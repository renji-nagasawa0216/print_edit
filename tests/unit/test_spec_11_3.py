"""docs/spec.md 11.3 の機械判定 TC（ai_docs/specs/spec_11_3_tc.md の「確定版」＋「差し替え」）。

画面 TC（N-32,33,34,35,36,37,38,40,41,42,50,56,57）は対象外。
lp は実行しない: PATH 先頭に引数を記録するだけの偽 lp を置く（autouse）。printer_name は実在しないキュー名 "Q1"。
共通前提: cards_per_sheet=2・ok カードのみ・printer_name="Q1"・copies=1（TC が別に書くときはそちら）。
"""
from __future__ import annotations

import io
import json
import os
import sqlite3
from collections import Counter
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from print_edit.api.app import create_app
from print_edit.cli import main
from print_edit.core.settings import Settings
from print_edit.home import Home

from synth import make_scan, save_png

import math

MM = 25.4 / 72  # pt -> mm
DETAIL409 = "印刷待ちではないシートです"


# ================================================================ 共通部品
@pytest.fixture(autouse=True)
def fake_lp(tmp_path, monkeypatch):
    """実在の lp を絶対に実行しない。呼ばれたら引数を1行記録。plan の n 行目が n 回目の終了コード。"""
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
        self.home = Home(Path(tmp_path) / "h")
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

    def drop_scan(self, n=1, kinds=None):
        """n 枚のカードを 2 列で並べたスキャンを inbox に置く（150 dpi・メタデータ 150）。review は寸法違い。"""
        self.n += 1
        kinds = kinds or ["ok"] * n
        rows = math.ceil(len(kinds) / 2)
        spec = []
        for i, k in enumerate(kinds):
            w, h = (91, 55) if k == "ok" else (89, 51)
            spec.append((55 + 100 * (i % 2) + self.n % 7, 35 + 60 * (i // 2), w, h, 0))
        arr = make_scan(spec, dpi=150, size_mm=(210, 10 + 60 * rows), text=False)
        p = self.inbox / f"s{self.n}.png"
        save_png(arr, p, 150)
        return p

    def ingest(self):
        r = self.c.post("/api/ingest")
        assert r.status_code == 200, r.text
        return r.json()

    def cli_ingest(self, capsys):
        capsys.readouterr()
        code = main(["ingest", "--home", str(self.home.root)])
        out = capsys.readouterr().out
        return code, json.loads(out)

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

    def x(self, sql, *a):
        con = self.db()
        try:
            con.execute(sql, a)
            con.commit()
        finally:
            con.close()

    def sheets_cards(self, jid):
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

    # ---- 11.3 用
    def held(self):
        r = self.c.get("/api/sheets", params={"status": "held"})
        assert r.status_code == 200, r.text
        return r.json()

    def sheet(self, sid):
        return self.q("SELECT * FROM sheets WHERE id=?", sid)[0]

    def sheet_card_status(self, sid):
        return [r["status"] for r in self.q(
            "SELECT DISTINCT c.id AS id, c.status AS status FROM sheet_cards sc JOIN cards c ON c.id=sc.card_id "
            "WHERE sc.sheet_id=? ORDER BY c.id", sid)]

    def job_status(self, jid):
        return self.q("SELECT status FROM jobs WHERE id=?", jid)[0]["status"]

    def n_sheets(self, jid=None):
        if jid is None:
            return self.q("SELECT COUNT(*) AS n FROM sheets")[0]["n"]
        return self.q("SELECT COUNT(*) AS n FROM sheets WHERE job_id=?", jid)[0]["n"]

    def print_(self, sid):
        return self.c.post(f"/api/sheets/{sid}/print")

    def discard(self, sid):
        return self.c.post(f"/api/sheets/{sid}/discard")

    def snap(self):
        """全シートと全カードの status（変化なしの確認用）。"""
        return (self.q("SELECT id, status FROM sheets ORDER BY id"), self.q("SELECT id, status FROM cards ORDER BY id"))


@pytest.fixture
def mk(tmp_path):
    return lambda over=None: Env(tmp_path, over)


def over(cps=2, output="lp", auto=False, timing="per_scan", printer="Q1", **p):
    return {"layout": {"cards_per_sheet": cps},
            "print": {"output": output, "auto_print": auto, "timing": timing, "printer_name": printer,
                      "copies": 1, **p}}


def lp_args(line):
    return line.split()


def one_sheet(e):
    """1 枚スキャンを取り込み、できた 1 シートの id を返す（API 経由）。"""
    e.drop_scan(1)
    out = e.ingest()
    return e.job(out[0]["job_id"])["sheets"][0]["id"]


def mkstates(e, lp, kinds):
    """kinds の順に、各 status のシートを 1 件ずつ作る。{kind: sheet_id}。"""
    res = {}
    for k in kinds:
        if k == "sent":
            e.put(print={"output": "lp", "auto_print": True, "printer_name": "Q1"})
            lp.plan(0)
            res[k] = one_sheet(e)
        elif k == "error":
            e.put(print={"output": "lp", "auto_print": True, "printer_name": "Q1"})
            lp.plan(1)
            lp.clear()
            res[k] = one_sheet(e)
            lp.plan(0)
        elif k == "created":
            e.put(print={"output": "pdf"})
            res[k] = one_sheet(e)
        elif k in ("held", "discarded"):
            e.put(print={"output": "lp", "auto_print": False, "printer_name": "Q1"})
            sid = one_sheet(e)
            if k == "discarded":
                assert e.discard(sid).status_code == 200
            res[k] = sid
    lp.clear()
    return res


def mixed_fill(e, a_kinds=None):
    """fill・cps=2。job A（1 枚 ok ＋任意の review）と job B（1 枚 ok）のカードが載った混在 held シートを作る。"""
    e.drop_scan(kinds=a_kinds or ["ok"])
    ja = e.ingest()[0]["job_id"]
    e.drop_scan(1)
    jb = e.ingest()[0]["job_id"]
    h = e.held()
    assert len(h) == 1 and h[0]["job_id"] is None
    return ja, jb, h[0]["id"]


def png_of(e, sid):
    r = e.c.get(f"/api/sheets/{sid}/image.png")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].split(";")[0] == "image/png"
    return Image.open(io.BytesIO(r.content))


def in_tol(im, w=2480, h=3508, t=1):
    return abs(im.size[0] - w) <= t and abs(im.size[1] - h) <= t


# ================================================================ 正常系（決定表）
def test_N01_lp_true_per_scan_sends(mk, lp, capsys):
    e = mk(over(auto=True))
    e.drop_scan(3)
    code, out = e.cli_ingest(capsys)
    # N-01 改: cards・sheets は整数の件数
    assert code == 0 and len(out) == 1 and out[0]["status"] == "ok"
    assert out[0]["cards"] == 3 and out[0]["sheets"] == 2
    assert type(out[0]["cards"]) is int and type(out[0]["sheets"]) is int
    job = e.job(out[0]["job_id"])
    assert len(job["sheets"]) == 2 and e.n_sheets(out[0]["job_id"]) == 2
    calls = lp.calls()
    assert len(calls) == 2
    for c, s in zip(calls, job["sheets"]):
        a = lp_args(c)
        assert a[:4] == ["-d", "Q1", "-n", "1"] and a[-1].endswith(".pdf")
        assert os.path.realpath(a[-1]) == os.path.realpath(str(e.abspdf(s["pdf_path"])))
    assert [s["status"] for s in job["sheets"]] == ["sent", "sent"]
    assert [c["status"] for c in job["cards"]] == ["printed"] * 3


def test_N02_lp_false_holds(mk, lp, capsys):
    e = mk(over(auto=False))
    e.drop_scan(3)
    code, out = e.cli_ingest(capsys)
    assert code == 0 and len(out) == 1
    jid = out[0]["job_id"]
    assert lp.calls() == []
    job = e.job(jid)
    assert [s["status"] for s in job["sheets"]] == ["held", "held"]
    assert len(list((e.home.root / "jobs" / jid / "sheets").glob("*.pdf"))) == 2
    assert [c["status"] for c in job["cards"]] == ["held"] * 3
    assert job["status"] == "ok"


def _pdf_run(tmp_path, name, auto, lp, capsys, n=3):
    sub = tmp_path / name
    sub.mkdir()
    e = Env(sub, over(output="pdf", auto=auto))
    e.drop_scan(n)
    code, out = e.cli_ingest(capsys)
    job = e.job(out[0]["job_id"])
    pdfs = len(list((e.home.root / "jobs" / out[0]["job_id"] / "sheets").glob("*.pdf")))
    return e, code, job, pdfs


def test_N03_pdf_true_no_lp(tmp_path, lp, capsys):
    e, code, job, pdfs = _pdf_run(tmp_path, "a", True, lp, capsys)
    assert lp.calls() == []
    assert {s["status"] for s in job["sheets"]} == {"created"}
    e2, _, job2, pdfs2 = _pdf_run(tmp_path, "b", False, lp, capsys)
    assert [c["status"] for c in job["cards"]] == [c["status"] for c in job2["cards"]]
    assert "held" not in {c["status"] for c in job["cards"]}


def test_N04_pdf_false_same_as_true(tmp_path, lp, capsys):
    ea, _, ja, pa = _pdf_run(tmp_path, "a", True, lp, capsys)
    eb, _, jb, pb = _pdf_run(tmp_path, "b", False, lp, capsys)
    assert [s["status"] for s in ja["sheets"]] == [s["status"] for s in jb["sheets"]]
    assert [c["status"] for c in ja["cards"]] == [c["status"] for c in jb["cards"]]
    assert pa == pb
    assert eb.c.get("/api/sheets", params={"status": "held"}).json() == []


def test_N05_fill_true_sends(mk, lp):
    e = mk(over(auto=True, timing="fill"))
    e.drop_scan(3)
    out = e.ingest()
    assert out[0]["status"] == "ok"
    job = e.job(out[0]["job_id"])
    assert [s["status"] for s in job["sheets"]] == ["sent"] and len(lp.calls()) == 1
    assert Counter(c["status"] for c in job["cards"]) == Counter({"printed": 2, "pending": 1})
    pend = next(c for c in job["cards"] if c["status"] == "pending")
    assert e.q("SELECT COUNT(*) AS n FROM sheet_cards WHERE card_id=?", pend["id"])[0]["n"] == 0


def test_N06_fill_false_holds_remainder(mk, lp):
    e = mk(over(auto=False, timing="fill"))
    e.drop_scan(3)
    out = e.ingest()
    job = e.job(out[0]["job_id"])
    assert [s["status"] for s in job["sheets"]] == ["held"] and lp.calls() == []
    assert Counter(c["status"] for c in job["cards"]) == Counter({"held": 2, "pending": 1})
    e.drop_scan(1)
    e.ingest()
    held = e.held()
    assert len(held) == 2
    assert held[1]["job_id"] is None and held[1]["card_count"] == 2
    assert lp.calls() == []


def test_N07_duplicate_true_sends(mk, lp, capsys):
    e = mk(over(cps=4, auto=True, timing="duplicate"))
    e.drop_scan(2)
    code, out = e.cli_ingest(capsys)
    jid = out[0]["job_id"]
    job = e.job(jid)
    assert e.sheets_cards(jid) == [[1, 2, 1, 2]]
    assert [s["status"] for s in job["sheets"]] == ["sent"] and len(lp.calls()) == 1
    assert [c["status"] for c in job["cards"]] == ["printed"] * 2


def test_N08_duplicate_false_holds(mk, lp, capsys):
    e = mk(over(cps=4, auto=False, timing="duplicate"))
    e.drop_scan(2)
    code, out = e.cli_ingest(capsys)
    jid = out[0]["job_id"]
    job = e.job(jid)
    assert [s["status"] for s in job["sheets"]] == ["held"] and lp.calls() == []
    assert e.sheets_cards(jid) == [[1, 2, 1, 2]]
    assert [c["status"] for c in job["cards"]] == ["held"] * 2


def test_N09_pdf_fill_false(mk, lp, capsys):
    e = mk(over(output="pdf", auto=False, timing="fill"))
    e.drop_scan(3)
    code, out = e.cli_ingest(capsys)
    job = e.job(out[0]["job_id"])
    assert [s["status"] for s in job["sheets"]] == ["created"]
    assert [c["status"] for c in job["cards"]].count("pending") == 1
    assert e.held() == []


def test_N10_pdf_duplicate_false(mk, lp, capsys):
    e = mk(over(output="pdf", auto=False, timing="duplicate"))
    e.drop_scan(2)
    code, out = e.cli_ingest(capsys)
    job = e.job(out[0]["job_id"])
    assert [s["status"] for s in job["sheets"]] == ["created"]
    assert e.held() == []


def test_N11_review_not_in_held(mk, lp, capsys):
    e = mk(over(auto=False))
    e.drop_scan(kinds=["ok", "ok", "review"])
    code, out = e.cli_ingest(capsys)
    jid = out[0]["job_id"]
    held = e.held()
    assert len(held) == 1 and held[0]["card_count"] == 2
    job = e.job(jid)
    rv = [c for c in job["cards"] if c["status"] == "review"]
    assert len(rv) == 1
    assert e.q("SELECT COUNT(*) AS n FROM sheet_cards WHERE card_id=?", rv[0]["id"])[0]["n"] == 0
    assert job["status"] == "review" and lp.calls() == []


def _review_only(e):
    e.drop_scan(kinds=["review"])
    jid = e.ingest()[0]["job_id"]
    return jid, e.job(jid)["cards"][0]["id"]


def test_N12_approve_holds(mk, lp):
    e = mk(over(auto=False))
    jid, cid = _review_only(e)
    r = e.c.post(f"/api/cards/{cid}/approve")
    assert r.status_code == 200, r.text
    held = e.held()
    assert len(held) == 1
    assert next(c for c in e.job(jid)["cards"] if c["id"] == cid)["status"] == "held"
    assert lp.calls() == []


def test_N13_approve_fill_below_capacity(mk, lp):
    e = mk(over(auto=False, timing="fill"))
    jid, cid = _review_only(e)
    r = e.c.post(f"/api/cards/{cid}/approve")
    assert r.status_code == 200, r.text
    assert e.n_sheets() == 0
    assert next(c for c in e.job(jid)["cards"] if c["id"] == cid)["status"] == "pending"


def test_N14_approve_auto_true_sends(mk, lp):
    e = mk(over(auto=True))
    jid, cid = _review_only(e)
    r = e.c.post(f"/api/cards/{cid}/approve")
    assert r.status_code == 200, r.text
    job = e.job(jid)
    assert [s["status"] for s in job["sheets"]] == ["sent"] and len(lp.calls()) == 1
    assert next(c for c in job["cards"] if c["id"] == cid)["status"] == "printed"


# ---------------------------------------------------------------- 一覧・print・discard
def test_N15_held_list_keys(mk, lp, capsys):
    e = mk(over(auto=False))
    e.drop_scan(3)
    code, out = e.cli_ingest(capsys)
    jid = out[0]["job_id"]
    r = e.c.get("/api/sheets", params={"status": "held"})
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2
    for row in rows:
        assert set(row) == {"id", "job_id", "status", "created_at", "card_count", "pdf_path"}
        assert row["status"] == "held" and row["job_id"] == jid
        assert not row["pdf_path"].startswith("/")
    assert [row["card_count"] for row in rows] == [2, 1]
    detail = {s["id"]: s["pdf_path"] for s in e.job(jid)["sheets"]}
    for row in rows:
        assert row["pdf_path"] == detail[row["id"]]


def test_N16_status_filter(mk, lp):
    e = mk(over())
    ids = mkstates(e, lp, ["held", "sent", "created"])
    rows = e.held()
    assert [r["id"] for r in rows] == [ids["held"]]


def test_N17_print_held(mk, lp):
    e = mk(over(auto=False))
    e.drop_scan(2)
    out = e.ingest()
    jid = out[0]["job_id"]
    sid = e.job(jid)["sheets"][0]["id"]
    r = e.print_(sid)
    assert r.status_code == 200 and r.json() == {"sheet_id": sid, "sent": True, "output": "lp"}
    calls = lp.calls()
    assert len(calls) == 1 and lp_args(calls[0])[:4] == ["-d", "Q1", "-n", "1"] and lp_args(calls[0])[-1].endswith(".pdf")
    assert e.sheet(sid)["status"] == "sent"
    assert e.sheet_card_status(sid) == ["printed", "printed"]
    assert e.job_status(jid) == "ok"


def test_N18_print_failure(mk, lp):
    e = mk(over(auto=False))
    e.drop_scan(2)
    jid = e.ingest()[0]["job_id"]
    sid = e.job(jid)["sheets"][0]["id"]
    lp.plan(1)
    r = e.print_(sid)
    assert r.status_code == 400
    b = r.json()
    assert b["detail"].startswith("送信に失敗しました: ")
    assert b["sheet_id"] == sid and b["sent"] is False and b["output"] == "lp"
    assert e.sheet(sid)["status"] == "error" and e.job_status(jid) == "error"
    assert e.sheet_card_status(sid) == ["held", "held"]


def test_N19_discard(mk, lp):
    e = mk(over(auto=False))
    e.drop_scan(2)
    jid = e.ingest()[0]["job_id"]
    s = e.job(jid)["sheets"][0]
    r = e.discard(s["id"])
    assert r.status_code == 200 and r.json() == {"sheet_id": s["id"], "status": "discarded"}
    assert e.sheet(s["id"])["status"] == "discarded"
    assert e.sheet_card_status(s["id"]) == ["discarded", "discarded"]
    assert e.abspdf(s["pdf_path"]).exists()
    assert lp.calls() == []
    assert s["id"] not in [h["id"] for h in e.held()]


def test_N20_reprint_excludes_held(mk, lp):
    e = mk(over(auto=False))
    e.drop_scan(2)
    jid = e.ingest()[0]["job_id"]
    sid = e.job(jid)["sheets"][0]["id"]
    r = e.c.post(f"/api/jobs/{jid}/reprint")
    assert r.status_code == 200
    assert lp.calls() == [] and e.sheet(sid)["status"] == "held"


def test_N21_reprint_excludes_discarded(mk, lp):
    e = mk(over(cps=None, auto=False))
    e.drop_scan(11)
    jid = e.ingest()[0]["job_id"]
    s1, s2 = (s["id"] for s in e.job(jid)["sheets"])
    assert e.discard(s2).status_code == 200
    assert e.print_(s1).status_code == 200
    lp.clear()
    r = e.c.post(f"/api/jobs/{jid}/reprint")
    assert r.status_code == 200
    assert len(lp.calls()) == 1
    assert e.sheet(s2)["status"] == "discarded" and e.sheet(s1)["status"] == "sent"


def test_N22_auto_print_flip_does_not_send(mk, lp):
    e = mk(over(auto=False))
    sid = one_sheet(e)
    e.put(print={"auto_print": True})
    assert lp.calls() == [] and e.sheet(sid)["status"] == "held"


def test_N23_new_scan_after_flip_sends(mk, lp, capsys):
    e = mk(over(auto=False))
    old = one_sheet(e)
    e.put(print={"auto_print": True})
    e.drop_scan(1)
    code, out = e.cli_ingest(capsys)
    new = e.job(out[0]["job_id"])["sheets"][0]
    assert new["status"] == "sent" and len(lp.calls()) == 1
    assert e.sheet(old)["status"] == "held"


def test_N24_image_png_held(mk, lp):
    e = mk(over(auto=False, ), )
    sid = one_sheet(e)
    im = png_of(e, sid)
    im.load()
    assert in_tol(im)


def test_N25_image_png_all_status(mk, lp):
    e = mk(over())
    ids = mkstates(e, lp, ["created", "held", "sent", "discarded", "error"])
    assert len(ids) == 5
    for k, sid in ids.items():
        im = png_of(e, sid)
        im.load()
        assert in_tol(im), k


def test_N26_mark_pixels(mk, lp):
    e = mk(over(auto=False, mark_gray=0) if False else over(auto=False))
    e.put(layout={"mark_enabled": True, "mark_gray": 0, "mark_width_mm": 0.1})
    sid = one_sheet(e)
    spath = e.abspdf(e.c.get("/api/sheets", params={"status": "held"}).json()[0]["pdf_path"])
    marks = json.loads(spath.with_suffix(".layout.json").read_text())["marks"]
    assert marks
    im = png_of(e, sid).convert("L")
    im.load()
    px = im.load()
    W, H = im.size
    k = 300 / 25.4
    checked = 0
    for m in marks:
        x1, y1, x2, y2 = (m["x1"] * k, m["y1"] * k, m["x2"] * k, m["y2"] * k)
        L = max(abs(x2 - x1), abs(y2 - y1))
        if L < 2:
            continue
        checked += 1
        n = int(L) + 1
        best = 255
        for i in range(n + 1):
            x = x1 + (x2 - x1) * i / n
            y = y1 + (y2 - y1) * i / n
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    xi, yi = int(round(x)) + dx, int(round(y)) + dy
                    if 0 <= xi < W and 0 <= yi < H:
                        best = min(best, px[xi, yi])
        assert best < 200, m
    assert checked > 0
    # 背景: 用紙の隅（マーク・カードから離れた余白）
    assert all(px[x, y] == 255 for x in range(30) for y in range(30))


def test_N27_print_uses_current_output(mk, lp):
    e = mk(over(auto=False))
    sid = one_sheet(e)
    e.put(print={"output": "pdf"})
    r = e.print_(sid)
    assert r.status_code == 200 and r.json() == {"sheet_id": sid, "sent": False, "output": "pdf"}
    assert e.sheet(sid)["status"] == "held" and lp.calls() == []
    assert e.sheet_card_status(sid) == ["held"]


def test_N28_held_job_ok(mk, lp):
    e = mk(over(auto=False))
    e.drop_scan(3)
    out = e.ingest()
    assert out[0]["status"] == "ok" and e.job_status(out[0]["job_id"]) == "ok"


def test_N29_held_cards_not_reimposed(mk, lp):
    """N-29 改: cps=2。1回目 ok3枚→シート2件(2・1)が held、2回目 ok2枚→シート1件(b1,b2)。"""
    e = mk(over(cps=2, auto=False))
    e.drop_scan(3)
    j1 = e.ingest()[0]["job_id"]
    assert e.n_sheets(j1) == 2
    e.drop_scan(2)
    j2 = e.ingest()[0]["job_id"]
    c1 = [c["id"] for c in e.job(j1)["cards"]]
    c2 = {c["id"] for c in e.job(j2)["cards"]}
    assert len(c1) == 3 and len(c2) == 2
    for cid in c1:
        assert e.q("SELECT COUNT(DISTINCT sheet_id) AS n FROM sheet_cards WHERE card_id=?", cid)[0]["n"] == 1
    s2 = e.job(j2)["sheets"]
    assert len(s2) == 1
    on = {r["card_id"] for r in e.q("SELECT card_id FROM sheet_cards WHERE sheet_id=?", s2[0]["id"])}
    assert on == c2
    h = e.held()
    assert len(h) == 3 and sorted(x["card_count"] for x in h) == [1, 2, 2]
    assert e.q("SELECT COUNT(*) AS n FROM cards WHERE status='held'")[0]["n"] == 5
    assert lp.calls() == []


def test_N30_fill_leftover_not_back_to_pending(mk, lp):
    e = mk(over(auto=False, timing="fill"))
    e.drop_scan(2)
    j1 = e.ingest()[0]["job_id"]
    assert len(e.held()) == 1
    e.drop_scan(1)
    j2 = e.ingest()[0]["job_id"]
    assert e.n_sheets() == 1 and len(e.held()) == 1
    assert [c["status"] for c in e.job(j2)["cards"]] == ["pending"]
    for c in e.job(j1)["cards"]:
        assert e.q("SELECT COUNT(DISTINCT sheet_id) AS n FROM sheet_cards WHERE card_id=?", c["id"])[0]["n"] == 1


def _schema_type(schema, sec, key):
    def deref(n):
        if "$ref" in n:
            return deref(schema["$defs"][n["$ref"].split("/")[-1]])
        if "allOf" in n and len(n["allOf"]) == 1:
            return deref(n["allOf"][0])
        return n

    return deref(deref(schema["properties"][sec])["properties"][key])["type"]


def test_N31_default_and_schema(tmp_path, capsys):
    home = Home(tmp_path / "fresh")
    home.ensure(Settings())
    c = TestClient(create_app(home))
    assert c.get("/api/config").json()["print"]["auto_print"] is True
    assert _schema_type(c.get("/api/config/schema").json(), "print", "auto_print") == "boolean"
    capsys.readouterr()
    assert main(["config", "schema", "--home", str(tmp_path / "fresh")]) == 0
    assert _schema_type(json.loads(capsys.readouterr().out), "print", "auto_print") == "boolean"


def test_N39_api_ingest_holds(mk, lp):
    """N-39 改: 応答の cards=3・sheets=2（整数）。DB の held 2件。"""
    e = mk(over(auto=False))
    e.drop_scan(3)
    r = e.c.post("/api/ingest")
    assert r.status_code == 200, r.text
    out = r.json()
    assert len(out) == 1 and out[0]["cards"] == 3 and out[0]["sheets"] == 2
    assert type(out[0]["cards"]) is int and type(out[0]["sheets"]) is int
    assert [x["status"] for x in e.q("SELECT status FROM sheets ORDER BY id")] == ["held", "held"]
    assert lp.calls() == []


def test_N43_list_without_status(mk, lp):
    e = mk(over())
    mkstates(e, lp, ["held", "sent", "created", "discarded"])
    r = e.c.get("/api/sheets")
    assert r.status_code == 200
    assert len(r.json()) == 4 and {s["status"] for s in r.json()} == {"held", "sent", "created", "discarded"}


def _set_times(e, mapping):
    rows = e.q("SELECT id, created_at FROM sheets ORDER BY id")
    base = rows[0]["created_at"]
    assert base[:4].isdigit()
    for sid, k in mapping.items():
        e.x("UPDATE sheets SET created_at=? WHERE id=?", f"{2020 + k}{base[4:]}", sid)


def test_N44_order(mk, lp):
    """N-44 改: シート4件。created_at は id1:T3, id2:T2, id3:T1, id4:T2 → [3, 2, 4, 1]。"""
    e = mk(over(auto=False))
    e.drop_scan(8)
    e.ingest()
    ids = [r["id"] for r in e.q("SELECT id FROM sheets ORDER BY id")]
    assert len(ids) == 4
    _set_times(e, {ids[0]: 3, ids[1]: 2, ids[2]: 1, ids[3]: 2})
    r = e.c.get("/api/sheets")
    assert r.status_code == 200
    assert len(r.json()) == 4
    assert [s["id"] for s in r.json()] == [ids[2], ids[1], ids[3], ids[0]]


def test_N45_mixed_job_id_null(mk, lp):
    """N-45 改: fill, cps=2。A(ok1)→B(ok1)→C(ok2)。A+B 混在シートは job_id=null、C のみのシートは C。"""
    e = mk(over(auto=False, timing="fill"))
    e.drop_scan(1)
    ja = e.ingest()[0]["job_id"]
    assert e.q("SELECT COUNT(*) AS n FROM sheets")[0]["n"] == 0
    assert [c["status"] for c in e.job(ja)["cards"]] == ["pending"]
    e.drop_scan(1)
    e.ingest()
    e.drop_scan(2)
    jc = e.ingest()[0]["job_id"]
    rows = e.c.get("/api/sheets").json()
    assert len(rows) == 2 and all(r["card_count"] == 2 for r in rows)
    ids = sorted(str(r["job_id"]) for r in rows)
    assert ids == sorted([str(None), str(jc)])


def test_N46_mixed_discard(mk, lp):
    e = mk(over(auto=False, timing="fill"))
    ja, jb, sid = mixed_fill(e, a_kinds=["ok", "review"])
    r = e.discard(sid)
    assert r.status_code == 200 and r.json() == {"sheet_id": sid, "status": "discarded"}
    assert e.sheet_card_status(sid) == ["discarded", "discarded"]
    assert e.job_status(ja) == "review" and e.job_status(jb) == "ok"


@pytest.mark.parametrize("timing", ["per_scan", "fill", "duplicate"])
def test_N47_empty_printer_still_holds(mk, lp, capsys, timing):
    e = mk(over(auto=False, timing=timing, printer=""))
    e.drop_scan(2)
    code, out = e.cli_ingest(capsys)
    assert code == 0 and len(e.held()) >= 1 and lp.calls() == []
    assert out[0]["status"] == "ok" and e.job_status(out[0]["job_id"]) == "ok"


def test_N48_approve_delivery_held(mk, lp):
    e = mk(over(auto=False))
    jid, cid = _review_only(e)
    r = e.c.post(f"/api/cards/{cid}/approve")
    assert r.status_code == 200 and r.json()["delivery"] == {"ok": True, "error": None}


def test_N49_reprint_zero_targets(mk, lp):
    e = mk(over(cps=None, auto=False))
    e.drop_scan(11)
    jid = e.ingest()[0]["job_id"]
    s1, s2 = (s["id"] for s in e.job(jid)["sheets"])
    assert e.discard(s2).status_code == 200
    r = e.c.post(f"/api/jobs/{jid}/reprint")
    assert r.status_code == 200 and r.json() == {"sheets": [], "output": "lp"}
    assert lp.calls() == []


def test_N51_auto_print_string_true(mk):
    e = mk(over(auto=False))
    cfg = e.c.get("/api/config").json()
    cfg["print"]["auto_print"] = "true"
    cfg["layout"]["mark_enabled"] = "true"
    r = e.c.put("/api/config", json=cfg)
    assert r.status_code == 200, r.text
    got = e.c.get("/api/config").json()
    assert got["print"]["auto_print"] is True and got["layout"]["mark_enabled"] is True


def test_N52_reprint_after_failure(mk, lp):
    e = mk(over(auto=False))
    e.drop_scan(2)
    jid = e.ingest()[0]["job_id"]
    sid = e.job(jid)["sheets"][0]["id"]
    lp.plan(1)
    assert e.print_(sid).status_code == 400
    lp.plan(0)
    lp.clear()
    r = e.c.post(f"/api/jobs/{jid}/reprint")
    assert r.status_code == 200, r.text
    assert len(lp.calls()) == 1
    assert e.sheet(sid)["status"] == "sent"
    assert e.sheet_card_status(sid) == ["printed", "printed"]
    assert e.job_status(jid) == "ok"


def test_N53_all_discarded_job_ok(mk, lp):
    e = mk(over(auto=False))
    e.drop_scan(2)
    jid = e.ingest()[0]["job_id"]
    sid = e.job(jid)["sheets"][0]["id"]
    assert e.discard(sid).status_code == 200
    job = e.job(jid)
    assert job["status"] == "ok" and {c["status"] for c in job["cards"]} == {"discarded"}


def test_N54_fetch_pdf_by_pdf_path(mk, lp):
    e = mk(over(auto=False))
    one_sheet(e)
    row = e.held()[0]
    r = e.c.get(f"/files/{row['pdf_path']}")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    doc = pdfium.PdfDocument(r.content)
    w, h = doc[0].get_size()
    doc.close()
    assert abs(w * MM - 210) <= 0.1 and abs(h * MM - 297) <= 0.1


def test_N55_reprint_after_mixed_failure(mk, lp):
    e = mk(over(auto=False, timing="fill"))
    ja, jb, sid = mixed_fill(e)
    lp.plan(1)
    assert e.print_(sid).status_code == 400
    lp.plan(0)
    lp.clear()
    r = e.c.post(f"/api/jobs/{ja}/reprint")
    assert r.status_code == 200, r.text
    assert len(lp.calls()) == 1
    assert e.sheet(sid)["status"] == "sent"
    assert e.sheet_card_status(sid) == ["printed", "printed"]
    assert e.job_status(ja) == "ok" and e.job_status(jb) == "ok"


# ================================================================ 異常系
def test_E01_double_print(mk, lp):
    e = mk(over(auto=False))
    sid = one_sheet(e)
    assert e.print_(sid).status_code == 200
    r = e.print_(sid)
    assert r.status_code == 409 and r.json() == {"detail": DETAIL409}
    assert len(lp.calls()) == 1


def test_E02_print_sent(mk, lp):
    e = mk(over())
    sid = mkstates(e, lp, ["sent"])["sent"]
    s0 = e.snap()
    r = e.print_(sid)
    assert r.status_code == 409 and r.json()["detail"] == DETAIL409
    assert lp.calls() == [] and e.snap() == s0


def test_E03_print_created_error_discarded(mk, lp):
    e = mk(over())
    ids = mkstates(e, lp, ["created", "error", "discarded"])
    s0 = e.snap()
    for k, sid in ids.items():
        r = e.print_(sid)
        assert r.status_code == 409 and r.json()["detail"] == DETAIL409, k
    assert lp.calls() == [] and e.snap() == s0


def test_E04_print_missing(mk, lp):
    e = mk(over())
    r = e.print_(99999)
    assert r.status_code == 404 and r.json() == {"detail": "sheet not found"}


def test_E05_discard_missing(mk, lp):
    e = mk(over())
    r = e.discard(99999)
    assert r.status_code == 404 and r.json() == {"detail": "sheet not found"}


def test_E06_discard_non_held(mk, lp):
    e = mk(over())
    ids = mkstates(e, lp, ["sent", "created", "error", "discarded"])
    s0 = e.snap()
    for k, sid in ids.items():
        r = e.discard(sid)
        assert r.status_code == 409 and r.json()["detail"] == DETAIL409, k
    assert e.snap() == s0


def test_E07_double_discard(mk, lp):
    e = mk(over(auto=False))
    sid = one_sheet(e)
    assert e.discard(sid).status_code == 200
    r = e.discard(sid)
    assert r.status_code == 409 and r.json()["detail"] == DETAIL409


def test_E08_print_discarded(mk, lp):
    e = mk(over(auto=False))
    sid = one_sheet(e)
    e.discard(sid)
    r = e.print_(sid)
    assert r.status_code == 409 and r.json()["detail"] == DETAIL409 and lp.calls() == []


def test_E09_image_missing(mk):
    e = mk(over())
    assert e.c.get("/api/sheets/99999/image.png").status_code == 404


def test_E10_print_empty_printer(mk, lp):
    e = mk(over(auto=False, printer=""))
    e.drop_scan(2)
    jid = e.ingest()[0]["job_id"]
    sid = e.job(jid)["sheets"][0]["id"]
    r = e.print_(sid)
    assert r.status_code == 400
    b = r.json()
    assert b["detail"].startswith("送信に失敗しました: ") and b["sent"] is False and b["output"] == "lp"
    assert lp.calls() == []
    assert e.sheet(sid)["status"] == "error" and e.job_status(jid) == "error"


def test_E11_auto_print_invalid(mk):
    e = mk(over(auto=False))
    before = e.c.get("/api/config").json()
    cfg = json.loads(json.dumps(before))
    cfg["print"]["auto_print"] = "abc"
    assert e.c.put("/api/config", json=cfg).status_code == 422
    assert e.c.get("/api/config").json() == before


def test_E12_unknown_status(mk):
    e = mk(over())
    assert e.c.get("/api/sheets", params={"status": "foo"}).status_code == 422


def test_E13_mixed_print_failure(mk, lp):
    e = mk(over(auto=False, timing="fill"))
    ja, jb, sid = mixed_fill(e)
    lp.plan(1)
    r = e.print_(sid)
    assert r.status_code == 400 and r.json()["detail"].startswith("送信に失敗しました: ")
    assert e.sheet(sid)["status"] == "error"
    assert e.job_status(ja) == "error" and e.job_status(jb) == "error"
    assert e.sheet_card_status(sid) == ["held", "held"]


def test_E14_held_creation_never_fails_on_lp(mk, lp, capsys):
    e = mk(over(auto=False))
    lp.plan(*([1] * 20))
    e.drop_scan(3)
    code, out = e.cli_ingest(capsys)
    assert code == 0 and lp.calls() == []
    assert out[0]["status"] == "ok"
    assert [s["status"] for s in e.job(out[0]["job_id"])["sheets"]] == ["held", "held"]


def test_E15_empty_status_is_all(mk, lp):
    e = mk(over())
    mkstates(e, lp, ["held", "sent"])
    r = e.c.get("/api/sheets", params={"status": ""})
    assert r.status_code == 200 and len(r.json()) == 2


# ================================================================ 境界値
def test_B01_no_held(mk):
    e = mk(over())
    r = e.c.get("/api/sheets", params={"status": "held"})
    assert r.status_code == 200 and r.json() == []


def test_B02_one_held(mk):
    e = mk(over(auto=False))
    one_sheet(e)
    assert len(e.held()) == 1


def test_B03_single_card_held(mk, lp, capsys):
    e = mk(over(auto=False))
    e.drop_scan(1)
    e.cli_ingest(capsys)
    h = e.held()
    assert len(h) == 1 and h[0]["card_count"] == 1


def test_B04_exact_capacity(mk, lp, capsys):
    e = mk(over(cps=None, auto=False))
    e.drop_scan(10)
    e.cli_ingest(capsys)
    h = e.held()
    assert len(h) == 1 and h[0]["card_count"] == 10


def test_B05_over_capacity(mk, lp):
    e = mk(over(cps=None, auto=False))
    e.drop_scan(11)
    e.ingest()
    h = e.held()
    assert [x["card_count"] for x in h] == [10, 1] and lp.calls() == []
    for x in h:
        assert e.print_(x["id"]).status_code == 200
    assert len(lp.calls()) == 2


def test_B06_fill_exact(mk, lp):
    e = mk(over(auto=False, timing="fill"))
    e.drop_scan(2)
    jid = e.ingest()[0]["job_id"]
    assert len(e.held()) == 1
    assert "pending" not in [c["status"] for c in e.job(jid)["cards"]]


def test_B07_fill_one_short(mk, lp):
    e = mk(over(auto=False, timing="fill"))
    e.drop_scan(1)
    jid = e.ingest()[0]["job_id"]
    assert e.n_sheets() == 0
    assert [c["status"] for c in e.job(jid)["cards"]] == ["pending"]


def test_B08_duplicate_zero_ok(mk, lp):
    e = mk(over(auto=False, timing="duplicate"))
    e.drop_scan(kinds=["review", "review"])
    out = e.ingest()
    assert e.n_sheets() == 0 and e.held() == [] and out[0]["status"] == "review"
    assert e.job_status(out[0]["job_id"]) == "review"


def test_B09_print_all_held(mk, lp):
    e = mk(over(auto=False))
    e.drop_scan(6)
    e.ingest()
    h = e.held()
    assert len(h) == 3
    for x in h:
        assert e.print_(x["id"]).status_code == 200
    assert len(lp.calls()) == 3
    assert {e.sheet(x["id"])["status"] for x in h} == {"sent"}


def test_B10_copies_two(mk, lp):
    e = mk(over(auto=False, copies=2))
    sid = one_sheet(e)
    assert e.print_(sid).status_code == 200
    a = lp_args(lp.calls()[0])
    assert "-n" in a and a[a.index("-n") + 1] == "2"


def test_B11_discard_one_print_one(mk, lp):
    e = mk(over(auto=False))
    e.drop_scan(4)
    e.ingest()
    s1, s2 = (x["id"] for x in e.held())
    assert e.discard(s1).status_code == 200 and e.print_(s2).status_code == 200
    assert e.sheet(s1)["status"] == "discarded" and e.sheet(s2)["status"] == "sent"
    assert set(e.sheet_card_status(s1)) == {"discarded"} and set(e.sheet_card_status(s2)) == {"printed"}
    assert e.held() == []


def test_B12_same_time_order(mk, lp):
    e = mk(over(auto=False))
    e.drop_scan(6)
    e.ingest()
    ids = [r["id"] for r in e.q("SELECT id FROM sheets ORDER BY id")]
    assert len(ids) == 3
    _set_times(e, {i: 4 for i in ids})
    assert [x["id"] for x in e.held()] == ids


def test_B13_dimension_tolerance(mk):
    e = mk(over(auto=False))
    sid = one_sheet(e)
    im = png_of(e, sid)
    assert 2479 <= im.size[0] <= 2481 and 3507 <= im.size[1] <= 3509


# ================================================================ 追補（2026-11-12 細則追記 3 行）
import threading
import time
from contextlib import contextmanager


@pytest.fixture
def block_lp(tmp_path, lp):
    """偽 lp を差し替え: 呼ばれたら記録し、release ファイルができるまで戻らない（終了コード 0）。"""
    log = tmp_path / "lp.log"
    release = tmp_path / "lp.release"
    script = tmp_path / "fakebin" / "lp"
    script.write_text(
        '#!/bin/sh\n'
        f'echo "$@" >> "{log}"\n'
        f'while [ ! -f "{release}" ]; do sleep 0.05; done\n'
        'exit 0\n'
    )
    script.chmod(0o755)

    class B:
        def release(self):
            release.write_text("1")

    return B()


def _wait_calls(lp, n, timeout=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if len(lp.calls()) >= n:
            return True
        time.sleep(0.05)
    return False


def _bg(fn):
    box = {}

    def run():
        box["r"] = fn()

    t = threading.Thread(target=run)
    t.start()
    return t, box


@contextmanager
def api_started(e):
    """API サーバを起動（lifespan 込み）して、そのクライアントを返す。"""
    with TestClient(create_app(e.home)) as c:
        yield c


def held2(e):
    """held シート1件（カード2枚）を作り (job_id, sheet_id, [card_id 昇順]) を返す。"""
    e.drop_scan(2)
    jid = e.ingest()[0]["job_id"]
    sid = e.job(jid)["sheets"][0]["id"]
    cards = sorted(c["id"] for c in e.job(jid)["cards"])
    assert len(cards) == 2
    return jid, sid, cards


def test_N58_cli_counts_are_int(mk, lp, capsys):
    """N-58: CLI の cards・sheets は整数（cards=3, sheets=2）。"""
    e = mk(over(auto=True))
    e.drop_scan(3)
    code, out = e.cli_ingest(capsys)
    assert code == 0 and len(out) == 1
    for k, v in (("cards", 3), ("sheets", 2)):
        assert type(out[0][k]) is int and out[0][k] == v


def test_N59_api_counts_are_int(mk, lp):
    """N-59: POST /api/ingest の cards=3・sheets=2（整数）。"""
    e = mk(over(auto=False))
    e.drop_scan(3)
    r = e.c.post("/api/ingest")
    assert r.status_code == 200
    o = r.json()[0]
    assert type(o["cards"]) is int and o["cards"] == 3
    assert type(o["sheets"]) is int and o["sheets"] == 2


def test_N60_zero_sheets_is_int_zero(mk, lp):
    """N-60: fill・ok1枚 → sheets=0（整数の 0）、cards は整数。"""
    e = mk(over(auto=False, timing="fill"))
    e.drop_scan(1)
    r = e.c.post("/api/ingest")
    assert r.status_code == 200
    o = r.json()[0]
    assert type(o["sheets"]) is int and o["sheets"] == 0
    assert type(o["cards"]) is int


def test_N61_status_sending_is_422(mk, lp):
    """N-61: ?status=sending は ?status=foo と同じ 422。シート status は変化しない。"""
    e = mk(over(auto=False))
    one_sheet(e)
    s0 = e.snap()
    r_foo = e.c.get("/api/sheets", params={"status": "foo"})
    r = e.c.get("/api/sheets", params={"status": "sending"})
    assert r_foo.status_code == 422 and r.status_code == 422
    assert e.snap() == s0


def test_N62_double_print_while_sending(mk, lp, block_lp):
    """N-62: print 実行中（lp ブロック中）の二重 print は 409。lp は1回。解放後 1回目は 200。"""
    e = mk(over(auto=False))
    sid = one_sheet(e)
    t, box = _bg(lambda: e.print_(sid))
    try:
        assert _wait_calls(lp, 1)
        r2 = e.print_(sid)
        assert r2.status_code == 409 and r2.json() == {"detail": DETAIL409}
        assert len(lp.calls()) == 1
    finally:
        block_lp.release()
        t.join(30)
    r1 = box["r"]
    assert r1.status_code == 200 and r1.json() == {"sheet_id": sid, "sent": True, "output": "lp"}
    assert e.sheet(sid)["status"] == "sent"


def test_N63_reprint_skips_sending(mk, lp, block_lp):
    """N-63: sending 中のシートのみのジョブの reprint は sheets=[]・lp 増えない。解放後 sent。"""
    e = mk(over(auto=False))
    jid, sid, _ = held2(e)
    t, box = _bg(lambda: e.print_(sid))
    try:
        assert _wait_calls(lp, 1)
        r = e.c.post(f"/api/jobs/{jid}/reprint")
        assert r.status_code == 200 and r.json() == {"sheets": [], "output": "lp"}
        assert len(lp.calls()) == 1
    finally:
        block_lp.release()
        t.join(30)
    assert e.sheet(sid)["status"] == "sent"


def test_N64_discard_while_sending(mk, lp, block_lp):
    """N-64: 送信中の discard は 409。カードは held のまま。解放後 sent・printed。"""
    e = mk(over(auto=False))
    jid, sid, _ = held2(e)
    t, box = _bg(lambda: e.print_(sid))
    try:
        assert _wait_calls(lp, 1)
        r = e.discard(sid)
        assert r.status_code == 409 and r.json() == {"detail": DETAIL409}
        assert e.sheet_card_status(sid) == ["held", "held"]
    finally:
        block_lp.release()
        t.join(30)
    assert e.sheet(sid)["status"] == "sent"
    assert e.sheet_card_status(sid) == ["printed", "printed"]


def _make_sending(e, jid_sheet_ids):
    for sid in jid_sheet_ids:
        e.x("UPDATE sheets SET status='sending' WHERE id=?", sid)


def test_N65_api_start_reverts_sending(mk, lp):
    """N-65: DB に sending 1件（カード2枚 held）→ API 起動で held に戻る。held 一覧1件、カード held、lp 0回。
    前提の sending は DB 直接書き換えで作る（外部 IF から作れない）。"""
    e = mk(over(auto=False))
    jid, sid, _ = held2(e)
    _make_sending(e, [sid])
    assert e.sheet(sid)["status"] == "sending"
    with api_started(e) as c:
        r = c.get("/api/sheets", params={"status": "held"})
        assert r.status_code == 200 and len(r.json()) == 1
    assert e.sheet(sid)["status"] == "held"
    assert e.sheet_card_status(sid) == ["held", "held"]
    assert lp.calls() == []


def test_N66_cli_does_not_revert_sending(mk, lp, capsys):
    """N-66: CLI ingest（対象ファイル無し）は sending を戻さない。終了コード 0・lp 0回。"""
    e = mk(over(auto=False))
    jid, sid, _ = held2(e)
    _make_sending(e, [sid])
    capsys.readouterr()
    code = main(["ingest", "--home", str(e.home.root)])
    capsys.readouterr()
    assert code == 0
    assert e.sheet(sid)["status"] == "sending"
    assert lp.calls() == []


def test_N67_single_card_discard(mk, lp):
    """N-67: held シートのカード c1 を単体破棄。c1 discarded・c2 held・シート held・PDF 不変。"""
    e = mk(over(auto=False))
    jid, sid, (c1, c2) = held2(e)
    pdf0 = e.sheet(sid)["pdf_path"]
    r = e.c.post(f"/api/cards/{c1}/discard")
    assert r.status_code == 200, r.text
    st = {x["id"]: x["status"] for x in e.q("SELECT id, status FROM cards")}
    assert st[c1] == "discarded" and st[c2] == "held"
    assert e.sheet(sid)["status"] == "held"
    assert e.sheet(sid)["pdf_path"] == pdf0 and e.abspdf(pdf0).exists()
    assert lp.calls() == []


def test_N68_print_after_card_discard(mk, lp):
    """N-68: N-67 の後に print 成功。c2 printed・c1 discarded のまま。"""
    e = mk(over(auto=False))
    jid, sid, (c1, c2) = held2(e)
    assert e.c.post(f"/api/cards/{c1}/discard").status_code == 200
    r = e.print_(sid)
    assert r.status_code == 200 and r.json() == {"sheet_id": sid, "sent": True, "output": "lp"}
    assert len(lp.calls()) == 1 and e.sheet(sid)["status"] == "sent"
    st = {x["id"]: x["status"] for x in e.q("SELECT id, status FROM cards")}
    assert st[c2] == "printed" and st[c1] == "discarded"


def test_N69_reprint_after_card_discard(mk, lp):
    """N-69: N-67 の後に print を lp 失敗で error → lp 成功へ差し替えて reprint。c2 printed・c1 discarded のまま。"""
    e = mk(over(auto=False))
    jid, sid, (c1, c2) = held2(e)
    assert e.c.post(f"/api/cards/{c1}/discard").status_code == 200
    lp.plan(1)
    assert e.print_(sid).status_code == 400
    assert e.sheet(sid)["status"] == "error"
    st = {x["id"]: x["status"] for x in e.q("SELECT id, status FROM cards")}
    assert st[c1] == "discarded" and st[c2] == "held"
    lp.plan(0)
    lp.clear()
    r = e.c.post(f"/api/jobs/{jid}/reprint")
    assert r.status_code == 200, r.text
    assert len(lp.calls()) == 1 and e.sheet(sid)["status"] == "sent"
    st = {x["id"]: x["status"] for x in e.q("SELECT id, status FROM cards")}
    assert st[c2] == "printed" and st[c1] == "discarded"


def test_N70_sheet_discard_after_card_discard(mk, lp):
    """N-70: N-67 の後のシート破棄。c1・c2 とも discarded。PDF は存在。"""
    e = mk(over(auto=False))
    jid, sid, (c1, c2) = held2(e)
    pdf0 = e.sheet(sid)["pdf_path"]
    assert e.c.post(f"/api/cards/{c1}/discard").status_code == 200
    r = e.discard(sid)
    assert r.status_code == 200 and r.json() == {"sheet_id": sid, "status": "discarded"}
    st = {x["id"]: x["status"] for x in e.q("SELECT id, status FROM cards")}
    assert st[c1] == "discarded" and st[c2] == "discarded"
    assert e.abspdf(pdf0).exists()


def test_N71_no_sending_left(mk, lp):
    """N-71: A を print 成功、B を print 失敗 → A sent・B error。sending は 0件。"""
    e = mk(over(cps=1, auto=False))
    e.drop_scan(2)
    jid = e.ingest()[0]["job_id"]
    ids = [x["id"] for x in e.held()]
    assert len(ids) == 2
    a, b = ids
    lp.plan(0, 1)
    assert e.print_(a).status_code == 200
    assert e.print_(b).status_code == 400
    got = {x["id"]: x["status"] for x in e.c.get("/api/sheets").json()}
    assert got[a] == "sent" and got[b] == "error"
    assert e.q("SELECT COUNT(*) AS n FROM sheets WHERE status='sending'")[0]["n"] == 0


def test_E16_start_reverts_only_sending(mk, lp):
    """E-16: sent・error・created・discarded・held 各1件。sending 0件。API 起動で5件とも変化なし。"""
    e = mk(over())
    mkstates(e, lp, ["sent", "error", "created", "discarded", "held"])
    s0 = e.snap()
    assert len(s0[0]) == 5
    assert e.q("SELECT COUNT(*) AS n FROM sheets WHERE status='sending'")[0]["n"] == 0
    with api_started(e) as c:
        r = c.get("/api/sheets")
        assert r.status_code == 200 and len(r.json()) == 5
    assert e.snap() == s0


def test_B14_start_sending_zero_and_two(mk, lp, tmp_path):
    """B-14: (a) sending 0件・held 1件 → 変化なし。(b) sending 2件・held 0件 → 起動後 held 2件。"""
    e = mk(over(auto=False))
    one_sheet(e)
    with api_started(e) as c:
        r = c.get("/api/sheets", params={"status": "held"})
        assert r.status_code == 200 and len(r.json()) == 1
    assert [x["status"] for x in e.q("SELECT status FROM sheets")] == ["held"]

    e2 = Env(tmp_path / "b14b", over(auto=False))
    e2.drop_scan(4)
    e2.ingest()
    ids = [x["id"] for x in e2.q("SELECT id FROM sheets ORDER BY id")]
    assert len(ids) == 2
    _make_sending(e2, ids)
    assert e2.held() == []
    with api_started(e2) as c:
        r = c.get("/api/sheets", params={"status": "held"})
        assert r.status_code == 200 and len(r.json()) == 2
        assert {x["status"] for x in r.json()} == {"held"}


# ================================================================ 追補2（D27: ラスタライズの同時要求）
# 実 HTTP サーバを別プロセス（print-edit serve）で起動し、スレッドで実際に並行させて image.png を要求する。
# サーバが異常終了しても pytest 本体は巻き込まれず、そのテストの fail になる。
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager

_SERVE_CODE = "import sys; from print_edit.cli import main; sys.exit(main(sys.argv[1:]))"


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def real_server(e):
    port = _free_port()
    log = (e.home.root.parent / "serve.log").open("w")
    proc = subprocess.Popen(
        [sys.executable, "-c", _SERVE_CODE, "serve", "--home", str(e.home.root), "--port", str(port)],
        stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    try:
        t0 = time.time()
        while True:
            assert proc.poll() is None, f"サーバが起動時に終了: rc={proc.returncode}"
            try:
                urllib.request.urlopen(base + "/api/sheets", timeout=2).read()
                break
            except Exception:
                assert time.time() - t0 < 30, "サーバが起動しない"
                time.sleep(0.2)
        yield proc, base
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()


def _get(base, path, timeout=120):
    """(status, content-type, body) を返す。接続切れ・タイムアウトは ('EXC', repr(e), b'')。"""
    try:
        with urllib.request.urlopen(base + path, timeout=timeout) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as ex:
        return ex.code, ex.headers.get("Content-Type", ""), ex.read()
    except Exception as ex:  # noqa: BLE001
        return "EXC", repr(ex), b""


def _concurrent(base, paths):
    """全件を待たず一斉に送信（バリアで揃える）してから全応答を集める。"""
    res = [None] * len(paths)
    barrier = threading.Barrier(len(paths))

    def w(i, p):
        barrier.wait()
        res[i] = _get(base, p)

    ts = [threading.Thread(target=w, args=(i, p)) for i, p in enumerate(paths)]
    [t.start() for t in ts]
    [t.join(180) for t in ts]
    assert all(r is not None for r in res), "応答が返らないスレッドがある"
    return res


def _assert_png_a4(res, label=""):
    assert res[0] == 200, f"{label} status={res[0]} {res[1]}"
    assert res[1].split(";")[0] == "image/png", f"{label} content-type={res[1]}"
    im = Image.open(io.BytesIO(res[2]))
    im.load()
    assert abs(im.size[0] - 2480) <= 1 and abs(im.size[1] - 3508) <= 1, f"{label} size={im.size}"
    return im


def _held_env(mk, n):
    e = mk(over(cps=1, auto=False))
    e.drop_scan(n)
    e.ingest()
    ids = [x["id"] for x in e.held()]
    assert len(ids) == n
    return e, ids


def test_N72_concurrent_images_different_sheets(mk, lp):
    """N-72: held 6 件の image.png を同時要求。全 200・PNG・2480x3508(±1)・接続切れ/タイムアウト無し。"""
    e, ids = _held_env(mk, 6)
    with real_server(e) as (proc, base):
        res = _concurrent(base, [f"/api/sheets/{i}/image.png" for i in ids])
        assert proc.poll() is None, f"サーバ異常終了 rc={proc.returncode}"
        for i, r in zip(ids, res):
            _assert_png_a4(r, f"sheet {i}")


def test_N73_concurrent_images_same_sheet(mk, lp):
    """N-73: 同じ id の image.png を 6 回同時要求。全 200・PNG・サイズ OK・6 件の画素一致。"""
    e, ids = _held_env(mk, 1)
    with real_server(e) as (proc, base):
        res = _concurrent(base, [f"/api/sheets/{ids[0]}/image.png"] * 6)
        assert proc.poll() is None, f"サーバ異常終了 rc={proc.returncode}"
        ims = [_assert_png_a4(r, f"#{k}") for k, r in enumerate(res)]
        ref = ims[0].convert("RGB").tobytes()
        for k, im in enumerate(ims[1:], 1):
            assert im.size == ims[0].size and im.convert("RGB").tobytes() == ref, f"#{k} の画素が不一致"


def test_N74_server_alive_after_concurrent(mk, lp):
    """N-74: N-72 の直後に held 一覧（長さ6）と image.png 1 件が 200。シート status は 6 件とも held のまま。"""
    e, ids = _held_env(mk, 6)
    with real_server(e) as (proc, base):
        res = _concurrent(base, [f"/api/sheets/{i}/image.png" for i in ids])
        assert all(r[0] == 200 for r in res), [r[0] for r in res]
        s, _, body = _get(base, "/api/sheets?status=held")
        assert s == 200
        assert len(json.loads(body)) == 6
        _assert_png_a4(_get(base, f"/api/sheets/{ids[0]}/image.png"))
        assert proc.poll() is None, f"サーバ異常終了 rc={proc.returncode}"
    st = e.q("SELECT id, status FROM sheets ORDER BY id")
    assert len(st) == 6 and {x["status"] for x in st} == {"held"}


def test_E17_concurrent_with_missing_id(mk, lp):
    """E-17: 実在 3 件 + 99999 を同時要求。実在は 200・PNG、99999 は 404。"""
    e, ids = _held_env(mk, 3)
    with real_server(e) as (proc, base):
        paths = [f"/api/sheets/{i}/image.png" for i in ids] + ["/api/sheets/99999/image.png"]
        res = _concurrent(base, paths)
        assert proc.poll() is None, f"サーバ異常終了 rc={proc.returncode}"
        for i, r in zip(ids, res[:3]):
            _assert_png_a4(r, f"sheet {i}")
        assert res[3][0] == 404, f"99999 status={res[3][0]}"


def test_B15_concurrent_counts_1_2_6_12(mk, lp):
    """B-15: held 12 件。同時 1・2・6・12 件を 4 回に分けて送る。全 200・PNG・サイズ OK。各回の後 GET /api/sheets が 200。"""
    e, ids = _held_env(mk, 12)
    with real_server(e) as (proc, base):
        for n in (1, 2, 6, 12):
            res = _concurrent(base, [f"/api/sheets/{i}/image.png" for i in ids[:n]])
            for i, r in zip(ids[:n], res):
                _assert_png_a4(r, f"n={n} sheet {i}")
            assert proc.poll() is None, f"n={n} サーバ異常終了 rc={proc.returncode}"
            assert _get(base, "/api/sheets")[0] == 200, f"n={n} 後の GET /api/sheets"
