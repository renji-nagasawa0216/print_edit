import json

import pytest
from fastapi.testclient import TestClient
from synth import make_scan, save_png

from print_edit.api.app import create_app
from print_edit.core.settings import Settings
from print_edit.home import Home


@pytest.fixture
def client(tmp_path):
    home = Home(tmp_path / "h")
    s = Settings.model_validate({"intake": {"stable_wait_s": 0}})
    home.ensure(s)
    home.save_settings(s)
    return TestClient(create_app(home)), home


def test_basic_endpoints(client):
    c, _ = client
    assert c.get("/api/config").json()["intake"]["expected_dpi"] == 600
    assert "properties" in c.get("/api/config/schema").json()
    assert c.get("/api/capacity").json() == {"capacity": 10, "columns": 2, "rows": 5, "card_rotated": False}
    assert c.get("/api/jobs").json() == []
    assert c.get("/api/jobs/nope").status_code == 404
    r = c.get("/")
    assert r.status_code == 200 and "print-edit" in r.text
    assert c.get("/static/app.js").status_code == 200
    assert len(c.get("/api/layout/preview").json()["slots"]) == 10


def test_put_config(client):
    c, home = client
    cfg = c.get("/api/config").json()
    cfg["layout"]["cards_per_sheet"] = 11
    assert c.put("/api/config", json=cfg).status_code == 422
    cfg["layout"]["cards_per_sheet"] = 4
    assert c.put("/api/config", json=cfg).status_code == 200
    assert json.loads(home.config_path.read_text())["layout"]["cards_per_sheet"] == 4
    assert c.put("/api/config", json={"intake": {"bogus": 1}}).status_code == 422


def test_ingest_review_flow_and_files(client):
    c, home = client
    save_png(make_scan([(52, 60, 91, 55, 4), (152, 62, 89, 51, 0)]), home.root / "inbox" / "a.png")
    res = c.post("/api/ingest").json()
    jid = res[0]["job_id"]
    job = c.get(f"/api/jobs/{jid}").json()
    assert len(job["cards"]) == 2 and len(job["sheets"]) == 1
    assert c.get("/api/jobs").json()[0]["id"] == jid
    rev = c.get("/api/cards", params={"status": "review"}).json()
    assert len(rev) == 1
    cid = rev[0]["id"]
    assert c.get("/files/" + rev[0]["image_path"]).status_code == 200
    assert c.get("/files/" + job["sheets"][0]["pdf_path"]).status_code == 200
    assert c.get("/files/db.sqlite3").status_code == 404
    assert c.get("/files/jobs/../db.sqlite3").status_code == 404
    assert c.get("/files/..%2F..%2Fetc/hosts").status_code == 404
    assert c.post(f"/api/cards/{cid}/rotate").status_code == 200
    assert c.post(f"/api/cards/{cid}/approve").status_code == 200
    assert c.post(f"/api/cards/{cid}/approve").status_code == 409
    assert c.post("/api/cards/9999/discard").status_code == 404
    assert c.post(f"/api/jobs/{jid}/reprint").status_code == 200


def _review_job(c, home):
    save_png(make_scan([(52, 60, 91, 55, 4), (152, 62, 89, 51, 0)]), home.root / "inbox" / "a.png")
    jid = c.post("/api/ingest").json()[0]["job_id"]
    assert c.get(f"/api/jobs/{jid}").json()["status"] == "review"
    cid = c.get("/api/cards", params={"status": "review"}).json()[0]["id"]
    return jid, cid


def test_approve_recomputes_job_status(client):
    c, home = client
    jid, cid = _review_job(c, home)
    r = c.post(f"/api/cards/{cid}/approve").json()
    assert r["delivery"] == {"ok": True, "error": None} and len(r["sheets"]) == 1
    job = c.get(f"/api/jobs/{jid}").json()
    assert job["status"] == "ok" and job["error"] is None and len(job["sheets"]) == 2


def test_discard_recomputes_job_status(client):
    c, home = client
    jid, cid = _review_job(c, home)
    assert c.post(f"/api/cards/{cid}/discard").json()["status"] == "discarded"
    assert c.get(f"/api/jobs/{jid}").json()["status"] == "ok"


def test_rotate_keeps_review_job_review(client):
    c, home = client
    jid, cid = _review_job(c, home)
    c.post(f"/api/cards/{cid}/rotate")
    assert c.get(f"/api/jobs/{jid}").json()["status"] == "review"


def test_approve_delivery_failure_reports_reason_and_job_error(tmp_path):
    from print_edit.adapters.base import PrinterError

    home = Home(tmp_path / "h")
    s = Settings.model_validate({"intake": {"stable_wait_s": 0}, "print": {"output": "lp", "printer_name": "Q"}})
    home.ensure(s)
    home.save_settings(s)

    class Printer:
        fail = False

        def send(self, pdf):
            if Printer.fail:
                raise PrinterError("lp 失敗: offline")

    c = TestClient(create_app(home, printer_factory=lambda _s: Printer()))
    jid, cid = _review_job(c, home)
    Printer.fail = True
    r = c.post(f"/api/cards/{cid}/approve").json()
    assert r["delivery"]["ok"] is False and "offline" in r["delivery"]["error"]
    assert r["card"]["status"] == "ok"
    job = c.get(f"/api/jobs/{jid}").json()
    assert job["status"] == "error" and "offline" in job["error"]


def test_favicon_link_present(client):
    c, _ = client
    assert 'rel="icon"' in c.get("/").text
