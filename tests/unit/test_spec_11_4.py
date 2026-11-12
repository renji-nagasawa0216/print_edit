"""仕様 11.4（別サイトからの書き込み要求の拒否）＋「11.4 の細則」の機械 TC。

正本: ai_docs/specs/spec_11_4_tc.md の機械 TC と追補（N-17・E-18 は追補の（改）行のみ）。
対象 65 件: N-01〜N-25・E-01〜E-33・B-01〜B-07。画面 TC・自動実行不可は対象外。
実 lp・実 home は使わない（PATH 先頭に引数を記録するだけの偽 lp。一時 home）。
E-01〜E-08 は test_E01_to_E08_ext_origin_denied[i] の i=1..8 に対応する。
"""
from __future__ import annotations

import hashlib
import http.client
import json
import shutil
import sqlite3
from pathlib import Path
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient

from print_edit.api.app import create_app
from print_edit.core.settings import Settings
from print_edit.home import Home

from test_spec_11_3 import Env, over, real_server, fake_lp  # noqa: F401  (fake_lp は autouse fixture)

MSG = "別サイトからの要求は受け付けません"
BODY403 = {"detail": MSG}
EXT = "https://evil.example"
OK_O = "http://127.0.0.1:8765"
NO = object()  # Origin ヘッダ無し
DETAIL409 = "印刷待ちではないシートです"
FIXTURE = Path(__file__).resolve().parents[1] / "acceptance" / "fixtures" / "images" / "a3_three_col.png"


# ================================================================ 共通部品
class Resp:
    def __init__(self, status, headers, body):
        self.status_code = status
        self.headers = list(headers)
        self.content = body

    @property
    def text(self):
        return self.content.decode("utf-8", "replace")

    def json(self):
        return json.loads(self.content)

    def header(self, name):
        for k, v in self.headers:
            if k.lower() == name.lower():
                return v
        return None


class Ctx:
    """Env（または config 無しの素の home）＋ TestClient（サーバ例外は 500 として返す）＋ 偽 lp。"""

    def __init__(self, env, lp):
        self.e = env
        self.lp = lp
        self.home = env.home
        self.tc = TestClient(create_app(env.home), raise_server_exceptions=False)
        self.ids = {}

    def q(self, sql, *a):
        return self.e.q(sql, *a)

    def req(self, method, path, origin=NO, headers=None, **kw):
        h = dict(headers or {})
        if origin is not NO:
            h["Origin"] = origin
        r = self.tc.request(method, path, headers=h, follow_redirects=False, **kw)
        return Resp(r.status_code, r.headers.multi_items(), r.content)

    def snap(self):
        """SNAP: DB 4 表の全行・config.json のバイト列・home 配下の全ファイル（db.sqlite3* 除く）・lp 回数。"""
        root = self.home.root
        con = sqlite3.connect(root / "db.sqlite3")
        try:
            dump = {t: con.execute(f"SELECT * FROM {t} ORDER BY rowid").fetchall()
                    for t in ("jobs", "cards", "sheets", "sheet_cards")}
        finally:
            con.close()
        cfg = root / "config.json"
        files = {}
        for p in sorted(root.rglob("*")):
            if p.is_file() and not p.name.startswith("db.sqlite3"):
                files[str(p.relative_to(root))] = (p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest())
        return {"db": dump, "cfg": cfg.read_bytes() if cfg.exists() else None, "files": files,
                "lp": len(self.lp.calls())}

    def sheet_status(self, sid):
        return self.q("SELECT status FROM sheets WHERE id=?", sid)[0]["status"]

    def card_statuses(self):
        return [r["status"] for r in self.q("SELECT status FROM cards ORDER BY id")]

    def pdf_rel(self):
        row = self.q("SELECT * FROM sheets ORDER BY id")[0]
        for v in row.values():
            if isinstance(v, str) and v.endswith(".pdf"):
                p = self.e.abspdf(v)
                assert p.exists()
                return str(p.relative_to(self.home.root))
        raise AssertionError("sheets 行に pdf パスが無い")

    def image_path(self):
        row = self.q("SELECT * FROM cards ORDER BY id")[0]
        p = self.e.abspdf(row["image_path"])
        assert p.exists()
        return p

    def sha(self, p):
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def denied(r, label=""):
    assert r.status_code == 403, f"{label} status={r.status_code} {r.text[:200]}"
    assert r.json() == BODY403, f"{label} body={r.text[:200]}"


def same_resp(a, b):
    assert (a.status_code, a.content) == (b.status_code, b.content), \
        f"{a.status_code} {a.content[:100]!r} != {b.status_code} {b.content[:100]!r}"
    assert a.header("content-type") == b.header("content-type")


@pytest.fixture
def lp(fake_lp):
    return fake_lp


@pytest.fixture
def mkc(tmp_path, lp):
    """build(kind) -> Ctx。kind: held / sent / review / inbox / cfg / empty / combined。呼ぶたびに新しい home。"""
    n = [0]

    def build(kind):
        n[0] += 1
        base = tmp_path / f"d{n[0]}"
        base.mkdir()
        if kind == "cfg":  # D-CFG: config.json 無し（既定値）
            class Plain(Env):
                def __init__(self, tp):
                    self.home = Home(Path(tp) / "h")
                    s = Settings.model_validate({"intake": {"stable_wait_s": 0}})
                    self.home.ensure(s)
                    self.n = 0
            return Ctx(Plain(base), lp)
        if kind == "inbox":  # D-INBOX
            e = Env(base, {"intake": {"expected_dpi": 600}, "print": {"output": "pdf", "timing": "per_scan"}})
            shutil.copy(FIXTURE, e.inbox / "a3_three_col.png")
            return Ctx(e, lp)
        if kind == "empty":
            return Ctx(Env(base, over(cps=2, auto=False)), lp)
        if kind in ("held", "combined"):  # D-HELD（combined は D-REVIEW のカードと D-INBOX の inbox ファイルも）
            e = Env(base, over(cps=2, auto=False))
            e.drop_scan(2)
            out = e.ingest()
            c = Ctx(e, lp)
            c.ids["job"] = out[0]["job_id"]
            c.ids["sheet"] = e.held()[0]["id"]
            assert len(e.held()) == 1 and c.card_statuses() == ["held", "held"]
            if kind == "combined":
                e.drop_scan(kinds=["review"])
                e.ingest()
                c.ids["card"] = c.q("SELECT id FROM cards WHERE status='review'")[0]["id"]
                shutil.copy(FIXTURE, e.inbox / "a3_three_col.png")
            return c
        if kind == "sent":  # D-SENT
            e = Env(base, over(cps=2, auto=True))
            lp.plan(0)
            e.drop_scan(2)
            out = e.ingest()
            lp.clear()
            c = Ctx(e, lp)
            c.ids["job"] = out[0]["job_id"]
            c.ids["sheet"] = c.q("SELECT id FROM sheets")[0]["id"]
            assert c.sheet_status(c.ids["sheet"]) == "sent" and c.card_statuses() == ["printed", "printed"]
            return c
        if kind == "review":  # D-REVIEW
            e = Env(base, over(cps=2, auto=False, timing="per_scan"))
            e.drop_scan(kinds=["review"])
            out = e.ingest()
            c = Ctx(e, lp)
            c.ids["job"] = out[0]["job_id"]
            c.ids["card"] = c.q("SELECT id FROM cards")[0]["id"]
            assert c.card_statuses() == ["review"] and e.n_sheets() == 0
            return c
        raise KeyError(kind)

    return build


def cfg_body(c, **print_over):
    cfg = c.req("GET", "/api/config").json()
    cfg["print"].update(print_over)
    return cfg


# 8 操作（N-01〜N-08 / E-01〜E-08）。(前提データ種別, 要求を返す関数)
OPS = {
    1: ("cfg", lambda c: ("PUT", "/api/config", {"json": cfg_body(c, copies=2)})),
    2: ("review", lambda c: ("POST", f"/api/cards/{c.ids['card']}/approve", {})),
    3: ("review", lambda c: ("POST", f"/api/cards/{c.ids['card']}/discard", {})),
    4: ("review", lambda c: ("POST", f"/api/cards/{c.ids['card']}/rotate", {})),
    5: ("sent", lambda c: ("POST", f"/api/jobs/{c.ids['job']}/reprint", {})),
    6: ("inbox", lambda c: ("POST", "/api/ingest", {})),
    7: ("held", lambda c: ("POST", f"/api/sheets/{c.ids['sheet']}/print", {})),
    8: ("held", lambda c: ("POST", f"/api/sheets/{c.ids['sheet']}/discard", {})),
}


def do_op(c, i, origin):
    m, p, kw = OPS[i][1](c)
    return c.req(m, p, origin=origin, **kw)


def combined_ops(c, origin=EXT):
    """E-01〜E-08 の 8 本を combined の home に順に流す（reprint は held の job を使う）。"""
    out = []
    sid, jid, card = c.ids["sheet"], c.ids["job"], c.ids["card"]
    reqs = [("PUT", "/api/config", {"json": cfg_body(c, copies=2)}),
            ("POST", f"/api/cards/{card}/approve", {}), ("POST", f"/api/cards/{card}/discard", {}),
            ("POST", f"/api/cards/{card}/rotate", {}), ("POST", f"/api/jobs/{jid}/reprint", {}),
            ("POST", "/api/ingest", {}), ("POST", f"/api/sheets/{sid}/print", {}),
            ("POST", f"/api/sheets/{sid}/discard", {})]
    for m, p, kw in reqs:
        out.append(c.req(m, p, origin=origin, **kw))
    return out


def run_ok(mkc, lp, i, origin):
    """N-01〜N-08 の期待結果（N-10 は origin=NO で全部流す）。"""
    c = mkc(OPS[i][0])
    if i == 4:
        before = c.sha(c.image_path())
    r = do_op(c, i, origin)
    assert r.status_code == 200, f"op{i}: {r.status_code} {r.text[:200]}"
    if i == 1:
        assert c.req("GET", "/api/config").json()["print"]["copies"] == 2
    elif i == 2:
        assert r.json()["delivery"] == {"ok": True, "error": None}
        assert [s["status"] for s in c.q("SELECT status FROM sheets")] == ["held"]
        assert lp.calls() == []
    elif i == 3:
        assert c.card_statuses() == ["discarded"] and lp.calls() == []
    elif i == 4:
        assert c.sha(c.image_path()) != before and c.card_statuses() == ["review"]
    elif i == 5:
        assert r.json() == {"sheets": [{"sheet_id": c.ids["sheet"], "sent": True}], "output": "lp"}
        calls = lp.calls()
        assert len(calls) == 1 and calls[0].startswith("-d Q1 -n 1 "), calls
    elif i == 6:
        j = r.json()
        assert len(j) == 1 and j[0]["status"] == "ok" and j[0]["cards"] == 3 and j[0]["sheets"] == 1, j
        assert list(c.e.inbox.iterdir()) == []
        assert len([p for p in (c.home.root / "processed").iterdir() if p.is_file()]) == 1
    elif i == 7:
        assert r.json() == {"sheet_id": c.ids["sheet"], "sent": True, "output": "lp"}
        calls = lp.calls()
        assert len(calls) == 1 and calls[0].startswith("-d Q1 -n 1 "), calls
        assert c.sheet_status(c.ids["sheet"]) == "sent" and c.card_statuses() == ["printed", "printed"]
    elif i == 8:
        assert r.json() == {"sheet_id": c.ids["sheet"], "status": "discarded"}
        assert c.sheet_status(c.ids["sheet"]) == "discarded" and c.card_statuses() == ["discarded"] * 2
        assert c.pdf_rel() and lp.calls() == []
    return c


def assert_discarded_ok(mkc, origin, **kw):
    c = mkc("held")
    r = c.req("POST", f"/api/sheets/{c.ids['sheet']}/discard", origin=origin, **kw)
    assert r.status_code == 200, f"Origin={origin!r}: {r.status_code} {r.text[:200]}"
    assert c.sheet_status(c.ids["sheet"]) == "discarded"


def assert_discard_denied(mkc, origin):
    c = mkc("held")
    s0 = c.snap()
    r = c.req("POST", f"/api/sheets/{c.ids['sheet']}/discard", origin=origin)
    denied(r, f"Origin={origin!r}")
    assert c.snap() == s0


def raw(base, method, path, headers=(), body=None):
    """生の要求（空の Origin・Origin 複数・生のパスを加工せず送る）。"""
    u = urlparse(base)
    conn = http.client.HTTPConnection(u.hostname, u.port, timeout=30)
    try:
        conn.putrequest(method, path, skip_accept_encoding=True)
        for k, v in headers:
            conn.putheader(k, v)
        if body is None and method in ("POST", "PUT", "PATCH"):
            conn.putheader("Content-Length", "0")
        conn.endheaders(body)
        r = conn.getresponse()
        return Resp(r.status, r.getheaders(), r.read())
    finally:
        conn.close()


# ================================================================ 正常系
def test_N01_put_config_ok_origin(mkc, lp):
    """N-01"""
    run_ok(mkc, lp, 1, OK_O)


def test_N02_approve_ok_origin(mkc, lp):
    """N-02"""
    run_ok(mkc, lp, 2, OK_O)


def test_N03_card_discard_ok_origin(mkc, lp):
    """N-03"""
    run_ok(mkc, lp, 3, OK_O)


def test_N04_rotate_ok_origin(mkc, lp):
    """N-04"""
    run_ok(mkc, lp, 4, OK_O)


def test_N05_reprint_ok_origin(mkc, lp):
    """N-05"""
    run_ok(mkc, lp, 5, OK_O)


def test_N06_ingest_ok_origin(mkc, lp):
    """N-06"""
    run_ok(mkc, lp, 6, OK_O)


def test_N07_sheet_print_ok_origin(mkc, lp):
    """N-07"""
    run_ok(mkc, lp, 7, OK_O)


def test_N08_sheet_discard_ok_origin(mkc, lp):
    """N-08"""
    run_ok(mkc, lp, 8, OK_O)


def test_N09_localhost_origin(mkc):
    """N-09"""
    assert_discarded_ok(mkc, "http://localhost:8765")


def test_N10_no_origin_header(mkc, lp):
    """N-10: 8 操作とも Origin 無しで N-01〜N-08 と同じ結果"""
    for i in range(1, 9):
        lp.clear()
        run_ok(mkc, lp, i, NO)


def test_N11_port_differs(mkc):
    """N-11"""
    assert_discarded_ok(mkc, "http://127.0.0.1:1")
    assert_discarded_ok(mkc, "http://localhost:9999")


def test_N12_scheme_port_omitted(mkc):
    """N-12"""
    assert_discarded_ok(mkc, "https://localhost:8443")
    assert_discarded_ok(mkc, "http://localhost")


def test_N13_host_external_origin_ok(mkc):
    """N-13"""
    assert_discarded_ok(mkc, OK_O, headers={"Host": "evil.example"})


def test_N14_host_external_no_origin(mkc):
    """N-14"""
    assert_discarded_ok(mkc, NO, headers={"Host": "evil.example"})


def test_N15_ext_get_list(mkc):
    """N-15"""
    c = mkc("held")
    r = c.req("GET", "/api/sheets?status=held", origin=EXT)
    j = r.json()
    assert r.status_code == 200 and len(j) == 1 and {x["status"] for x in j} == {"held"}


def test_N16_ext_all_gets(mkc):
    """N-16: 10 本の GET は Origin 無しと同一"""
    c = mkc("held")
    sid, jid = c.ids["sheet"], c.ids["job"]
    paths = ["/api/config", "/api/config/schema", "/api/capacity", "/api/jobs", f"/api/jobs/{jid}",
             "/api/cards", "/api/info", "/api/layout/preview", "/api/sheets", f"/api/sheets/{sid}/image.png"]
    for p in paths:
        a, b = c.req("GET", p, origin=EXT), c.req("GET", p)
        same_resp(a, b)
        assert MSG not in a.text, p


def test_N17_ext_head_same_as_no_origin(mkc):
    """N-17（改）"""
    c = mkc("held")
    s0 = c.snap()
    for p in ("/api/sheets", f"/api/jobs/{c.ids['job']}"):
        a, b = c.req("HEAD", p, origin=EXT), c.req("HEAD", p)
        same_resp(a, b)
        assert a.status_code != 403 and MSG not in a.text
    assert c.snap() == s0


def test_N18_files_not_target(mkc):
    """N-18"""
    c = mkc("held")
    p = "/files/" + c.pdf_rel()
    a, b = c.req("GET", p, origin=EXT), c.req("GET", p)
    same_resp(a, b)
    assert a.content == (c.home.root / c.pdf_rel()).read_bytes()


def test_N19_root_html_not_target(mkc):
    """N-19"""
    c = mkc("empty")
    same_resp(c.req("GET", "/", origin=EXT), c.req("GET", "/"))


def test_N20_post_non_api_not_denied(mkc):
    """N-20"""
    c = mkc("empty")
    for p in ("/", "/files/x.png"):
        a, b = c.req("POST", p, origin=EXT), c.req("POST", p)
        same_resp(a, b)
        assert a.status_code != 403 and MSG not in a.text


def test_N21_real_server_ok_origin(mkc):
    """N-21"""
    c = mkc("held")
    with real_server(c.e) as (proc, base):
        r = raw(base, "POST", f"/api/sheets/{c.ids['sheet']}/discard", [("Origin", base)])
    assert r.status_code == 200
    assert c.sheet_status(c.ids["sheet"]) == "discarded"


def test_N22_real_server_no_origin(mkc):
    """N-22"""
    c = mkc("held")
    with real_server(c.e) as (proc, base):
        r = raw(base, "POST", f"/api/sheets/{c.ids['sheet']}/discard")
    assert r.status_code == 200
    assert c.sheet_status(c.ids["sheet"]) == "discarded"


@pytest.mark.parametrize("o", ["http://LOCALHOST:8765", "http://LocalHost:8765", "HTTP://127.0.0.1:8765"])
def test_N23_hostname_case_insensitive(mkc, o):
    """N-23"""
    assert_discarded_ok(mkc, o)


@pytest.mark.parametrize("o", ["http://x@127.0.0.1", "http://x:y@localhost:8765"])
def test_N24_userinfo_allowed(mkc, o):
    """N-24"""
    assert_discarded_ok(mkc, o)


@pytest.mark.parametrize("o", ["http://127.0.0.1:99999", "http://localhost:99999"])
def test_N25_out_of_range_port_allowed(mkc, o):
    """N-25"""
    assert_discarded_ok(mkc, o)


# ================================================================ 異常系
@pytest.mark.parametrize("i", range(1, 9))
def test_E01_to_E08_ext_origin_denied(mkc, lp, i):
    """E-01〜E-08（i=1..8 が E-0i）"""
    c = mkc(OPS[i][0])
    s0 = c.snap()
    denied(do_op(c, i, EXT), f"E-0{i}")
    assert c.snap() == s0
    if i == 1:
        assert c.req("GET", "/api/config").json()["print"]["copies"] == 1
        assert s0["cfg"] is None and not (c.home.root / "config.json").exists()
    if i == 2:
        assert c.card_statuses() == ["review"] and c.e.n_sheets() == 0
    if i in (3, 4):
        assert c.card_statuses() == ["review"]
    if i == 6:
        assert len(list(c.e.inbox.iterdir())) == 1 and c.q("SELECT COUNT(*) AS n FROM jobs")[0]["n"] == 0
        assert list((c.home.root / "processed").iterdir()) == []
    if i in (7, 8):
        assert c.sheet_status(c.ids["sheet"]) == "held" and c.card_statuses() == ["held", "held"]
    assert lp.calls() == []


def test_E09_origin_null(mkc):
    """E-09"""
    c = mkc("held")
    s0 = c.snap()
    denied(c.req("POST", f"/api/sheets/{c.ids['sheet']}/print", origin="null"))
    assert c.snap() == s0 and c.lp.calls() == []


@pytest.mark.parametrize("o", ["evil.example", "http://", "not a url"])
def test_E10_unparseable_origin(mkc, o):
    """E-10"""
    assert_discard_denied(mkc, o)


@pytest.mark.parametrize("o", ["http://localhost.evil.example", "http://127.0.0.1.evil.example",
                               "http://evil.example/127.0.0.1", "http://127.0.0.1@evil.example"])
def test_E11_lookalike_hosts(mkc, o):
    """E-11"""
    assert_discard_denied(mkc, o)


@pytest.mark.parametrize("o", ["http://127.0.0.2:8765", "http://0.0.0.0:8765", "http://[::1]:8765"])
def test_E12_other_loopback_forms(mkc, o):
    """E-12"""
    assert_discard_denied(mkc, o)


def test_E13_host_ok_origin_ext(mkc):
    """E-13"""
    c = mkc("held")
    s0 = c.snap()
    denied(c.req("POST", f"/api/sheets/{c.ids['sheet']}/discard", origin="http://evil.example",
                 headers={"Host": "127.0.0.1:8765"}))
    assert c.snap() == s0


def test_E14_ext_nonexistent_sheet(mkc):
    """E-14"""
    c = mkc("empty")
    s0 = c.snap()
    for p in ("/api/sheets/99999/print", "/api/sheets/99999/discard"):
        denied(c.req("POST", p, origin=EXT), p)
    assert c.snap() == s0


def test_E15_ext_state_mismatch(mkc):
    """E-15"""
    c = mkc("sent")
    s0 = c.snap()
    for a in ("print", "discard"):
        denied(c.req("POST", f"/api/sheets/{c.ids['sheet']}/{a}", origin=EXT), a)
    assert c.snap() == s0


def test_E16_ext_validation_error(mkc):
    """E-16"""
    c = mkc("cfg")
    s0 = c.snap()
    denied(c.req("PUT", "/api/config", origin=EXT, json=cfg_body(c, auto_print="abc")))
    assert c.snap() == s0


def test_E17_ext_nonexistent_card(mkc):
    """E-17"""
    c = mkc("empty")
    s0 = c.snap()
    denied(c.req("POST", "/api/cards/99999/approve", origin=EXT))
    assert c.snap() == s0


def test_E18_patch_delete_options_denied(mkc):
    """E-18（改）: PATCH・DELETE・OPTIONS も外部 Origin は 403"""
    c = mkc("held")
    sid = c.ids["sheet"]
    for m, p in (("PATCH", f"/api/sheets/{sid}/discard"), ("DELETE", f"/api/sheets/{sid}"),
                 ("OPTIONS", f"/api/sheets/{sid}/print"), ("OPTIONS", "/api/config")):
        s0 = c.snap()
        denied(c.req(m, p, origin=EXT), f"{m} {p}")
        assert c.snap() == s0


def test_E19_all_ops_in_sequence(mkc, lp):
    """E-19: 8 本連続でも何も変わらない"""
    c = mkc("combined")
    s0 = c.snap()
    for k, r in enumerate(combined_ops(c), 1):
        denied(r, f"op{k}")
    assert c.snap() == s0 and lp.calls() == []


def test_E20_ingest_denied_leaves_no_lock(mkc):
    """E-20"""
    c = mkc("inbox")
    denied(c.req("POST", "/api/ingest", origin=EXT))
    r = c.req("POST", "/api/ingest")
    j = r.json()
    assert r.status_code == 200 and len(j) == 1 and j[0]["status"] == "ok", (r.status_code, r.text[:200])


def test_E21_ok_origin_legacy_errors(mkc, lp):
    """E-21"""
    c = mkc("sent")
    cfg0 = c.snap()["cfg"]
    r = c.req("POST", "/api/sheets/99999/print", origin=OK_O)
    assert r.status_code == 404 and r.json() == {"detail": "sheet not found"}
    r = c.req("POST", f"/api/sheets/{c.ids['sheet']}/print", origin=OK_O)
    assert r.status_code == 409 and r.json() == {"detail": DETAIL409}
    assert lp.calls() == []
    r = c.req("PUT", "/api/config", origin=OK_O, json=cfg_body(c, auto_print="abc"))
    assert r.status_code == 422
    assert c.snap()["cfg"] == cfg0


def test_E22_no_origin_validation_error(mkc):
    """E-22"""
    c = mkc("cfg")
    s0 = c.snap()
    assert c.req("PUT", "/api/config", json=cfg_body(c, auto_print="abc")).status_code == 422
    assert c.snap() == s0


def test_E23_real_server_ext_origin_denied(mkc):
    """E-23"""
    c = mkc("held")
    s0 = c.snap()
    with real_server(c.e) as (proc, base):
        for o in ("https://evil.example", "null"):
            denied(raw(base, "POST", f"/api/sheets/{c.ids['sheet']}/discard", [("Origin", o)]), o)
    assert c.snap() == s0


def test_E24_empty_origin(mkc):
    """E-24: 空の Origin ヘッダ"""
    c = mkc("held")
    s0 = c.snap()
    with real_server(c.e) as (proc, base):
        for a in ("discard", "print"):
            denied(raw(base, "POST", f"/api/sheets/{c.ids['sheet']}/{a}", [("Origin", "")]), a)
    assert c.snap() == s0 and c.lp.calls() == []


@pytest.mark.parametrize("origins", [[OK_O, OK_O], [OK_O, EXT], [EXT, OK_O]])
def test_E25_multiple_origin_headers(mkc, origins):
    """E-25"""
    c = mkc("held")
    s0 = c.snap()
    with real_server(c.e) as (proc, base):
        denied(raw(base, "POST", f"/api/sheets/{c.ids['sheet']}/discard", [("Origin", o) for o in origins]))
    assert c.snap() == s0


@pytest.mark.parametrize("o", ["http://localhost.:8765", "http://127.0.0.1.:8765", "http://127.0.0.1.evil.com",
                               "http://localhost.evil.com", "http://127.1:8765", "http://127.1",
                               "http://[::1]", "http://[::1]:8765"])
def test_E26_not_exact_hostname(mkc, o):
    """E-26"""
    assert_discard_denied(mkc, o)


@pytest.mark.parametrize("o", ["http://[::1", "http://[", "://", "http://%zz"])
def test_E27_unparseable_is_403_not_500(mkc, o):
    """E-27"""
    assert_discard_denied(mkc, o)


@pytest.mark.parametrize("o", ["http://localhost:8765@evil.example", "http://127.0.0.1:8765@evil.example:99999",
                               "http://x@evil.example:99999"])
def test_E28_userinfo_port_external_host(mkc, o):
    """E-28"""
    assert_discard_denied(mkc, o)


def test_E29_percent_encoded_api(mkc):
    """E-29: /%61pi/... も対象"""
    c = mkc("combined")
    sid = c.ids["sheet"]
    with real_server(c.e) as (proc, base):
        for p in (f"/%61pi/sheets/{sid}/print", f"/%61pi/sheets/{sid}/discard", "/%61pi/ingest"):
            s0 = c.snap()
            denied(raw(base, "POST", p, [("Origin", EXT)]), p)
            assert c.snap() == s0
    assert c.lp.calls() == [] and len(list(c.e.inbox.iterdir())) == 1


def test_E30_unregistered_method_path(mkc):
    """E-30"""
    c = mkc("held")
    sid = c.ids["sheet"]
    cases = [("POST", "/api/jobs", {}), ("PUT", f"/api/sheets/{sid}/print", {}),
             ("OPTIONS", f"/api/sheets/{sid}/print",
              {"headers": {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"}})]
    for m, p, kw in cases:
        s0 = c.snap()
        denied(c.req(m, p, origin=EXT, **kw), f"{m} {p}")
        assert c.snap() == s0


def test_E31_ext_invalid_json_body(mkc):
    """E-31"""
    c = mkc("cfg")
    s0 = c.snap()
    denied(c.req("PUT", "/api/config", origin=EXT, headers={"Content-Type": "application/json"}, content=b"{"))
    denied(c.req("PUT", "/api/config", origin=EXT))
    assert c.snap() == s0


def test_E32_no_access_control_headers(mkc):
    """E-32"""
    c = mkc("held")
    sid = c.ids["sheet"]

    def check(r, label):
        assert r.status_code == 403, f"{label} status={r.status_code}"
        names = [k.lower() for k, _ in r.headers]
        assert not [n for n in names if n.startswith("access-control-")], (label, names)

    s0 = c.snap()
    check(c.req("PUT", "/api/config", origin=EXT, json=cfg_body(c, copies=2)), "PUT config")
    check(c.req("POST", f"/api/sheets/{sid}/discard", origin=EXT), "E-08")
    check(c.req("OPTIONS", f"/api/sheets/{sid}/print", origin=EXT,
                headers={"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"}),
          "preflight")
    with real_server(c.e) as (proc, base):
        check(raw(base, "POST", f"/api/sheets/{sid}/discard", [("Origin", "")]), "empty origin")
    assert c.snap() == s0


def test_E33_403_not_logged(mkc, lp, caplog):
    """E-33: アプリのログに 403・Origin・別サイトの言及が無い（テストクライアント側 httpx/httpcore のログは除く）"""
    c = mkc("combined")
    s0 = c.snap()
    caplog.set_level(0)
    for k, r in enumerate(combined_ops(c), 1):
        denied(r, f"op{k}")
    bad = []
    for rec in caplog.records:
        if rec.name.startswith(("httpx", "httpcore", "asyncio")):
            continue
        t = rec.getMessage()
        if "403" in t or "origin" in t.lower() or MSG in t:
            bad.append((rec.name, t))
    assert bad == []
    assert c.snap() == s0


# ================================================================ 境界値
@pytest.mark.parametrize("o", ["http://127.0.0.1:65535", "http://127.0.0.1", "https://127.0.0.1:443"])
def test_B01_port_scheme_boundary(mkc, o):
    """B-01"""
    assert_discarded_ok(mkc, o)


def test_B02_api_prefix_only_not_target(mkc):
    """B-02"""
    c = mkc("empty")
    for p in ("/apix", "/api2/sheets/1/discard"):
        a, b = c.req("POST", p, origin=EXT), c.req("POST", p)
        same_resp(a, b)
        assert a.status_code != 403 and MSG not in a.text


@pytest.mark.parametrize("o", ["http://127.0.0.10:8765", "http://localhost1", "http://xlocalhost"])
def test_B03_hostname_with_extra_chars(mkc, o):
    """B-03"""
    assert_discard_denied(mkc, o)


def test_B04_repeated_denial_not_409(mkc):
    """B-04"""
    c = mkc("held")
    s0 = c.snap()
    for _ in range(2):
        denied(c.req("POST", f"/api/sheets/{c.ids['sheet']}/discard", origin=EXT))
    assert c.snap() == s0


def test_B05_api_exact_and_slash(mkc):
    """B-05"""
    c = mkc("held")
    for p in ("/api", "/api/"):
        s0 = c.snap()
        denied(c.req("POST", p, origin=EXT), p)
        assert c.snap() == s0
    for p in ("/api", "/api/"):
        r = c.req("POST", p)
        assert r.status_code != 403 and MSG not in r.text, p


@pytest.mark.parametrize("o", ["http://127.0.0.1:0", "http://127.0.0.1:65536"])
def test_B06_port_numeric_edges(mkc, o):
    """B-06"""
    assert_discarded_ok(mkc, o)


def test_B07_percent_encoded_api_boundary(mkc):
    """B-07"""
    c = mkc("held")
    with real_server(c.e) as (proc, base):
        s0 = c.snap()
        denied(raw(base, "POST", "/%61pi", [("Origin", EXT)]))
        assert c.snap() == s0
        a = raw(base, "POST", "/%61pix", [("Origin", EXT)])
        b = raw(base, "POST", "/%61pix")
        same_resp(a, b)
        assert a.status_code != 403 and MSG not in a.text
