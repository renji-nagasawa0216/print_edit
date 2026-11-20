"""docs/spec.md 11.2 の機械判定 TC（ai_docs/specs/spec_11_2_tc.md）。画面 TC（R-09,10,13 / G-* / M-10 / V-01〜05）は対象外。

lp は実行しない: PATH 先頭に引数を記録するだけの偽 lp を置く（autouse）。printer_name は実在しないキュー名。
"""
from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import zlib
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from synth import make_scan, save_png

from print_edit.api.app import create_app
from print_edit.cli import main
from print_edit.core.settings import Settings
from print_edit.home import Home

MM = 25.4 / 72  # pt -> mm
PT = 72 / 25.4  # mm -> pt


# ================================================================ 共通部品
@pytest.fixture(autouse=True)
def fake_lp(tmp_path, monkeypatch):
    """実在の lp を絶対に実行しない。呼ばれたら LPLOG に引数を1行記録。LPPLAN の n 行目が n 回目の終了コード。"""
    d = tmp_path / "fakebin"
    d.mkdir()
    log, plan = tmp_path / "lp.log", tmp_path / "lp.plan"
    log.write_text("")
    (d / "lp").write_text(
        '#!/bin/sh\n'
        f'echo "$@" >> "{log}"\n'
        f'n=$(wc -l < "{log}" | tr -d " ")\n'
        f'rc=$(sed -n "${{n}}p" "{plan}" 2>/dev/null)\n'
        'exit ${rc:-0}\n'
    )
    (d / "lp").chmod(0o755)
    monkeypatch.setenv("PATH", f"{d}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.delenv("PRINT_EDIT_HOME", raising=False)

    class LP:
        def calls(self):
            return [ln for ln in log.read_text().splitlines() if ln.strip()]

        def clear(self):
            log.write_text("")

        def plan(self, *codes):
            plan.write_text("\n".join(str(c) for c in codes) + "\n")

    return LP()


@pytest.fixture
def lp(fake_lp):
    return fake_lp


def _merge(base, over):
    out = {k: dict(v) if isinstance(v, dict) else v for k, v in base.items()}
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


class Env:
    def __init__(self, tmp_path, over=None):
        self.home = Home(tmp_path / "h")
        base = {"intake": {"stable_wait_s": 0, "expected_dpi": 150}}
        s = Settings.model_validate(_merge(base, over))
        self.home.ensure(s)
        self.home.save_settings(s)
        self.c = TestClient(create_app(self.home))
        self.n = 0

    @property
    def inbox(self):
        return self.home.root / "inbox"

    def put(self, **sections):
        cfg = self.c.get("/api/config").json()
        for k, v in sections.items():
            cfg[k].update(v)
        r = self.c.put("/api/config", json=cfg)
        assert r.status_code == 200, r.text
        return r

    def drop_scan(self, n=1, kinds=None, name=None):
        """n 枚のカードを 2 列で並べたスキャンを inbox に置く（150 dpi・メタデータ 150）。"""
        self.n += 1
        kinds = kinds or ["ok"] * n
        rows = math.ceil(n / 2)
        spec = []
        for i, k in enumerate(kinds):
            w, h = (91, 55) if k == "ok" else (89, 51)
            spec.append((55 + 100 * (i % 2) + self.n % 7, 35 + 60 * (i // 2), w, h, 0))
        arr = make_scan(spec, dpi=150, size_mm=(210, 10 + 60 * rows), text=False)
        p = self.inbox / (name or f"s{self.n}.png")
        save_png(arr, p, 150)
        return p

    def ingest(self):
        r = self.c.post("/api/ingest")
        assert r.status_code == 200, r.text
        return r.json()

    def job(self, jid):
        return self.c.get(f"/api/jobs/{jid}").json()

    def db(self):
        con = sqlite3.connect(self.home.root / "db.sqlite3")
        con.row_factory = sqlite3.Row
        return con

    def q(self, sql, *a):
        con = self.db()
        try:
            return [dict(r) for r in con.execute(sql, a)]
        finally:
            con.close()

    def sheets_cards(self, jid):
        """シートごと（sheets.id 昇順）の、枠順のカード index 列。"""
        out = []
        for s in self.q("SELECT id FROM sheets WHERE job_id=? ORDER BY id", jid):
            rows = self.q(
                'SELECT c.idx AS idx FROM sheet_cards sc JOIN cards c ON c.id=sc.card_id '
                "WHERE sc.sheet_id=? ORDER BY sc.slot", s["id"])
            out.append([r["idx"] for r in rows])
        return out

    def abspdf(self, rel):
        p = Path(rel)
        return p if p.is_absolute() else self.home.root / p


@pytest.fixture
def mk(tmp_path):
    return lambda over=None: Env(tmp_path, over)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def page_mm(pdf):
    doc = pdfium.PdfDocument(str(pdf))
    w, h = doc[0].get_size()
    doc.close()
    return w * MM, h * MM


class Locker:
    CODE = ("import fcntl,sys\nf=open(sys.argv[1],'a+')\nfcntl.flock(f,fcntl.LOCK_EX)\n"
            "print('ready',flush=True)\nsys.stdin.read()\n")

    def __init__(self, path):
        self.p = subprocess.Popen([sys.executable, "-c", self.CODE, str(path)], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, text=True)
        assert self.p.stdout.readline().strip() == "ready"

    def release(self):
        if self.p.poll() is None:
            self.p.stdin.close()
            self.p.wait(timeout=10)


@pytest.fixture
def locker():
    made = []

    def make(path):
        lk = Locker(path)
        made.append(lk)
        return lk

    yield make
    for lk in made:
        lk.release()


def lock_free(path):
    with open(path, "a+") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        fcntl.flock(f, fcntl.LOCK_UN)
        return True


# ================================================================ 1. 再印刷
def _reprint_env(mk, lp, n=3, **print_over):
    e = mk()
    e.drop_scan(n)
    jid = e.ingest()[0]["job_id"]
    e.put(print={"output": "lp", "printer_name": "q1", "copies": 2, "lp_options": ["media=A4"], **print_over})
    lp.clear()
    return e, jid


def _same_path(a, b):
    return os.path.isabs(a) and os.path.realpath(a) == os.path.realpath(str(b))


def test_R01_reprint_sends_saved_pdf(mk, lp):
    e, jid = _reprint_env(mk, lp)
    job = e.job(jid)
    assert len(job["sheets"]) == 1
    pdf = e.abspdf(job["sheets"][0]["pdf_path"])
    h0, lay0 = sha(pdf), sha(pdf.with_name("01.layout.json"))
    rows0 = e.q("SELECT id, pdf_path FROM sheets WHERE job_id=?", jid)
    r = e.c.post(f"/api/jobs/{jid}/reprint")
    assert r.status_code == 200, r.text
    calls = lp.calls()
    assert len(calls) == 1
    args = calls[0].split()
    assert args[:-1] == ["-d", "q1", "-n", "2", "-o", "media=A4"]
    assert _same_path(args[-1], pdf) and args[-1].endswith("sheets/01.pdf")
    assert sha(pdf) == h0 and sha(pdf.with_name("01.layout.json")) == lay0
    assert e.q("SELECT id, pdf_path FROM sheets WHERE job_id=?", jid) == rows0


def test_R02_reprint_ignores_later_config_change(mk, lp):
    e, jid = _reprint_env(mk, lp)
    pdf = e.abspdf(e.job(jid)["sheets"][0]["pdf_path"])
    h0, lay0 = sha(pdf), sha(pdf.with_name("01.layout.json"))
    e.c.post(f"/api/jobs/{jid}/reprint")
    lp.clear()
    nfiles = sorted(p.name for p in pdf.parent.iterdir())
    nrows = e.q("SELECT COUNT(*) AS n FROM sheets")[0]["n"]
    e.put(print={"scale_x": 1.03, "scale_y": 0.97},
          layout={"mark_enabled": False, "paper_width_mm": 148, "paper_height_mm": 210})
    r = e.c.post(f"/api/jobs/{jid}/reprint")
    assert r.status_code == 200, r.text
    calls = lp.calls()
    assert len(calls) == 1 and _same_path(calls[0].split()[-1], pdf)
    assert sha(pdf) == h0
    w, h = page_mm(pdf)
    assert abs(w - 210) <= 0.1 and abs(h - 297) <= 0.1
    assert sha(pdf.with_name("01.layout.json")) == lay0
    assert sorted(p.name for p in pdf.parent.iterdir()) == nfiles
    assert e.q("SELECT COUNT(*) AS n FROM sheets")[0]["n"] == nrows


def test_R03_reprint_multiple_sheets_in_order(mk, lp):
    e, jid = _reprint_env(mk, lp, n=12)
    sheets = e.job(jid)["sheets"]
    assert len(sheets) == 2
    r = e.c.post(f"/api/jobs/{jid}/reprint")
    assert r.status_code == 200, r.text
    calls = lp.calls()
    assert len(calls) == 2
    p1, p2 = (e.abspdf(s["pdf_path"]) for s in sheets)
    assert p1.name == "01.pdf" and p2.name == "02.pdf"
    assert _same_path(calls[0].split()[-1], p1) and _same_path(calls[1].split()[-1], p2)


def _pdf_env(mk, lp, n=3):
    e = mk()
    e.drop_scan(n)
    jid = e.ingest()[0]["job_id"]
    lp.clear()
    return e, jid


def test_R04_pdf_output_sends_nothing(mk, lp):
    e, jid = _pdf_env(mk, lp)
    sheets = e.job(jid)["sheets"]
    pdf = e.abspdf(sheets[0]["pdf_path"])
    h0 = sha(pdf)
    files = sorted(p.name for p in pdf.parent.iterdir())
    r = e.c.post(f"/api/jobs/{jid}/reprint")
    assert r.status_code == 200
    assert lp.calls() == []
    assert sha(pdf) == h0 and sorted(p.name for p in pdf.parent.iterdir()) == files
    assert r.json() == {"sheets": [{"sheet_id": s["id"], "sent": True} for s in sheets], "output": "pdf"}


def test_R05_response_output_pdf(mk, lp):
    e, jid = _pdf_env(mk, lp)
    r = e.c.post(f"/api/jobs/{jid}/reprint")
    assert r.json()["output"] == "pdf"


def test_R06_response_output_lp_success(mk, lp):
    e, jid = _reprint_env(mk, lp)
    r = e.c.post(f"/api/jobs/{jid}/reprint")
    assert r.status_code != 400 and r.status_code == 200
    assert r.json()["output"] == "lp"
    assert len(lp.calls()) == 1


def test_R07_success_state_transition(mk, lp):
    e, jid = _reprint_env(mk, lp)
    assert {s["status"] for s in e.job(jid)["sheets"]} == {"created"}
    r = e.c.post(f"/api/jobs/{jid}/reprint")
    assert r.status_code == 200
    job = e.job(jid)
    assert {s["status"] for s in job["sheets"]} == {"sent"}
    assert {c["status"] for c in job["cards"]} == {"printed"}
    assert job["status"] == "ok"


def test_R08_lp_with_empty_printer_name(mk, lp):
    e, jid = _reprint_env(mk, lp, printer_name="")
    r = e.c.post(f"/api/jobs/{jid}/reprint")
    assert lp.calls() == []
    assert r.status_code == 400
    body = r.json()
    assert body["detail"] == "送信に失敗したシートがあります" and body["output"] == "lp"


def test_R11_partial_success(mk, lp):
    e, jid = _reprint_env(mk, lp, n=12)
    lp.plan(0, 1)
    r = e.c.post(f"/api/jobs/{jid}/reprint")
    assert len(lp.calls()) == 2
    assert r.status_code == 400
    body = r.json()
    assert body["detail"] == "送信に失敗したシートがあります" and body["output"] == "lp"
    assert len(body["sheets"]) == 2
    assert sorted(s["sent"] for s in body["sheets"]) == [False, True]


def test_R12_unknown_job_404(mk, lp):
    e = mk()
    r = e.c.post("/api/jobs/9999/reprint")
    assert r.status_code == 404
    assert lp.calls() == []


# ================================================================ 2. duplicate の容量超過
def _dup(mk, n=None, kinds=None, cps=None):
    e = mk({"print": {"timing": "duplicate"}, "layout": {"cards_per_sheet": cps}})
    e.drop_scan(n or len(kinds), kinds)
    res = e.ingest()
    return e, res[0]["job_id"]


def test_D01_twelve_cards(mk):
    e, jid = _dup(mk, 12)
    s = e.sheets_cards(jid)
    assert len(s) == 2
    assert s[0] == list(range(1, 11))
    assert s[1] == [11, 12] * 5
    assert {x for sh in s for x in sh} == set(range(1, 13))


def test_D02_exact_capacity(mk):
    e, jid = _dup(mk, 10)
    assert e.sheets_cards(jid) == [list(range(1, 11))]


def test_D03_capacity_plus_one(mk):
    e, jid = _dup(mk, 11)
    assert e.sheets_cards(jid) == [list(range(1, 11)), [11] * 10]


def test_D04_three_cards(mk):
    e, jid = _dup(mk, 3)
    assert e.sheets_cards(jid) == [[1, 2, 3, 1, 2, 3, 1, 2, 3, 1]]


def test_D05_one_card(mk):
    e, jid = _dup(mk, 1)
    assert e.sheets_cards(jid) == [[1] * 10]


def test_D06_double_capacity_plus(mk):
    e, jid = _dup(mk, 24)
    assert e.sheets_cards(jid) == [list(range(1, 11)), list(range(11, 21)), [21, 22, 23, 24, 21, 22, 23, 24, 21, 22]]


def test_D07_cards_per_sheet_4(mk):
    e, jid = _dup(mk, 9, cps=4)
    assert e.sheets_cards(jid) == [[1, 2, 3, 4], [5, 6, 7, 8], [9, 9, 9, 9]]
    sheets = e.job(jid)["sheets"]
    lay = json.loads(e.abspdf(sheets[2]["pdf_path"]).with_name("03.layout.json").read_text())
    assert len(lay["slots"]) == 4


def test_D08_review_not_placed(mk):
    e, jid = _dup(mk, kinds=["ok"] * 10 + ["review"] * 2)
    assert e.sheets_cards(jid) == [list(range(1, 11))]
    assert {c["idx"] for c in e.job(jid)["cards"] if c["status"] == "review"} == {11, 12}


def test_D09_approved_card_gets_its_own_sheet(mk):
    e, jid = _dup(mk, kinds=["ok"] * 10 + ["review"] * 2)
    c11 = next(c for c in e.job(jid)["cards"] if c["idx"] == 11)
    r = e.c.post(f"/api/cards/{c11['id']}/approve")
    assert r.status_code == 200, r.text
    assert next(c for c in e.job(jid)["cards"] if c["idx"] == 11)["status"] != "review"
    assert [11] * 10 in e.sheets_cards(jid)


def test_D10_total_rows(mk):
    e, jid = _dup(mk, 12)
    rows = e.q("SELECT sc.card_id FROM sheet_cards sc JOIN sheets s ON s.id=sc.sheet_id WHERE s.job_id=?", jid)
    assert len({r["card_id"] for r in rows}) == 12
    assert len(rows) == 20


def test_D11_zero_ok_cards_no_sheet(mk):
    e, jid = _dup(mk, kinds=["review"] * 3)
    assert e.q("SELECT COUNT(*) AS n FROM sheets WHERE job_id=?", jid)[0]["n"] == 0
    assert not list((e.home.root / "jobs" / jid).glob("sheets/*.pdf"))


# ================================================================ 3. PDF のラスタライズ解像度
def make_pdf(path, w_mm, h_mm, pages=1, embed_png=None):
    c = canvas.Canvas(str(path), pagesize=(w_mm * PT, h_mm * PT))
    for i in range(pages):
        c.setFillGray(0.1)
        c.rect(0, 0, w_mm * PT, h_mm * PT, stroke=0, fill=1)
        c.setFillGray(0.92)
        c.rect(w_mm * PT * 0.2, h_mm * PT * 0.2, 91 * PT, 55 * PT, stroke=0, fill=1)
        if embed_png is not None:
            c.drawImage(ImageReader(str(embed_png)), 0, 0, w_mm * PT, h_mm * PT)
        c.showPage()
    c.save()


def cfg_file(tmp_path, **sections):
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps(_merge({"intake": {"stable_wait_s": 0}}, sections)))
    return p


def run_detect(tmp_path, capsys, pdf, dpi=None, expected_dpi=600):
    cfg = cfg_file(tmp_path, intake={"expected_dpi": expected_dpi})
    out = tmp_path / "out"
    argv = ["detect", str(pdf), "--out", str(out), "--home", str(tmp_path / "h"), "--config", str(cfg)]
    if dpi is not None:
        argv += ["--dpi", str(dpi)]
    code = main(argv)
    cap = capsys.readouterr()
    assert code == 0, cap.err
    return json.loads(cap.out)


def near(a, b, tol=1):
    return abs(a - b) <= tol


def test_P01_expected_dpi_used(tmp_path, capsys):
    make_pdf(tmp_path / "a4.pdf", 210, 297)
    d = run_detect(tmp_path, capsys, tmp_path / "a4.pdf", expected_dpi=300)
    s = d["source"]
    assert near(s["width_px"], 2480) and near(s["height_px"], 3508)
    assert s["dpi"] == 300 and s["dpi_source"] == "config"
    assert "dpi_mismatch" not in d["warnings"]


def test_P02_option_dpi_wins(tmp_path, capsys):
    make_pdf(tmp_path / "a4.pdf", 210, 297)
    d = run_detect(tmp_path, capsys, tmp_path / "a4.pdf", dpi=150, expected_dpi=300)
    s = d["source"]
    assert near(s["width_px"], 1240) and near(s["height_px"], 1754)
    assert s["dpi"] == 150 and s["dpi_source"] == "option"
    assert "dpi_mismatch" not in d["warnings"]


def test_P03_default_600_card_size(tmp_path, capsys):
    make_pdf(tmp_path / "card.pdf", 91, 55)
    d = run_detect(tmp_path, capsys, tmp_path / "card.pdf", expected_dpi=600)
    s = d["source"]
    assert near(s["width_px"], 2150) and near(s["height_px"], 1299)
    assert s["dpi"] == 600 and s["dpi_source"] == "config"


def test_P04_embedded_image_dpi_ignored(tmp_path, capsys):
    img = tmp_path / "emb.png"
    Image.new("L", (2480, 3508), 120).save(img, dpi=(300, 300))
    make_pdf(tmp_path / "emb.pdf", 210, 297, embed_png=img)
    d = run_detect(tmp_path, capsys, tmp_path / "emb.pdf", expected_dpi=600)
    assert d["source"]["dpi"] == 600 and d["source"]["dpi_source"] == "config"
    assert "dpi_mismatch" not in d["warnings"]


def test_P05_ingest_pdf_uses_expected_dpi(tmp_path, capsys):
    home = tmp_path / "h"
    (home / "inbox").mkdir(parents=True)
    cfg = cfg_file(tmp_path, intake={"expected_dpi": 300})
    make_pdf(home / "inbox" / "SCAN.PDF", 210, 297)
    code = main(["ingest", "--home", str(home), "--config", str(cfg)])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and len(out) == 1
    jid = out[0]["job_id"]
    con = sqlite3.connect(home / "db.sqlite3")
    try:
        assert con.execute("SELECT dpi FROM jobs WHERE id=?", (jid,)).fetchone()[0] == 300
    finally:
        con.close()
    with Image.open(home / "jobs" / str(jid) / "source.png") as im:
        assert near(im.size[0], 2480) and near(im.size[1], 3508)


def test_P06_multipage(tmp_path, capsys):
    make_pdf(tmp_path / "m.pdf", 210, 297, pages=2)
    d = run_detect(tmp_path, capsys, tmp_path / "m.pdf", dpi=150)
    assert "pdf_multipage_ignored" in d["warnings"]
    assert near(d["source"]["width_px"], 1240) and near(d["source"]["height_px"], 1754)
    assert d["source"]["dpi_source"] == "option"


def test_P07_a4_600dpi(tmp_path, capsys):
    make_pdf(tmp_path / "a4.pdf", 210, 297)
    d = run_detect(tmp_path, capsys, tmp_path / "a4.pdf", expected_dpi=600)
    assert near(d["source"]["width_px"], 4961) and near(d["source"]["height_px"], 7016)
    assert d["source"]["dpi_source"] == "config"


# ================================================================ 4. POST /api/ingest の 409
def test_I01_locked_returns_409(mk, locker):
    e = mk()
    p = e.drop_scan(1)
    locker(e.home.root / "ingest.lock")
    r = e.c.post("/api/ingest")
    assert r.status_code == 409
    assert r.json() == {"detail": "別の取り込みが実行中です"}
    assert p.exists() and e.c.get("/api/jobs").json() == []


def test_I02_cli_locked_unchanged(mk, locker, capsys):
    e = mk()
    p = e.drop_scan(1)
    locker(e.home.root / "ingest.lock")
    code = main(["ingest", "--home", str(e.home.root)])
    out = capsys.readouterr().out
    assert code == 0 and json.loads(out) == [] and out.strip() == "[]"
    assert p.exists()


def test_I03_after_unlock_200(mk, locker):
    e = mk()
    e.drop_scan(1)
    lk = locker(e.home.root / "ingest.lock")
    assert e.c.post("/api/ingest").status_code == 409
    lk.release()
    r = e.c.post("/api/ingest")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1 and {"job_id", "status", "cards", "sheets"} <= set(body[0])


def test_I04_empty_inbox(mk):
    r = mk().c.post("/api/ingest")
    assert r.status_code == 200 and r.json() == []


def test_I05_three_pngs(mk):
    e = mk()
    for i in range(3):
        e.drop_scan(1)
    r = e.c.post("/api/ingest")
    assert r.status_code == 200 and len(r.json()) == 3


def test_I06_with_error(mk):
    e = mk()
    (e.inbox / "bad.png").write_bytes(b"this is not a png")
    e.drop_scan(1, name="good.png")
    r = e.c.post("/api/ingest")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2 and sum(1 for x in body if x["status"] == "error") == 1


def test_I07_lock_not_leaked(mk, locker):
    e = mk()
    e.drop_scan(1)
    lk = locker(e.home.root / "ingest.lock")
    assert e.c.post("/api/ingest").status_code == 409
    lk.release()
    assert e.c.post("/api/ingest").status_code == 200
    assert lock_free(e.home.root / "ingest.lock")
    e.drop_scan(1)
    assert e.c.post("/api/ingest").status_code == 200
    assert lock_free(e.home.root / "ingest.lock")


# ================================================================ 6.1 トンボ設定値
LAYOUT_KEYS = ("mark_style", "mark_dash_mm", "mark_gap_mm")


def test_M01_defaults(mk):
    lay = mk().c.get("/api/config").json()["layout"]
    assert lay["mark_style"] == "solid" and lay["mark_dash_mm"] == 1 and lay["mark_gap_mm"] == 1


def _put_layout(e, **kw):
    cfg = e.c.get("/api/config").json()
    cfg["layout"].update(kw)
    return e.c.put("/api/config", json=cfg)


def test_M02_save_and_get(mk):
    e = mk()
    assert _put_layout(e, mark_style="dashed", mark_dash_mm=2, mark_gap_mm=0.5).status_code == 200
    lay = e.c.get("/api/config").json()["layout"]
    assert (lay["mark_style"], lay["mark_dash_mm"], lay["mark_gap_mm"]) == ("dashed", 2, 0.5)


def test_M03_invalid_style(mk):
    e = mk()
    before = e.c.get("/api/config").json()
    assert _put_layout(e, mark_style="dotted").status_code == 422
    assert e.c.get("/api/config").json() == before


def test_M04_dash_zero(mk):
    assert _put_layout(mk(), mark_style="dashed", mark_dash_mm=0).status_code == 422


def test_M05_gap_zero(mk):
    assert _put_layout(mk(), mark_style="dashed", mark_gap_mm=0).status_code == 422


def test_M06_negative(mk):
    assert _put_layout(mk(), mark_style="dashed", mark_dash_mm=-1).status_code == 422


def test_M07_just_above_lower_bound(mk):
    assert _put_layout(mk(), mark_style="dashed", mark_dash_mm=0.01, mark_gap_mm=0.01).status_code == 200


def test_M08_solid_still_rejects_nonpositive(mk):
    e = mk()
    assert _put_layout(e, mark_style="solid", mark_dash_mm=0).status_code == 422
    assert _put_layout(e, mark_gap_mm=-1).status_code == 422


def _deref(schema, node):
    while isinstance(node, dict) and "$ref" in node:
        cur = schema
        for part in node["$ref"].lstrip("#/").split("/"):
            cur = cur[part]
        node = cur
    if isinstance(node, dict) and "allOf" in node and len(node["allOf"]) == 1:
        return _deref(schema, node["allOf"][0])
    return node


def test_M09_json_schema(mk):
    sc = mk().c.get("/api/config/schema").json()
    lay = _deref(sc, sc["properties"]["layout"])
    props = lay["properties"]
    ms = _deref(sc, props["mark_style"])
    opts = ms.get("enum") or [x.get("const") for x in ms.get("anyOf", ms.get("oneOf", []))]
    assert sorted(opts) == ["dashed", "solid"] and len(opts) == 2
    for k in ("mark_dash_mm", "mark_gap_mm"):
        p = _deref(sc, props[k])
        assert p["type"] == "number" and p["default"] == 1


# ================================================================ 6.2 PDF と layout.json
def card_pngs(d, n):
    d.mkdir(parents=True, exist_ok=True)
    ps = []
    for i in range(n):
        p = d / f"{i + 1:02d}.png"
        Image.new("L", (2150, 1299), 200).save(p)
        ps.append(str(p))
    return ps


def impose(tmp_path, tag, n=10, layout=None, device=None, print_=None):
    work = tmp_path / tag
    work.mkdir()
    cfg = work / "cfg.json"
    cfg.write_text(json.dumps({k: v for k, v in (("layout", layout), ("device", device), ("print", print_)) if v}))
    pdf = work / "o.pdf"
    code = main(["impose", *card_pngs(work / "c", n), "--out", str(pdf), "--home", str(work / "h"),
                 "--config", str(cfg)])
    assert code == 0
    return pdf


def layout_of(pdf):
    return json.loads(Path(str(pdf) + ".layout.json").read_text())


def content_stream(pdf):
    raw = Path(pdf).read_bytes()
    outs = []
    for m in re.finditer(rb"<<((?:(?!endobj).)*?)>>\s*stream\r?\n(.*?)\s*endstream", raw, re.S):
        hdr, body = m.group(1), m.group(2).strip()
        if b"/Image" in hdr or b"/XObject" in hdr and b"/Subtype /Form" not in hdr:
            continue
        if b"ASCII85" in hdr:
            body = base64.a85decode(body[:-2] if body.endswith(b"~>") else body, adobe=False)
        if b"Flate" in hdr:
            body = zlib.decompress(body)
        outs.append(body.decode("latin1"))
    return "\n".join(outs)


NUM = r"(-?[0-9.]+)"


def parse_ops(stream):
    """トンボのストローク列。各要素は dict(x1,y1,x2,y2 pt, width, gray, dash(list), phase)。"""
    width, gray, dash, phase = None, None, [], 0.0
    segs = []
    for ln in stream.splitlines():
        ln = ln.strip()
        if m := re.fullmatch(rf"{NUM} w", ln):
            width = float(m.group(1))
        elif m := re.fullmatch(rf"{NUM} G", ln):
            gray = float(m.group(1))
        elif m := re.fullmatch(rf"\[([^\]]*)\] {NUM} d", ln):
            dash = [float(x) for x in m.group(1).split()]
            phase = float(m.group(2))
        elif m := re.fullmatch(rf"n {NUM} {NUM} m {NUM} {NUM} l S", ln):
            x1, y1, x2, y2 = (float(g) for g in m.groups())
            segs.append(dict(x1=x1, y1=y1, x2=x2, y2=y2, width=width, gray=gray, dash=list(dash), phase=phase))
    return segs


def dash_ops(stream):
    return re.findall(r"^\[[^\]]*\] \S+ d$", stream, re.M)


def approx(a, b, tol=0.01):
    return abs(a - b) <= tol


def dash_is(seg, arr):
    return len(seg["dash"]) == len(arr) and all(approx(a, b) for a, b in zip(seg["dash"], arr)) and seg["phase"] == 0


def find_left_top(segs):
    """左上の水平トンボ: y=810.71 pt（11 mm）で x が 10〜13 mm 付近の線分"""
    c = [s for s in segs if approx(s["y1"], 810.71, 0.05) and approx(s["y2"], 810.71, 0.05)
         and max(s["x1"], s["x2"]) < 40 and min(s["x1"], s["x2"]) < 36]
    assert len(c) == 1, c
    return c[0]


DASHED = {"mark_style": "dashed", "mark_dash_mm": 1, "mark_gap_mm": 1}


def test_M11_default_dash_all_marks(tmp_path):
    pdf = impose(tmp_path, "a", layout=DASHED)
    segs = parse_ops(content_stream(pdf))
    assert len(segs) == len(layout_of(pdf)["marks"]) > 0
    assert all(dash_is(s, [2.835, 2.835]) for s in segs), [s["dash"] for s in segs][:3]


def test_M12_arbitrary_values(tmp_path):
    pdf = impose(tmp_path, "a", layout={"mark_style": "dashed", "mark_dash_mm": 2, "mark_gap_mm": 0.5})
    segs = parse_ops(content_stream(pdf))
    assert len(segs) == len(layout_of(pdf)["marks"])
    assert all(dash_is(s, [5.669, 1.417]) for s in segs)


def test_M13_starts_on_card_side(tmp_path):
    pdf = impose(tmp_path, "a", layout=DASHED)
    s = find_left_top(parse_ops(content_stream(pdf)))
    assert approx(s["x1"], 36.85) and approx(s["y1"], 810.71)
    assert approx(s["x2"], 28.35) and approx(s["y2"], 810.71)
    assert s["phase"] == 0


def test_M14_width_and_gray_same_as_solid(tmp_path):
    base = {"mark_gray": 128, "mark_width_mm": 0.1}
    a = parse_ops(content_stream(impose(tmp_path, "s", layout={**base, "mark_style": "solid"})))
    b = parse_ops(content_stream(impose(tmp_path, "d", layout={**base, **DASHED})))
    assert a and b
    for s in a + b:
        assert approx(s["width"], 0.283, 0.001) and approx(s["gray"], 0.502, 0.001)
    assert not any(s["dash"] for s in a) and all(s["dash"] for s in b)


GOLDEN_SOLID_OPS = """0 G
.283465 w
n 39.68504 822.0472 m 39.68504 813.5433 l S
n 39.68504 28.34646 m 39.68504 19.84252 l S
n 297.6378 822.0472 m 297.6378 813.5433 l S
n 297.6378 28.34646 m 297.6378 19.84252 l S
n 555.5906 822.0472 m 555.5906 813.5433 l S
n 555.5906 28.34646 m 555.5906 19.84252 l S
n 28.34646 810.7087 m 36.85039 810.7087 l S
n 558.4252 810.7087 m 566.9291 810.7087 l S
n 28.34646 654.8031 m 36.85039 654.8031 l S
n 558.4252 654.8031 m 566.9291 654.8031 l S
n 28.34646 498.8976 m 36.85039 498.8976 l S
n 558.4252 498.8976 m 566.9291 498.8976 l S
n 28.34646 342.9921 m 36.85039 342.9921 l S
n 558.4252 342.9921 m 566.9291 342.9921 l S
n 28.34646 187.0866 m 36.85039 187.0866 l S
n 558.4252 187.0866 m 566.9291 187.0866 l S
n 28.34646 31.1811 m 36.85039 31.1811 l S
n 558.4252 31.1811 m 566.9291 31.1811 l S"""  # cfbdd2d（11.2 実装前）で 10 枚・既定設定の impose が出した内容


def test_M15_solid_matches_pre_11_2_golden(tmp_path):
    st = content_stream(impose(tmp_path, "a"))
    i = st.index("0 G")
    lines = [ln.strip() for ln in st[i:].splitlines() if ln.strip()]
    lines = [ln for ln in lines if not re.fullmatch(r"\[\s*\] \S+ d", ln)]
    assert lines == GOLDEN_SOLID_OPS.splitlines()
    assert not any(re.fullmatch(r"\[\s*[0-9.]+[^\]]*\] \S+ d", ln) for ln in lines)


def test_M16_coordinates_independent_of_style(tmp_path):
    a = layout_of(impose(tmp_path, "s", layout={"mark_style": "solid"}))
    b = layout_of(impose(tmp_path, "d", layout=DASHED))
    assert a["marks"] == b["marks"]
    assert a["slots"] == b["slots"] and a["printable_mm"] == b["printable_mm"] and a["capacity"] == b["capacity"]
    assert all(set(m) == {"x1", "y1", "x2", "y2"} for m in b["marks"] + a["marks"])


def test_M17_all_pages(tmp_path):
    pdf = impose(tmp_path, "a", n=12, layout=DASHED)
    pages = [pdf, pdf.with_name("o-2.pdf")]
    assert all(p.exists() for p in pages)
    for p in pages:
        segs = parse_ops(content_stream(p))
        assert segs and all(dash_is(s, [2.835, 2.835]) for s in segs)


def test_M18_marks_disabled(tmp_path):
    pdf = impose(tmp_path, "a", layout={**DASHED, "mark_enabled": False})
    st = content_stream(pdf)
    assert parse_ops(st) == [] and dash_ops(st) == []
    assert layout_of(pdf)["marks"] == []


def test_M19_dash_longer_than_mark(tmp_path):
    pdf = impose(tmp_path, "a", layout={"mark_style": "dashed", "mark_dash_mm": 5, "mark_gap_mm": 1,
                                        "mark_length_mm": 3})
    segs = parse_ops(content_stream(pdf))
    assert segs and all(dash_is(s, [14.173, 2.835]) for s in segs)
    for m in layout_of(pdf)["marks"]:
        assert approx(math.hypot(m["x2"] - m["x1"], m["y2"] - m["y1"]), 3.0)


def dash_xs_mm(seg):
    """破線の実線区間を x(mm) の組で返す（開始位相 0）。"""
    d, g = seg["dash"]
    length = math.hypot(seg["x2"] - seg["x1"], seg["y2"] - seg["y1"])
    out, t = [], 0.0
    while t < length - 1e-9:
        a, b = t, min(t + d, length)
        xa = seg["x1"] + (seg["x2"] - seg["x1"]) * a / length
        xb = seg["x1"] + (seg["x2"] - seg["x1"]) * b / length
        out.append((xa * MM, xb * MM))
        t += d + g
    return out


def test_M20_dash_fits_in_length(tmp_path):
    pdf = impose(tmp_path, "a", layout={"mark_style": "dashed", "mark_dash_mm": 1, "mark_gap_mm": 1,
                                        "mark_length_mm": 3})
    s = find_left_top(parse_ops(content_stream(pdf)))
    iv = dash_xs_mm(s)
    assert len(iv) == 2
    assert approx(iv[0][0], 13, 0.02) and approx(iv[0][1], 12, 0.02)
    assert approx(iv[1][0], 11, 0.02) and approx(iv[1][1], 10, 0.02)


def test_M21_clipped_mark_starts_card_side(tmp_path):
    pdf = impose(tmp_path, "a", layout={**DASHED, "mark_length_mm": 3, "mark_offset_mm": 1},
                 device={"unprintable_mm": 11})
    segs = parse_ops(content_stream(pdf))
    c = [s for s in segs if approx(s["y1"], 810.71, 0.05) and approx(s["y2"], 810.71, 0.05)
         and approx(s["x1"], 36.85, 0.05)]
    assert len(c) == 1
    s = c[0]
    assert approx(s["x2"], 31.18, 0.05) and dash_is(s, [2.835, 2.835])
    ends = [{(round(m["x1"], 2), round(m["y1"], 2)), (round(m["x2"], 2), round(m["y2"], 2))}
            for m in layout_of(pdf)["marks"]]
    assert {(13.0, 11.0), (11.0, 11.0)} in ends


def test_M22_scale_does_not_stretch_dash(tmp_path):
    pdf = impose(tmp_path, "a", layout=DASHED, print_={"scale_x": 1.05, "scale_y": 1.05})
    segs = parse_ops(content_stream(pdf))
    assert segs
    for s in segs:
        assert dash_is(s, [2.835, 2.835]) and approx(s["width"], 0.283, 0.001)


# ================================================================ 6.3 プレビュー API
def test_V06_preview_keys(mk):
    e = mk()
    solid = e.c.get("/api/layout/preview").json()
    assert solid["mark_style"] == "solid" and "slots" in solid
    e.put(layout={"mark_style": "dashed", "mark_dash_mm": 2, "mark_gap_mm": 0.5})
    d = e.c.get("/api/layout/preview").json()
    assert d["mark_style"] == "dashed" and d["mark_dash_mm"] == 2 and d["mark_gap_mm"] == 0.5
    assert set(solid) <= set(d) and "slots" in d
