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
    preset = c.get("/api/presets").json()[0]
    data = preset["data"]
    url = f"/api/presets/{preset['id']}"
    data["layout"]["cards_per_sheet"] = 11
    assert c.put(url, json={"data": data}).status_code == 422
    data["layout"]["cards_per_sheet"] = 4
    assert c.put(url, json={"data": data}).status_code == 200
    assert home.get_preset().layout.cards_per_sheet == 4
    cfg["intake"]["stable_wait_s"] = 2
    assert c.put("/api/config", json=cfg).status_code == 200
    assert json.loads(home.config_path.read_text())["intake"]["stable_wait_s"] == 2
    assert c.put("/api/config", json={"intake": {"bogus": 1}}).status_code == 422


def test_ingest_review_flow_and_files(client):
    c, home = client
    save_png(make_scan([(52, 60, 91, 55, 4), (152, 62, 89, 51, 0)]), home.root / "inbox" / "a.png")
    res = c.post("/api/ingest/create", json={}).json()["results"]
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
    assert c.post(f"/api/cards/{cid}/register").status_code == 200
    assert c.post(f"/api/cards/{cid}/register").status_code == 409
    assert c.post("/api/cards/9999/discard").status_code == 404
    assert c.post(f"/api/sheets/{job['sheets'][0]['id']}/reprint").status_code == 409


def _review_job(c, home):
    save_png(make_scan([(52, 60, 91, 55, 4), (152, 62, 89, 51, 0)]), home.root / "inbox" / "a.png")
    jid = c.post("/api/ingest").json()[0]["job_id"]
    assert c.get(f"/api/jobs/{jid}").json()["status"] == "review"
    cid = c.get("/api/cards", params={"status": "review"}).json()[0]["id"]
    return jid, cid


@pytest.mark.parametrize(("action", "reg"), [("register", "master"), ("discard", "discarded")])
def test_pending_review_action_preserves_detection_result(client, action, reg):
    c, home = client
    jid, cid = _review_job(c, home)
    response = c.post(f"/api/cards/{cid}/{action}")
    assert response.status_code == 200 and response.json()["reg"] == reg
    job = c.get(f"/api/jobs/{jid}").json()
    assert job["status"] == "review" and job["sheets"] == []
    assert cid in [card["id"] for card in c.get("/api/cards", params={"reg": reg}).json()]


def test_rotate_keeps_review_job_review(client):
    c, home = client
    jid, cid = _review_job(c, home)
    c.post(f"/api/cards/{cid}/rotate")
    assert c.get(f"/api/jobs/{jid}").json()["status"] == "review"


def test_bulk_print_continues_after_failure_and_old_reprint_cannot_send(tmp_path):
    from print_edit.adapters.base import PrinterError
    from print_edit.store.db import Store

    home = Home(tmp_path / "h")
    settings = Settings.model_validate({"print": {"output": "lp", "printer_name": "Q", "auto_print": False}})
    home.ensure(settings)
    home.save_settings(settings)
    calls = []

    class Printer:
        def send(self, pdf):
            calls.append(pdf.name)
            if pdf.name == "2.pdf":
                raise PrinterError("offline")

    c = TestClient(create_app(home, printer_factory=lambda _: Printer()))
    store = Store(home.db)
    store.add_job("JA", "scan.png", "a", "ok", [], 600)
    ids = [store.add_sheet("JA", f"jobs/JA/sheets/{i}.pdf", "held", []) for i in (1, 2, 3)]
    response = c.post("/api/bulk/sheets/print", json={"ids": ids}).json()
    assert (response["success"], response["failed"]) == (2, 1)
    assert [store.get_sheet(i)["status"] for i in ids] == ["sent", "held", "sent"]
    before = [store.get_sheet(i) for i in ids]
    assert c.post("/api/jobs/JA/reprint").status_code == 404
    assert calls == ["1.pdf", "2.pdf", "3.pdf"]
    assert [store.get_sheet(i) for i in ids] == before


def test_intake_status_counts_files_and_records_last_job(client):
    c, home = client
    inbox = home.root / "inbox"
    for name in ("empty.png", "noise.txt", ".hidden.PNG"):
        (inbox / name).write_bytes(b"" if name == "empty.png" else b"x")
    (inbox / "dir.jpg").mkdir()
    save_png(make_scan([(52, 60, 91, 55, 4)]), inbox / "valid.PNG")
    before = c.get("/api/info").json()
    assert before["pending_count"] == 1 and before["last_ingest_at"] is None
    jid = c.post("/api/ingest").json()[0]["job_id"]
    after = c.get("/api/info").json()
    assert after["pending_count"] == 0
    assert after["last_ingest_at"] == c.get(f"/api/jobs/{jid}").json()["created_at"]


def test_favicon_link_present(client):
    c, _ = client
    assert 'rel="icon"' in c.get("/").text


def test_launchd_watch_status_checks_registration_and_inbox(tmp_path, monkeypatch):
    import plistlib
    from subprocess import CompletedProcess, TimeoutExpired
    from print_edit.adapters.sources import launchd

    inbox = tmp_path / "inbox"
    plist = tmp_path / "agent.plist"
    plist.write_bytes(plistlib.dumps({"Label": "com.print-edit.ingest", "WatchPaths": [str(inbox)]}))
    monkeypatch.setattr(launchd.sys, "platform", "darwin")
    result = CompletedProcess([], 0, f"path = {plist}\nstate = not running\n", "")
    monkeypatch.setattr(launchd.subprocess, "run", lambda *a, **kw: result)
    assert launchd.watch_status(inbox) == "active"
    assert launchd.watch_status(tmp_path / "elsewhere") == "inactive"
    result.returncode, result.stderr = 113, "Could not find service"
    assert launchd.watch_status(inbox) == "inactive"
    result.stderr = "permission denied"
    assert launchd.watch_status(inbox) == "unknown"

    def timeout(*args, **kwargs):
        raise TimeoutExpired("launchctl", 2)

    monkeypatch.setattr(launchd.subprocess, "run", timeout)
    assert launchd.watch_status(inbox) == "unknown"
    monkeypatch.setattr(launchd.sys, "platform", "linux")
    assert launchd.watch_status(inbox) == "unavailable"
