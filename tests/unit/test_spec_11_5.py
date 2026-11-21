"""仕様 11.5（duplicate の繰り返し面数 print.duplicate_count）＋「11.5 の細則」の機械 TC。

正本: ai_docs/specs/spec_11_5_tc.md の機械 TC（N-・E-・B-）と、末尾の追補 2 つ
（「本文の訂正」N-14（改）・E-11（改）、「11.5 の細則の反映」N-32〜35・E-15・E-16・B-18〜21・N-01/07/24（改））。
対象は N-01〜N-35・E-01〜E-16・B-01〜B-21（計 72）。画面 TC（S-）・自動実行不可（X-）は対象外。
実 lp・実 home は使わない（PATH 先頭に引数を記録するだけの偽 lp。一時 home）。
入力画像: D-J3・D-J1・D-JR1・D-J0 は tests/acceptance/fixtures/images の画像を inbox へ複製（読み取りのみ）。
D-J4・D-J12・D-JMIX はテスト内の一時フォルダに合成画像で作る（tests/acceptance には足さない）。
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from print_edit.api.app import create_app
from print_edit.cli import main
from print_edit.core.settings import Settings
from print_edit.home import Home

from test_spec_11_3 import Env, fake_lp, lp  # noqa: F401  (fake_lp は autouse fixture)

FX = Path(__file__).resolve().parents[1] / "acceptance" / "fixtures" / "images"
ABSENT = object()  # config.json に duplicate_count のキーを書かない

FIXTURE_FILE = {"J3": "a3_three_col", "J1": "a1_deg_p15", "JR1": "a5_wrong_size_15", "J0": "a5_zero_noise"}
SYNTH = ("J4", "J12", "JMIX")


# ================================================================ 共通部品
class Plain(Env):
    """config.json 無し（または raw を手書き）の home。"""

    def __init__(self, base, raw=None):
        self.home = Home(Path(base) / "h")
        self.home.ensure(Settings.model_validate({"intake": {"stable_wait_s": 0}}))
        if raw is not None:
            (self.home.root / "config.json").write_text(json.dumps(raw))
        self.c = TestClient(create_app(self.home))
        self.n = 0


def cfgfile(e):
    return e.home.root / "config.json"


def feed(e, d):
    """前提データ記号 → inbox に入力を置く。"""
    if d in FIXTURE_FILE:
        shutil.copy(FX / f"{FIXTURE_FILE[d]}.png", e.inbox / f"{FIXTURE_FILE[d]}.png")
    elif d == "J4":
        e.drop_scan(4)  # D-J4: ok カード 4 枚（index 1〜4）
    elif d == "J12":
        e.drop_scan(12)  # D-J12: ok カード 12 枚（index 1〜12）
    elif d == "JMIX":
        e.drop_scan(kinds=["ok", "ok", "review"])  # D-JMIX: ok 2 枚（index 1・2）＋ review 1 枚（index 3）
    elif d is not None:
        raise AssertionError(d)


@pytest.fixture
def mkd(tmp_path):
    """mkd(data, N, ...) -> Env。N: ABSENT=キー無し / None=項目に null / 整数。呼ぶたびに新しい home。"""
    cnt = [0]

    def build(data=None, N=ABSENT, *, cps=None, output="pdf", timing="duplicate", printer="Q1", auto=True,
              copies=1, lp_options=None):
        cnt[0] += 1
        base = tmp_path / f"d{cnt[0]}"
        base.mkdir()
        pr = {"output": output, "timing": timing, "auto_print": auto, "copies": copies}
        if output == "lp":
            pr["printer_name"] = printer
        if lp_options is not None:
            pr["lp_options"] = lp_options
        dpi = 150 if (data in SYNTH or data is None) else 600
        if N is not ABSENT:
            pr["duplicate_count"] = N
        e = Env(base, {"layout": {"cards_per_sheet": cps}, "print": pr, "intake": {"expected_dpi": dpi}})
        feed(e, data)
        return e

    return build


@pytest.fixture
def mkp(tmp_path):
    cnt = [0]

    def build(raw=None):
        cnt[0] += 1
        base = tmp_path / f"p{cnt[0]}"
        base.mkdir()
        return Plain(base, raw)

    return build


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def txt(r):
    return json.dumps(r.json(), ensure_ascii=False)


def getcfg(e):
    r = e.c.get("/api/config")
    assert r.status_code == 200, r.text
    return r.json()


def put(e, mutate):
    cfg = getcfg(e)
    mutate(cfg)
    return e.c.put("/api/config", json=cfg)


def setdup(v):
    return lambda c: c["print"].__setitem__("duplicate_count", v)


def setcps(v):
    return lambda c: c["layout"].__setitem__("cards_per_sheet", v)


def both(cps, dup):
    def f(c):
        c["layout"]["cards_per_sheet"] = cps
        c["print"]["duplicate_count"] = dup
    return f


def cfgsnap(e):
    """設定不変の基準: config.json の SHA-256（無ければ None）と GET /api/config の本文。"""
    p = cfgfile(e)
    return (sha(p) if p.exists() else None, getcfg(e))


def seq(e, names_sorted=True):
    """並び: 全シートを id 昇順に、各シートの sheet_cards を slot 昇順に並べた card index の列。
    同時に PDF の実在・NN 昇順と id 昇順の一致・NN.layout.json の slots（件数・card の NN）が sheet_cards と一致することを確認する。"""
    res, names = [], []
    for s in e.q("SELECT id, pdf_path FROM sheets ORDER BY id"):
        p = e.abspdf(s["pdf_path"])
        assert p.exists(), p
        names.append(p.name)
        rows = e.q("SELECT c.idx AS idx FROM sheet_cards sc JOIN cards c ON c.id=sc.card_id "
                   "WHERE sc.sheet_id=? ORDER BY sc.slot", s["id"])
        sc = [r["idx"] for r in rows]
        lay = json.loads(p.with_name(p.stem + ".layout.json").read_text())
        slots = sorted(lay["slots"], key=lambda x: x["index"])
        assert len(slots) == len(sc), (len(slots), sc)
        assert [int(Path(x["card"]).stem) for x in slots] == sc, ([x["card"] for x in slots], sc)
        res.append(sc)
    if names_sorted:
        assert names == sorted(names)
    return res


def once(e):
    rows = e.q("SELECT card_id, COUNT(DISTINCT sheet_id) AS n FROM sheet_cards GROUP BY card_id")
    return bool(rows) and all(r["n"] == 1 for r in rows)


def faces(s):
    return [len(x) for x in s]


def sc_rows(e):
    return e.q("SELECT sheet_id, slot, card_id FROM sheet_cards ORDER BY sheet_id, slot")


def n_sheets(e):
    return e.q("SELECT COUNT(*) AS n FROM sheets")[0]["n"]


def pdf_files(e):
    return sorted((e.home.root / "jobs").rglob("*.pdf")) if (e.home.root / "jobs").exists() else []


def ing(e, capsys):
    """CLI の ingest（stdout は [{"job_id","status","cards","sheets"}]）。JSON が出ないときは stderr を理由に出す。"""
    capsys.readouterr()
    code = main(["ingest", "--home", str(e.home.root)])
    cap = capsys.readouterr()
    try:
        out = json.loads(cap.out)
    except ValueError:
        pytest.fail(f"ingest が結果を出さなかった: code={code} stderr={cap.err.strip()[:300]}")
    assert len(out) == 1, out
    return code, out[0]


def card_status(e):
    return {r["idx"]: r["status"] for r in e.q("SELECT idx, status FROM cards")}


def review_id(e):
    return e.q("SELECT id FROM cards WHERE status='review'")[0]["id"]


def lpargs(line):
    return line.split()


def same(a, b):
    import os
    return os.path.realpath(str(a)) == os.path.realpath(str(b))


def sheet_pdfs(e):
    return [e.abspdf(r["pdf_path"]) for r in e.q("SELECT pdf_path FROM sheets ORDER BY id")]


# ================================================================ 正常系
def test_N01_null_keeps_12_card_example(mkd, capsys):
    e = mkd("J12", None)
    code, o = ing(e, capsys)
    assert o["cards"] == 12 and o["sheets"] == 2
    assert seq(e) == [list(range(1, 11)), [11, 12] * 5]


def test_N02_no_key_in_config_is_classic_duplicate(mkp, capsys):
    e = mkp({"intake": {"stable_wait_s": 0, "expected_dpi": 600}, "print": {"output": "pdf", "timing": "duplicate"}})
    feed(e, "J3")
    code, o = ing(e, capsys)
    assert o["cards"] == 3 and o["sheets"] == 1
    s = seq(e)
    assert s == [[1, 2, 3, 1, 2, 3, 1, 2, 3, 1]] and faces(s) == [10]


def test_N03_no_config_file_reads_null(mkp):
    e = mkp()
    assert not cfgfile(e).exists()
    r = e.c.get("/api/config")
    assert r.status_code == 200
    assert r.json()["print"]["duplicate_count"] is None
    assert r.json()["print"]["timing"] == "per_scan"


def test_N04_null_with_cards_per_sheet_2(mkd, capsys):
    e = mkd("J3", None, cps=2)
    code, o = ing(e, capsys)
    assert o["sheets"] == 2
    s = seq(e)
    assert s == [[1, 2], [3, 3]] and faces(s) == [2, 2]


def test_N05_example1_3cards_N4(mkd, capsys):
    e = mkd("J3", 4)
    code, o = ing(e, capsys)
    assert o["cards"] == 3 and o["sheets"] == 2
    s = seq(e)
    assert s == [[1, 1, 1, 1, 2, 2, 2, 2], [3, 3, 3, 3]] and faces(s) == [8, 4]


def test_N06_example2_3cards_N10(mkd, capsys):
    e = mkd("J3", 10)
    code, o = ing(e, capsys)
    assert o["sheets"] == 3
    s = seq(e)
    assert s == [[1] * 10, [2] * 10, [3] * 10] and faces(s) == [10, 10, 10]


def test_N07_example3_4cards_N3(mkd, capsys):
    e = mkd("J4", 3)
    code, o = ing(e, capsys)
    assert o["sheets"] == 2
    s = seq(e)
    assert s == [[1, 1, 1, 2, 2, 2, 3, 3, 3], [4, 4, 4]] and faces(s) == [9, 3]


def test_N08_example4_3cards_N1(mkd, capsys):
    e = mkd("J3", 1)
    code, o = ing(e, capsys)
    assert o["sheets"] == 1
    s = seq(e)
    assert s == [[1, 2, 3]] and faces(s) == [3]


def test_N09_layout_slots_and_coordinates(mkd, capsys):
    e = mkd("J3", 4)
    ing(e, capsys)
    sheets = e.q("SELECT id, pdf_path FROM sheets ORDER BY id")
    p1, p2 = (e.abspdf(s["pdf_path"]) for s in sheets)
    lay1 = json.loads(p1.with_name(p1.stem + ".layout.json").read_text())
    lay2 = json.loads(p2.with_name(p2.stem + ".layout.json").read_text())
    sl = lay1["slots"]
    assert len(sl) == 8 and [x["index"] for x in sl] == list(range(1, 9))
    assert [Path(x["card"]).name for x in sl] == ["01.png"] * 4 + ["02.png"] * 4
    rows = e.q("SELECT slot FROM sheet_cards WHERE sheet_id=? ORDER BY slot", sheets[0]["id"])
    assert [r["slot"] for r in rows] == list(range(1, 9))

    def near(slot, ex, ey):
        return abs(slot["x"] - ex) <= 0.5 and abs(slot["y"] - ey) <= 0.5

    assert near(sl[0], 14, 11) and near(sl[1], 105, 11) and near(sl[2], 14, 66) and near(sl[7], 105, 176)
    s2 = lay2["slots"]
    assert len(s2) == 4 and {Path(x["card"]).name for x in s2} == {"03.png"}
    assert (s2[0]["x"], s2[0]["y"]) == (sl[0]["x"], sl[0]["y"])


@pytest.mark.parametrize("N,data,total", [(4, "J3", 12), (10, "J3", 30), (3, "J4", 12), (1, "J3", 3)])
def test_N10_each_card_on_one_sheet_and_rows(mkd, capsys, N, data, total):
    e = mkd(data, N)
    ing(e, capsys)
    assert once(e)
    assert e.q("SELECT COUNT(*) AS n FROM sheet_cards")[0]["n"] == total


def test_N11_does_not_fit_cps7(mkd, capsys):
    e = mkd("J3", 3, cps=7)
    code, o = ing(e, capsys)
    assert o["sheets"] == 2
    s = seq(e)
    assert s == [[1, 1, 1, 2, 2, 2], [3, 3, 3]] and faces(s) == [6, 3] and once(e)


def test_N12_does_not_fit_cps5(mkd, capsys):
    e = mkd("J3", 2, cps=5)
    code, o = ing(e, capsys)
    assert o["sheets"] == 2
    s = seq(e)
    assert s == [[1, 1, 2, 2], [3, 3]] and faces(s) == [4, 2] and once(e)


def test_N13_per_scan_ignores_duplicate_count(mkd, capsys):
    e = mkd("J3", 4, output="pdf", timing="per_scan")
    code, o = ing(e, capsys)
    assert o["sheets"] == 1 and seq(e) == [[1, 2, 3]]
    r = mkd("J3", None, output="pdf", timing="per_scan")
    ing(r, capsys)
    assert (n_sheets(e), seq(e), sc_rows(e)) == (n_sheets(r), seq(r), sc_rows(r))


def test_N14_fill_ignores_duplicate_count(mkd, capsys):  # N-14（改）: duplicate_count=3
    e = mkd("J3", 3, output="pdf", timing="fill", cps=3)
    code, o = ing(e, capsys)
    assert o["sheets"] == 1
    s = seq(e)
    assert s == [[1, 2, 3]] and s != [[1, 1, 1]]
    r = mkd("J3", None, output="pdf", timing="fill", cps=3)
    ing(r, capsys)
    assert (n_sheets(e), s, sc_rows(e)) == (n_sheets(r), seq(r), sc_rows(r))


def test_N15_fill_remainder_stays_pending(mkd, capsys):
    e = mkd("J3", 2, output="pdf", timing="fill", cps=4)
    ing(e, capsys)
    assert n_sheets(e) == 0 and pdf_files(e) == []
    assert [r["status"] for r in e.q("SELECT status FROM cards")] == ["pending"] * 3
    r = mkd("J3", None, output="pdf", timing="fill", cps=4)
    ing(r, capsys)
    assert n_sheets(r) == 0
    assert [x["status"] for x in r.q("SELECT status FROM cards")] == ["pending"] * 3


def test_N16_capacity_unaffected_by_N(mkd):
    a, b = mkd(None, 4), mkd(None, None)
    ra, rb = a.c.get("/api/capacity"), b.c.get("/api/capacity")
    assert ra.status_code == rb.status_code == 200
    assert ra.json() == rb.json()
    assert (ra.json()["capacity"], ra.json()["columns"], ra.json()["rows"]) == (10, 2, 5)


def test_N17_saved_as_integer(mkp, capsys):
    e = mkp()
    r = put(e, setdup(4))
    assert r.status_code == 200, r.text
    g = getcfg(e)["print"]["duplicate_count"]
    assert g == 4 and type(g) is int
    capsys.readouterr()
    main(["config", "show", "--home", str(e.home.root)])
    shown = json.loads(capsys.readouterr().out)["print"]["duplicate_count"]
    assert shown == 4 and type(shown) is int
    saved = json.loads(cfgfile(e).read_text())["print"]["duplicate_count"]
    assert saved == 4 and type(saved) is int


def test_N18_missing_key_in_put_resets_to_null(mkp):
    e = mkp()
    assert put(e, setdup(4)).status_code == 200
    assert getcfg(e)["print"]["duplicate_count"] == 4
    r = put(e, lambda c: c["print"].pop("duplicate_count", None))
    assert r.status_code == 200, r.text
    assert getcfg(e)["print"]["duplicate_count"] is None


def _prop(schema):
    def deref(n):
        if "$ref" in n:
            cur = schema
            for k in n["$ref"].lstrip("#/").split("/"):
                cur = cur[k]
            return cur
        return n

    p = deref(schema["properties"]["print"])
    return p["properties"]["duplicate_count"]


def test_N19_schema(mkp):
    e = mkp()
    r = e.c.get("/api/config/schema")
    assert r.status_code == 200
    prop = _prop(r.json())
    opts = prop.get("anyOf") or prop.get("oneOf") or [prop]
    ints = [o for o in opts if o.get("type") == "integer"]
    nulls = [o for o in opts if o.get("type") == "null"]
    assert ints and nulls
    assert ints[0].get("minimum") == 1 or ints[0].get("exclusiveMinimum") == 0
    assert "default" in prop and prop["default"] is None


def test_N20_approve_makes_N_face_sheet(mkd, lp, capsys):
    e = mkd("JR1", 4, output="lp", auto=False)
    code, o = ing(e, capsys)
    assert n_sheets(e) == 0
    r = e.c.post(f"/api/cards/{review_id(e)}/approve")
    assert r.status_code == 200, r.text
    assert r.json()["delivery"] == {"ok": True, "error": None}
    assert n_sheets(e) == 1 and e.q("SELECT status FROM sheets")[0]["status"] == "held"
    s = seq(e)
    assert s == [[1, 1, 1, 1]] and faces(s) == [4]
    assert len(e.q("SELECT DISTINCT card_id FROM sheet_cards")) == 1
    assert e.q("SELECT COUNT(*) AS n FROM sheet_cards")[0]["n"] == 4
    assert lp.calls() == []


def test_N21_approve_auto_print_sends_once(mkd, lp, capsys):
    e = mkd("JR1", 4, output="lp", auto=True)
    ing(e, capsys)
    r = e.c.post(f"/api/cards/{review_id(e)}/approve")
    assert r.status_code == 200, r.text
    assert n_sheets(e) == 1 and seq(e) == [[1, 1, 1, 1]]
    assert e.q("SELECT status FROM sheets")[0]["status"] == "sent"
    calls = lp.calls()
    assert len(calls) == 1
    a = lpargs(calls[0])
    assert a[:4] == ["-d", "Q1", "-n", "1"] and len(a) == 5
    assert same(a[-1], sheet_pdfs(e)[0]) and a[-1].endswith("sheets/01.pdf")
    assert card_status(e) == {1: "printed"}


def test_N22_approve_null_fills_slots(mkd, capsys):
    e = mkd("JR1", None)
    ing(e, capsys)
    r = e.c.post(f"/api/cards/{review_id(e)}/approve")
    assert r.status_code == 200, r.text
    s = seq(e)
    assert n_sheets(e) == 1 and s == [[1] * 10] and faces(s) == [10]


def test_N23_review_only_makes_no_sheet(mkd, capsys):
    e = mkd("JR1", 4)
    code, o = ing(e, capsys)
    assert o["cards"] == 1 and o["sheets"] == 0
    assert n_sheets(e) == 0 and pdf_files(e) == []
    assert e.q("SELECT COUNT(*) AS n FROM sheet_cards")[0]["n"] == 0
    assert card_status(e) == {1: "review"}


def test_N24_review_card_not_in_sheet(mkd, capsys):  # N-24（改）
    e = mkd("JMIX", 2)
    code, o = ing(e, capsys)
    assert o["sheets"] == 1
    assert seq(e) == [[1, 1, 2, 2]]
    assert e.q("SELECT COUNT(*) AS n FROM sheet_cards sc JOIN cards c ON c.id=sc.card_id WHERE c.idx=3")[0]["n"] == 0
    assert card_status(e)[3] == "review"


def test_N25_api_ingest_same_rule(mkd):
    e = mkd("J3", 4)
    r = e.c.post("/api/ingest")
    assert r.status_code == 200, r.text
    out = r.json()
    assert len(out) == 1 and out[0]["cards"] == 3 and out[0]["sheets"] == 2
    assert seq(e) == [[1, 1, 1, 1, 2, 2, 2, 2], [3, 3, 3, 3]]


def test_N26_lp_sends_all_sheets(mkd, lp, capsys):
    e = mkd("J3", 4, output="lp", auto=True)
    code, o = ing(e, capsys)
    calls = lp.calls()
    pdfs = sheet_pdfs(e)
    assert len(calls) == 2 and len(pdfs) == 2
    for c, p, nn in zip(calls, pdfs, ("01.pdf", "02.pdf")):
        a = lpargs(c)
        assert a[:4] == ["-d", "Q1", "-n", "1"] and len(a) == 5 and same(a[-1], p) and a[-1].endswith(nn)
    assert [r["status"] for r in e.q("SELECT status FROM sheets ORDER BY id")] == ["sent", "sent"]
    assert set(card_status(e).values()) == {"printed"} and len(card_status(e)) == 3
    assert e.q("SELECT status FROM jobs")[0]["status"] == "ok"


def test_N27_copies_and_options_on_all_sheets(mkd, lp, capsys):
    e = mkd("J3", 4, output="lp", auto=True, copies=3, lp_options=["media=A4"])
    ing(e, capsys)
    calls = lp.calls()
    assert len(calls) == 2
    for c, p in zip(calls, sheet_pdfs(e)):
        a = lpargs(c)
        assert a[:-1] == ["-d", "Q1", "-n", "3", "-o", "media=A4"] and same(a[-1], p)


def _held_j3(mkd, capsys):
    e = mkd("J3", 4, output="lp", auto=False)
    ing(e, capsys)
    return e


def test_N28_auto_off_holds(mkd, lp, capsys):
    e = _held_j3(mkd, capsys)
    assert lp.calls() == []
    assert [r["status"] for r in e.q("SELECT status FROM sheets ORDER BY id")] == ["held", "held"]
    assert set(card_status(e).values()) == {"held"} and len(card_status(e)) == 3
    assert e.q("SELECT status FROM jobs")[0]["status"] == "ok"
    assert once(e)


def test_N29_discard_affects_only_its_cards(mkd, lp, capsys):
    e = _held_j3(mkd, capsys)
    ids = [r["id"] for r in e.q("SELECT id FROM sheets ORDER BY id")]
    r = e.c.post(f"/api/sheets/{ids[0]}/discard")
    assert r.status_code == 200 and r.json() == {"sheet_id": ids[0], "status": "discarded"}
    st = {x["id"]: x["status"] for x in e.q("SELECT id, status FROM sheets")}
    assert st == {ids[0]: "discarded", ids[1]: "held"}
    assert card_status(e) == {1: "discarded", 2: "discarded", 3: "held"}
    assert all(p.exists() for p in sheet_pdfs(e))
    assert lp.calls() == []


def test_N30_print_affects_only_its_cards(mkd, lp, capsys):
    e = _held_j3(mkd, capsys)
    ids = [r["id"] for r in e.q("SELECT id FROM sheets ORDER BY id")]
    r = e.c.post(f"/api/sheets/{ids[1]}/print")
    assert r.status_code == 200 and r.json() == {"sheet_id": ids[1], "sent": True, "output": "lp"}
    calls = lp.calls()
    assert len(calls) == 1
    a = lpargs(calls[0])
    assert a[:4] == ["-d", "Q1", "-n", "1"] and len(a) == 5 and same(a[-1], sheet_pdfs(e)[1])
    st = {x["id"]: x["status"] for x in e.q("SELECT id, status FROM sheets")}
    assert st == {ids[0]: "held", ids[1]: "sent"}
    assert card_status(e) == {1: "held", 2: "held", 3: "printed"}


def test_N31_reprint_does_not_rebuild(mkd, lp, capsys):
    e = mkd("J3", 4, output="lp", auto=True)
    code, o = ing(e, capsys)
    sheets = e.q("SELECT id, pdf_path FROM sheets ORDER BY id")
    assert len(sheets) == 2 and [r["status"] for r in e.q("SELECT status FROM sheets ORDER BY id")] == ["sent", "sent"]
    pdfs = sheet_pdfs(e)
    h0 = [(sha(p), sha(p.with_name(p.stem + ".layout.json"))) for p in pdfs]
    rows0, sc0 = e.q("SELECT id, pdf_path FROM sheets ORDER BY id"), sc_rows(e)
    lp.clear()
    assert put(e, setdup(2)).status_code == 200
    r = e.c.post(f"/api/jobs/{o['job_id']}/reprint")
    assert r.status_code == 200, r.text
    assert r.json() == {"sheets": [{"sheet_id": sheets[0]["id"], "sent": True},
                                   {"sheet_id": sheets[1]["id"], "sent": True}], "output": "lp"}
    calls = lp.calls()
    assert len(calls) == 2 and same(lpargs(calls[0])[-1], pdfs[0]) and same(lpargs(calls[1])[-1], pdfs[1])
    assert lpargs(calls[0])[-1].endswith("01.pdf") and lpargs(calls[1])[-1].endswith("02.pdf")
    assert [(sha(p), sha(p.with_name(p.stem + ".layout.json"))) for p in pdfs] == h0
    assert e.q("SELECT id, pdf_path FROM sheets ORDER BY id") == rows0 and sc_rows(e) == sc0


def test_N32_card_count_is_face_count(mkd, capsys):
    e = mkd("J3", 4)
    ing(e, capsys)
    r = e.c.get("/api/sheets")
    assert r.status_code == 200, r.text
    rows = r.json()
    ids = [x["id"] for x in e.q("SELECT id FROM sheets ORDER BY id")]
    assert [x["id"] for x in rows] == ids
    assert [x["card_count"] for x in rows] == [8, 4]
    s = seq(e)
    assert [x["card_count"] for x in rows] == faces(s)


def test_N33_card_count_null_duplicate(mkd, capsys):
    e = mkd("J3", None)
    ing(e, capsys)
    r = e.c.get("/api/sheets")
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 1 and rows[0]["card_count"] == 10
    assert seq(e) == [[1, 2, 3, 1, 2, 3, 1, 2, 3, 1]]


def _mix_before(e, capsys):
    """N-34・N-35・B-20 の①: 取り込み → 既存シート S1 の控え。"""
    ing(e, capsys)
    s1 = e.q("SELECT id, status, pdf_path FROM sheets")
    assert len(s1) == 1
    p = e.abspdf(s1[0]["pdf_path"])
    return {"rows": s1, "pdf": sha(p), "lay": sha(p.with_name(p.stem + ".layout.json")), "sc": sc_rows(e), "path": p}


def _s1_unchanged(e, b):
    sid = b["rows"][0]["id"]
    row = e.q("SELECT id, status, pdf_path FROM sheets WHERE id=?", sid)
    assert row == b["rows"]
    p = b["path"]
    assert sha(p) == b["pdf"] and sha(p.with_name(p.stem + ".layout.json")) == b["lay"]
    assert [r for r in sc_rows(e) if r["sheet_id"] == sid] == b["sc"]


def test_N34_approve_adds_new_sheet_keeps_existing_held(mkd, lp, capsys):
    e = mkd("JMIX", 2, output="lp", auto=False)
    b = _mix_before(e, capsys)
    assert seq(e) == [[1, 1, 2, 2]] and b["rows"][0]["status"] == "held"
    r = e.c.post(f"/api/cards/{review_id(e)}/approve")
    assert r.status_code == 200, r.text
    assert r.json()["delivery"] == {"ok": True, "error": None}
    assert n_sheets(e) == 2
    _s1_unchanged(e, b)
    new = e.q("SELECT id, status FROM sheets WHERE id<>?", b["rows"][0]["id"])[0]
    assert new["id"] > b["rows"][0]["id"] and new["status"] == "held"
    assert seq(e, names_sorted=False) == [[1, 1, 2, 2], [3, 3]]
    assert e.q("SELECT COUNT(*) AS n FROM sheet_cards")[0]["n"] == 6 and once(e)
    assert card_status(e) == {1: "held", 2: "held", 3: "held"}
    assert lp.calls() == []
    rows = e.c.get("/api/sheets").json()
    assert [x["card_count"] for x in rows] == [4, 2]


def test_N35_approve_sends_only_new_sheet(mkd, lp, capsys):
    e = mkd("JMIX", 2, output="lp", auto=True)
    b = _mix_before(e, capsys)
    lp.clear()
    r = e.c.post(f"/api/cards/{review_id(e)}/approve")
    assert r.status_code == 200, r.text
    assert r.json()["delivery"] == {"ok": True, "error": None}
    new = e.q("SELECT id, status, pdf_path FROM sheets WHERE id<>?", b["rows"][0]["id"])
    assert len(new) == 1 and n_sheets(e) == 2
    newp = e.abspdf(new[0]["pdf_path"])
    calls = lp.calls()
    assert len(calls) == 1
    a = lpargs(calls[0])
    assert a[:4] == ["-d", "Q1", "-n", "1"] and len(a) == 5 and same(a[-1], newp)
    assert not same(a[-1], b["path"])
    assert seq(e, names_sorted=False) == [[1, 1, 2, 2], [3, 3]]
    assert new[0]["status"] == "sent" and card_status(e)[3] == "printed"
    _s1_unchanged(e, b)


# ================================================================ 異常系
def test_E01_over_capacity_422(mkp):
    e = mkp()
    base = cfgsnap(e)
    r = put(e, setdup(11))
    assert r.status_code == 422
    assert "duplicate_count (11) が 1 シートの枚数 (10) を超えています" in txt(r)
    assert cfgsnap(e) == base and not cfgfile(e).exists()


def test_E02_over_cards_per_sheet_422(mkp):
    e = mkp()
    base = cfgsnap(e)
    r = put(e, both(4, 5))
    assert r.status_code == 422
    assert "duplicate_count (5) が 1 シートの枚数 (4) を超えています" in txt(r)
    assert cfgsnap(e) == base


def test_E03_checked_regardless_of_timing(mkp):
    e = mkp()
    base = cfgsnap(e)
    for t in ("per_scan", "fill", "duplicate"):
        def f(c, t=t):
            c["print"]["duplicate_count"] = 11
            c["print"]["timing"] = t
        r = put(e, f)
        assert r.status_code == 422, t
        assert "(11) が 1 シートの枚数 (10)" in txt(r), t
        assert cfgsnap(e) == base, t

    def g(c):
        c["layout"]["cards_per_sheet"] = 4
        c["print"]["duplicate_count"] = 5
        c["print"]["timing"] = "fill"
    r = put(e, g)
    assert r.status_code == 422
    assert "(5) が 1 シートの枚数 (4)" in txt(r)
    assert cfgsnap(e) == base


@pytest.mark.parametrize("v", [0, -1])
def test_E04_E05_zero_and_negative_422(mkp, v):
    e = mkp()
    base = cfgsnap(e)
    assert put(e, setdup(v)).status_code == 422
    assert cfgsnap(e) == base


@pytest.mark.parametrize("v", [1.5, "abc"])
def test_E06_non_integer_422(mkp, v):
    e = mkp()
    base = cfgsnap(e)
    assert put(e, setdup(v)).status_code == 422
    assert cfgsnap(e) == base


def test_E07_saved_value_remains_after_422(mkp):
    e = mkp()
    assert put(e, setdup(4)).status_code == 200
    assert getcfg(e)["print"]["duplicate_count"] == 4
    h = sha(cfgfile(e))
    assert put(e, setdup(11)).status_code == 422
    assert getcfg(e)["print"]["duplicate_count"] == 4
    assert sha(cfgfile(e)) == h


def test_E08_422_structure_same_as_cards_per_sheet(mkp):
    e = mkp()
    base = cfgsnap(e)
    r1 = put(e, setcps(11))
    r2 = put(e, setdup(11))
    assert r1.status_code == r2.status_code == 422
    assert set(r2.json().keys()) == set(r1.json().keys())
    assert cfgsnap(e) == base


def _capacity_cli(e, capsys):
    capsys.readouterr()
    try:
        code = main(["capacity", "--home", str(e.home.root)])
    except SystemExit as ex:
        code = ex.code if isinstance(ex.code, int) else 1
    except Exception as ex:  # 未捕捉の例外は終了コード非 0 + 例外メッセージが stderr に出るものとして扱う
        import traceback
        capsys.readouterr()
        return 1, traceback.format_exc()
    cap = capsys.readouterr()
    return code, cap.err


def test_E09_hand_written_config_error(mkp, capsys):
    e1 = mkp({"layout": {"cards_per_sheet": 11}})
    e2 = mkp({"print": {"duplicate_count": 11}, "layout": {"cards_per_sheet": None}})
    c1, _ = _capacity_cli(e1, capsys)
    c2, err2 = _capacity_cli(e2, capsys)
    assert c2 == c1 and c2 != 0
    assert "duplicate_count (11) が 1 シートの枚数 (10) を超えています" in err2


def test_E10_lp_failure_marks_error(mkd, lp, capsys):
    e = mkd("J1", 10, output="lp", auto=True)
    lp.plan(1)
    code, o = ing(e, capsys)
    assert o["status"] == "error" and o["sheets"] == 1 and code != 0
    assert [r["status"] for r in e.q("SELECT status FROM sheets")] == ["error"]
    s = seq(e)
    assert s == [[1] * 10] and faces(s) == [10]
    j = e.q("SELECT status, error FROM jobs")[0]
    assert j["status"] == "error" and j["error"]
    assert card_status(e)[1] != "printed"
    assert len(lp.calls()) == 1


def test_E11_empty_printer_name_errors_without_lp(mkd, lp, capsys):  # E-11（改）
    e = mkd("J1", 10, output="lp", auto=True, printer="")
    ing(e, capsys)
    assert lp.calls() == []
    assert [r["status"] for r in e.q("SELECT status FROM sheets")] == ["error"]
    assert faces(seq(e)) == [10]
    assert e.q("SELECT status FROM jobs")[0]["status"] == "error"
    assert card_status(e)[1] != "printed"


def test_E12_approve_send_failure_in_delivery(mkd, lp, capsys):
    e = mkd("JR1", 4, output="lp", auto=True)
    ing(e, capsys)
    lp.plan(1)
    r = e.c.post(f"/api/cards/{review_id(e)}/approve")
    d = r.json()["delivery"]
    assert d["ok"] is False and d["error"]
    assert [x["status"] for x in e.q("SELECT status FROM sheets")] == ["error"]
    assert faces(seq(e)) == [4]
    assert card_status(e)[1] != "printed"


def test_E13_held_print_failure_keeps_cards_held(mkd, lp, capsys):
    e = mkd("J3", 4, output="lp", auto=False, printer="")
    ing(e, capsys)
    ids = [r["id"] for r in e.q("SELECT id FROM sheets ORDER BY id")]
    r = e.c.post(f"/api/sheets/{ids[0]}/print")
    assert r.status_code == 400
    b = r.json()
    assert b["detail"].startswith("送信に失敗しました: ") and b["sent"] is False and b["output"] == "lp"
    assert e.q("SELECT status FROM sheets WHERE id=?", ids[0])[0]["status"] == "error"
    assert e.q("SELECT status FROM jobs")[0]["status"] == "error"
    cs = card_status(e)
    assert cs[1] == "held" and cs[2] == "held"
    assert lp.calls() == []


def test_E14_reprint_all_held_has_no_target(mkd, lp, capsys):
    e = mkd("J3", 4, output="lp", auto=False)
    code, o = ing(e, capsys)
    snap = e.snap()
    r = e.c.post(f"/api/jobs/{o['job_id']}/reprint")
    assert r.status_code == 200 and r.json() == {"sheets": [], "output": "lp"}
    assert lp.calls() == [] and e.snap() == snap


def test_E15_cards_per_sheet_over_capacity_classic_error(mkp):
    e = mkp()
    base = cfgsnap(e)
    r = put(e, both(11, None))
    assert r.status_code == 422
    t = txt(r)
    assert "cards_per_sheet" in t and "を超えています" in t
    assert cfgsnap(e) == base and not cfgfile(e).exists()


def test_E16_both_over(mkp):
    e = mkp()
    base = cfgsnap(e)
    r = put(e, both(11, 11))
    assert r.status_code == 422
    t = txt(r)
    assert "cards_per_sheet" in t and "を超えています" in t
    assert cfgsnap(e) == base


# ================================================================ 境界値
def test_B01_N1_is_saved(mkp):
    e = mkp()
    assert put(e, setdup(1)).status_code == 200
    assert getcfg(e)["print"]["duplicate_count"] == 1


def test_B02_N_equals_capacity_saved(mkp):
    e = mkp()
    assert put(e, setdup(10)).status_code == 200
    assert getcfg(e)["print"]["duplicate_count"] == 10


def test_B03_N_equals_cards_per_sheet_saved(mkp):
    e = mkp()
    assert put(e, both(4, 4)).status_code == 200
    assert getcfg(e)["print"]["duplicate_count"] == 4


def test_B04_boundary_with_non_default_capacity(mkp):
    e = mkp()
    assert put(e, lambda c: c["layout"].__setitem__("gap_y_mm", 15)).status_code == 200
    cap = e.c.get("/api/capacity").json()["capacity"]
    assert put(e, setdup(cap)).status_code == 200
    assert getcfg(e)["print"]["duplicate_count"] == cap
    base = cfgsnap(e)
    r = put(e, setdup(cap + 1))
    assert r.status_code == 422
    assert f"duplicate_count ({cap + 1}) が 1 シートの枚数 ({cap}) を超えています" in txt(r)
    assert cfgsnap(e) == base


def test_B05_null_is_saved(mkp):
    e = mkp()
    assert put(e, setdup(4)).status_code == 200
    assert put(e, setdup(None)).status_code == 200
    assert getcfg(e)["print"]["duplicate_count"] is None


def test_B06_config_without_print_section(mkp):
    e = mkp({})
    r = e.c.get("/api/config")
    assert r.status_code == 200
    assert r.json()["print"]["duplicate_count"] is None


def test_B07_explicit_null_in_config(mkp, capsys):
    e = mkp({"intake": {"stable_wait_s": 0, "expected_dpi": 600},
             "print": {"output": "pdf", "timing": "duplicate", "duplicate_count": None}})
    feed(e, "J3")
    ing(e, capsys)
    assert seq(e) == [[1, 2, 3, 1, 2, 3, 1, 2, 3, 1]]


def test_B08_remaining_slots_zero(mkd, capsys):
    e = mkd("J3", 3, cps=6)
    code, o = ing(e, capsys)
    assert o["sheets"] == 2
    s = seq(e)
    assert s == [[1, 1, 1, 2, 2, 2], [3, 3, 3]] and faces(s) == [6, 3]


def test_B09_N_equals_slots(mkd, capsys):
    e = mkd("J3", 4, cps=4)
    code, o = ing(e, capsys)
    assert o["sheets"] == 3
    s = seq(e)
    assert s == [[1] * 4, [2] * 4, [3] * 4] and faces(s) == [4, 4, 4]


def test_B10_N1_vs_null_cps2(mkd, capsys):
    e = mkd("J3", 1, cps=2)
    code, o = ing(e, capsys)
    assert o["sheets"] == 2
    s = seq(e)
    assert s == [[1, 2], [3]] and faces(s) == [2, 1]


def test_B11_single_card_N10(mkd, capsys):
    e = mkd("J1", 10)
    code, o = ing(e, capsys)
    assert o["sheets"] == 1
    assert seq(e) == [[1] * 10]


def test_B12_single_card_N1_is_one_face(mkd, capsys):
    e = mkd("J1", 1)
    code, o = ing(e, capsys)
    assert o["sheets"] == 1
    s = seq(e)
    assert s == [[1]] and faces(s) == [1]


def test_B13_null_faces_equal_slots(mkd, capsys):
    e = mkd("J3", None, cps=3)
    code, o = ing(e, capsys)
    assert o["sheets"] == 1
    s = seq(e)
    assert s == [[1, 2, 3]] and faces(s) == [3]


def test_B14_null_single_card_fills(mkd, capsys):
    e = mkd("J1", None)
    code, o = ing(e, capsys)
    assert o["sheets"] == 1
    s = seq(e)
    assert s == [[1] * 10] and faces(s) == [10]


def test_B15_zero_card_job(mkd, capsys):
    e = mkd("J0", 4)
    code, o = ing(e, capsys)
    assert o["cards"] == 0 and o["sheets"] == 0 and o["status"] == "review"
    assert n_sheets(e) == 0 and pdf_files(e) == []


def test_B16_approve_N_equals_capacity(mkd, capsys):
    e = mkd("JR1", 10, output="lp", auto=False)
    ing(e, capsys)
    r = e.c.post(f"/api/cards/{review_id(e)}/approve")
    assert r.status_code == 200, r.text
    s = seq(e)
    assert n_sheets(e) == 1 and s == [[1] * 10] and faces(s) == [10]
    assert e.q("SELECT status FROM sheets")[0]["status"] == "held"


def test_B17_approve_N1(mkd, capsys):
    e = mkd("JR1", 1, output="lp", auto=False)
    ing(e, capsys)
    r = e.c.post(f"/api/cards/{review_id(e)}/approve")
    assert r.status_code == 200, r.text
    s = seq(e)
    assert n_sheets(e) == 1 and s == [[1]] and faces(s) == [1]


def test_B18_card_count_single_card_sheet(mkd, capsys):
    e = mkd("J1", 4)
    ing(e, capsys)
    r = e.c.get("/api/sheets")
    assert r.status_code == 200, r.text
    rows = r.json()
    s = seq(e)
    assert len(rows) == 1 and rows[0]["card_count"] == 4
    assert faces(s) == [4]
    assert e.q("SELECT COUNT(*) AS n FROM sheet_cards")[0]["n"] == 4


@pytest.mark.parametrize("v", [2.0, "3", True, 1.5, "abc"], ids=["2.0", "str3", "true", "1.5", "abc"])
def test_B19_non_integer_same_as_cards_per_sheet(mkp, v):
    a, b = mkp(), mkp()
    ra = put(a, setcps(v))
    rb = put(b, setdup(v))
    assert ra.status_code == rb.status_code
    if v in (1.5, "abc"):
        assert ra.status_code == 422
    if ra.status_code == 200:
        va = getcfg(a)["layout"]["cards_per_sheet"]
        vb = getcfg(b)["print"]["duplicate_count"]
        assert vb == va and type(vb) is type(va)
    else:
        assert ra.status_code == 422 and not cfgfile(b).exists()


def test_B20_approve_null_keeps_existing_sheet_new_sheet_fills(mkd, lp, capsys):
    e = mkd("JMIX", None, output="lp", auto=False)
    b = _mix_before(e, capsys)
    assert seq(e) == [[1, 2] * 5]
    r = e.c.post(f"/api/cards/{review_id(e)}/approve")
    assert r.status_code == 200, r.text
    assert n_sheets(e) == 2
    _s1_unchanged(e, b)
    new = e.q("SELECT id, status FROM sheets WHERE id<>?", b["rows"][0]["id"])[0]
    assert new["status"] == "held"
    s = seq(e, names_sorted=False)
    assert s[1] == [3] * 10 and faces(s)[1] == 10
    assert lp.calls() == []


def test_B21_cards_per_sheet_boundary(mkp):
    a, b = mkp(), mkp()
    cap = a.c.get("/api/capacity").json()["capacity"]
    assert put(a, setcps(cap)).status_code == 200
    assert getcfg(a)["layout"]["cards_per_sheet"] == cap
    base = cfgsnap(b)
    r = put(b, setcps(cap + 1))
    assert r.status_code == 422
    t = txt(r)
    assert "cards_per_sheet" in t and "を超えています" in t
    assert cfgsnap(b) == base
