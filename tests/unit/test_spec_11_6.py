"""仕様 11.6（配置の寄せ先 layout.align_x・layout.align_y）の機械 TC。

正本: ai_docs/specs/spec_11_6_tc.md の機械 TC（N-01〜N-58・E-01〜E-10・B-01〜B-20、計 88 件）。
画面 TC（S-）と自動実行不可（X-）はテストにしない。期待値は TC の値をそのまま使う（誤差 0.01 mm）。
実 home・実 lp・実プリンタは使わない（一時 home と、引数を記録するだけの偽 lp を PATH 先頭に置く）。
入力画像は tests/acceptance/fixtures/images の D-J3・D-J1・D-JR1 を inbox へ複製する（読み取りのみ）。
PDF 解析は pypdfium2（先例テストと同じ依存）。メールは書かない。

TC に書かれていない呼び方（この TC 表と spec・先例テストだけから決めたもの）:
- 設定は config.json に手書きの JSON（dict）で置く（キー無し・片方だけ・不正値の TC があるため）。
- 取り込みは CLI `ingest`（終了コードが要る TC と標準）。N-26 だけ POST /api/ingest。
- E-09 の `print-edit capacity` はサブプロセスで実行（終了コードと stderr を実物で見るため）。
"""
from __future__ import annotations

import ctypes
import hashlib
import io
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
import pypdfium2.raw as pdfraw
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from print_edit.api.app import create_app
from print_edit.cli import main
from print_edit.core.settings import Settings
from print_edit.home import Home

from preset_api import get_preset_data, put_preset_data
from test_spec_11_3 import Env, fake_lp, lp  # noqa: F401  (fake_lp は autouse fixture)

FX = Path(__file__).resolve().parents[1] / "acceptance" / "fixtures" / "images"
FILES = {"J3": "a3_three_col.png", "J1": "a1_deg_p15.png", "JR1": "a5_wrong_size_15.png"}
PT = 25.4 / 72  # pt -> mm
TOL = 0.01
SIDES = ("left", "right", "top", "bottom")
DUP10 = [1, 2, 3, 1, 2, 3, 1, 2, 3, 1]
CAP10 = {"capacity": 10, "columns": 2, "rows": 5, "card_rotated": False}
NINE = [(ax, ay) for ay in ("top", "center", "bottom") for ax in ("left", "center", "right")]


# ================================================================ 設定・home
def cfg(ax="center", ay="center", *, timing="duplicate", layout=None, print_=None, device=None, output="pdf"):
    """CFG-A(x,y)（timing=duplicate）。timing="per_scan" で CFG-S(x,y)。intake は fixture 取り込み用の環境値だけ。"""
    c = {
        "intake": {"stable_wait_s": 0, "expected_dpi": 600},
        "layout": {"align_x": ax, "align_y": ay, **(layout or {})},
        "print": {"output": output, "timing": timing, **(print_ or {})},
    }
    if device:
        c["device"] = device
    return c


def cfgS(ax="center", ay="center", **kw):
    return cfg(ax, ay, timing="per_scan", **kw)


class Raw(Env):
    """config.json を手書きの dict で置く home（raw=None なら config.json 無し）。"""

    def __init__(self, base, raw=None):
        self.home = Home(Path(base) / "h")
        self.home.ensure(Settings.model_validate({"intake": {"stable_wait_s": 0}}))
        if raw is not None:
            (self.home.root / "config.json").write_text(json.dumps(raw))
        self.c = TestClient(create_app(self.home))
        self.n = 0


def feed(e, d):
    if d is not None:
        shutil.copy(FX / FILES[d], e.inbox / FILES[d])


@pytest.fixture
def mk(tmp_path):
    cnt = [0]

    def build(raw=None, data=None):
        cnt[0] += 1
        base = tmp_path / f"d{cnt[0]}"
        base.mkdir()
        e = Raw(base, raw)
        feed(e, data)
        return e

    return build


def ing(e, capsys):
    capsys.readouterr()
    code = main(["ingest", "--home", str(e.home.root)])
    cap = capsys.readouterr()
    try:
        out = json.loads(cap.out)
    except ValueError:
        pytest.fail(f"ingest が結果を出さなかった: code={code} stderr={cap.err.strip()[:300]}")
    return code, out


def go(mk, capsys, raw, data="J3"):
    """home を作り、fixture を置き、CLI で取り込む。終了コード 0 を確認し (env, layouts) を返す。"""
    e = mk(raw, data)
    code, out = ing(e, capsys)
    assert code == 0, (code, out)
    return e, layouts(e)


def sheet_rows(e):
    return e.q("SELECT id, job_id, pdf_path, status FROM sheets ORDER BY id")


def lay_of(pdf):
    p = Path(pdf)
    return json.loads(p.with_name(p.stem + ".layout.json").read_text())


def layouts(e):
    return [lay_of(e.abspdf(r["pdf_path"])) for r in sheet_rows(e)]


def pdfs(e):
    return [e.abspdf(r["pdf_path"]) for r in sheet_rows(e)]


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def putcfg(e, mutate):
    c = get_preset_data(e.c)
    mutate(c)
    return put_preset_data(e.c, c)


def cfgsnap(e):
    """設定不変: config.json の SHA-256（無ければ None）と既定プリセットの内容。"""
    p = e.home.root / "config.json"
    return (sha(p) if p.exists() else None, get_preset_data(e.c))


def cli_json(e, capsys, *args):
    capsys.readouterr()
    code = main([*args, "--home", str(e.home.root)])
    out = capsys.readouterr().out
    assert code == 0, (args, code)
    return json.loads(out)


# ================================================================ 判定語
def near(a, b, tol=TOL):
    return abs(a - b) <= tol + 1e-9


def by_index(lay):
    return {s["index"]: s for s in lay["slots"]}


def check_slots(lay, exp, w=91, h=55, n=None):
    """exp: {index: (x, y)}（w・h は全スロット共通）。n があれば件数と index 1〜n も確認する。"""
    d = by_index(lay)
    if n is not None:
        assert len(lay["slots"]) == n and sorted(d) == list(range(1, n + 1)), [s["index"] for s in lay["slots"]]
    for i, (x, y) in exp.items():
        s = d[i]
        assert near(s["x"], x) and near(s["y"], y) and near(s["w"], w) and near(s["h"], h), (i, s, (x, y, w, h))


def card_order(lay):
    return [int(Path(s["card"]).stem) for s in sorted(lay["slots"], key=lambda s: s["index"])]


def slot_ok(lay, X0, Y0, n=10, cols=2, gx=0, gy=0, w=91, h=55, order=DUP10):
    """SLOT-OK(X0,Y0): slots が n 件・index 1〜n・x,y が格子の式どおり・w=91・h=55。order があれば card の並びも見る。"""
    exp = {}
    for i in range(1, n + 1):
        col, row = (i - 1) % cols, (i - 1) // cols
        exp[i] = (X0 + col * (w + gx), Y0 + row * (h + gy))
    check_slots(lay, exp, w=w, h=h, n=n)
    if order is not None:
        assert card_order(lay) == order, card_order(lay)


def inside(lay, u=4.2, paper=(210, 297), corner=False):
    """INSIDE: すべてのスロットが印字可能域内・互いに重ならない。"""
    x0 = y0 = 0 if corner else u
    x1, y1 = paper[0] - u, paper[1] - u
    sl = lay["slots"]
    for s in sl:
        assert s["x"] >= x0 - TOL and s["y"] >= y0 - TOL, s
        assert s["x"] + s["w"] <= x1 + TOL and s["y"] + s["h"] <= y1 + TOL, s
    for i in range(len(sl)):
        for j in range(i + 1, len(sl)):
            a, b = sl[i], sl[j]
            ox = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
            oy = min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])
            assert not (ox > TOL and oy > TOL), (a, b)


def box_of(lay):
    sl = lay["slots"]
    return (min(s["x"] for s in sl), min(s["y"] for s in sl),
            max(s["x"] + s["w"] for s in sl), max(s["y"] + s["h"] for s in sl))


def classify(m, box):
    """トンボの向きの呼び方（TC 共通前提）。線分の端点順は問わない。どれでもなければ None。"""
    l, t, r, b = box
    x1, y1, x2, y2 = m["x1"], m["y1"], m["x2"], m["y2"]
    if abs(y1 - y2) <= TOL and abs(x1 - x2) > TOL:
        if max(x1, x2) <= l + TOL:
            return "left"
        if min(x1, x2) >= r - TOL:
            return "right"
    if abs(x1 - x2) <= TOL and abs(y1 - y2) > TOL:
        if max(y1, y2) <= t + TOL:
            return "top"
        if min(y1, y2) >= b - TOL:
            return "bottom"
    return None


def uniq(vals, tol=TOL):
    out = []
    for v in sorted(vals):
        if not out or v - out[-1] > tol + 1e-9:
            out.append(v)
    return out


def same_vals(got, exp):
    g, e = uniq(got), uniq(exp)
    return len(g) == len(e) and all(near(a, b) for a, b in zip(g, e))


def mark_common(lay, u=4.2, paper=(210, 297), corner=False):
    """MARK-COMMON: 全端点が印字可能域内（境界線上を含む）・長さ 0 の線分が無い。"""
    x0 = y0 = 0 if corner else u
    x1, y1 = paper[0] - u, paper[1] - u
    for m in lay["marks"]:
        for k in ("x1", "x2"):
            assert x0 - TOL <= m[k] <= x1 + TOL, m
        for k in ("y1", "y2"):
            assert y0 - TOL <= m[k] <= y1 + TOL, m
        assert math.hypot(m["x2"] - m["x1"], m["y2"] - m["y1"]) > 1e-3, m


def side_marks(lay):
    box = box_of(lay)
    out = {s: [] for s in SIDES}
    for m in lay["marks"]:
        s = classify(m, box)
        assert s is not None, ("どの向きにも当たらないトンボ", m, box)
        out[s].append(m)
    return out


def M(pos, lo, hi):
    """ある向きのトンボ: pos=裁断線の位置の集合（None なら判定しない）、lo〜hi=線分の延びる範囲。"""
    return (pos, lo, hi)


def check_marks(lay, left=None, right=None, top=None, bottom=None, u=4.2, paper=(210, 297), corner=False):
    """向きごとに期待（M(...)）または None（その向きのトンボ無し）を照合する。MARK-COMMON も確認する。
    左右は水平線分（位置=y・範囲=x）、上下は垂直線分（位置=x・範囲=y）。トンボの数・並びは判定しない。"""
    mark_common(lay, u, paper, corner)
    got = side_marks(lay)
    for side, exp in zip(SIDES, (left, right, top, bottom)):
        segs = got[side]
        if exp is None:
            assert segs == [], (side, segs)
            continue
        pos, lo, hi = exp
        assert segs, f"{side} のトンボが無い"
        horiz = side in ("left", "right")
        for m in segs:
            ext = (m["x1"], m["x2"]) if horiz else (m["y1"], m["y2"])
            assert near(min(ext), lo) and near(max(ext), hi), (side, m, lo, hi)
        if pos is not None:
            ps = [(m["y1"] + m["y2"]) / 2 if horiz else (m["x1"] + m["x2"]) / 2 for m in segs]
            assert same_vals(ps, pos), (side, uniq(ps), pos)


def ys_n10(first, step=55, k=6):
    return [first + step * i for i in range(k)]


# ---- PDF 解析（pypdfium2。原点は左下・1 pt = 25.4/72 mm）
def pdf_page_pt(pdf):
    doc = pdfium.PdfDocument(str(pdf))
    w, h = doc[0].get_size()
    doc.close()
    return w, h


def pdf_items(pdf):
    """PDF-RECT（画像の配置矩形 (x,y,w,h) mm・y は上端）と PDF-LINES（線分 (x1,y1,x2,y2) mm・原点左上）。"""
    doc = pdfium.PdfDocument(str(pdf))
    page = doc[0]
    _, H = page.get_size()
    rects, lines = [], []
    for o in page.get_objects():
        if o.type == pdfraw.FPDF_PAGEOBJ_IMAGE:
            l, b, r, t = o.get_bounds()
            rects.append((l * PT, (H - t) * PT, (r - l) * PT, (t - b) * PT))
        elif o.type == pdfraw.FPDF_PAGEOBJ_PATH:
            cur = None
            for i in range(pdfraw.FPDFPath_CountSegments(o.raw)):
                seg = pdfraw.FPDFPath_GetPathSegment(o.raw, i)
                x, y = ctypes.c_float(), ctypes.c_float()
                pdfraw.FPDFPathSegment_GetPoint(seg, x, y)
                t = pdfraw.FPDFPathSegment_GetType(seg)
                p = (x.value * PT, (H - y.value) * PT)
                if t == pdfraw.FPDF_SEGMENT_MOVETO:
                    cur = p
                elif t == pdfraw.FPDF_SEGMENT_LINETO and cur is not None:
                    lines.append((cur[0], cur[1], p[0], p[1]))
                    cur = p
    doc.close()
    return rects, lines


def match_all(got, exp, tol=TOL):
    """got と exp（同じ長さのタプルの列）が 1 つずつ対応する（順不同）。"""
    rest = list(exp)
    assert len(got) == len(rest), (len(got), len(rest))
    for g in got:
        for i, e in enumerate(rest):
            if all(near(a, b, tol) for a, b in zip(g, e)):
                del rest[i]
                break
        else:
            raise AssertionError(f"対応する期待が無い: {g}")


def seg_set(segs):
    """線分（端点の順は問わない）の重複を除いた集合。端点は 0.01 mm で丸めて辞書順に揃える。"""
    out = []
    for x1, y1, x2, y2 in segs:
        a, b = sorted([(round(x1, 2), round(y1, 2)), (round(x2, 2), round(y2, 2))])
        out.append((a[0], a[1], b[0], b[1]))
    ded = []
    for s in out:
        if not any(all(near(p, q) for p, q in zip(s, d)) for d in ded):
            ded.append(s)
    return ded


def marks_of(lay):
    return [(m["x1"], m["y1"], m["x2"], m["y2"]) for m in lay["marks"]]


def rect_of(s):
    return (s["x"], s["y"], s["w"], s["h"])


def mirror(lay, paper=(210, 297)):
    """(x→W−x, y→H−y) に写した marks と slots 矩形。"""
    W, H = paper
    mk_ = [(W - x1, H - y1, W - x2, H - y2) for x1, y1, x2, y2 in marks_of(lay)]
    rc = [(W - s["x"] - s["w"], H - s["y"] - s["h"], s["w"], s["h"]) for s in lay["slots"]]
    return mk_, rc


def same_segset(a, b):
    sa, sb = seg_set(a), seg_set(b)
    assert len(sa) == len(sb), (len(sa), len(sb))
    for s in sa:
        assert any(all(near(p, q) for p, q in zip(s, d)) for d in sb), s


# ================================================================ N 正常系
def test_N01_no_config_file_is_center_center(mk, capsys):
    e = mk(None, "J3")
    assert not (e.home.root / "config.json").exists()
    c = get_preset_data(e.c)
    assert c["layout"]["align_x"] == "center" and c["layout"]["align_y"] == "center"
    # 続けて config.json に print.timing=duplicate だけを書く（intake は fixture 用の環境値）
    (e.home.root / "config.json").write_text(json.dumps(
        {"intake": {"stable_wait_s": 0, "expected_dpi": 600}, "print": {"timing": "duplicate"}}))
    e.c = TestClient(create_app(e.home))
    code, out = ing(e, capsys)
    assert code == 0
    (lay,) = layouts(e)
    slot_ok(lay, 14, 11)
    check_slots(lay, {1: (14, 11), 2: (105, 11), 3: (14, 66), 10: (105, 231)})
    inside(lay)


def test_N02_explicit_center_same_as_N01(mk, capsys):
    e1 = mk(None, "J3")
    (e1.home.root / "config.json").write_text(json.dumps(
        {"intake": {"stable_wait_s": 0, "expected_dpi": 600}, "print": {"timing": "duplicate"}}))
    e1.c = TestClient(create_app(e1.home))
    assert ing(e1, capsys)[0] == 0
    (l1,) = layouts(e1)
    _, (l2,) = go(mk, capsys, cfg("center", "center"))
    s1 = sorted(l1["slots"], key=lambda s: s["index"])
    s2 = sorted(l2["slots"], key=lambda s: s["index"])
    assert len(s1) == len(s2) == 10
    for a, b in zip(s1, s2):
        assert all(near(a[k], b[k]) for k in ("x", "y", "w", "h")) and Path(a["card"]).name == Path(b["card"]).name
    slot_ok(l2, 14, 11)


def test_N03_no_align_keys_in_layout_section_is_center(mk, capsys):
    raw = {"intake": {"stable_wait_s": 0, "expected_dpi": 600},
           "layout": {"paper_width_mm": 210, "paper_height_mm": 297, "gap_x_mm": 0, "gap_y_mm": 0},
           "print": {"timing": "duplicate"}}
    e = mk(raw, "J3")
    code, out = ing(e, capsys)
    assert code == 0
    (lay,) = layouts(e)
    slot_ok(lay, 14, 11)
    c = get_preset_data(e.c)
    assert c["layout"]["align_x"] == "center" and c["layout"]["align_y"] == "center"


POS10 = [
    ("N-04", "left", "top", 0, 0, {1: (0, 0), 2: (91, 0), 3: (0, 55), 10: (91, 220)}),
    ("N-05", "center", "top", 14, 4.2, {1: (14, 4.2), 2: (105, 4.2), 3: (14, 59.2), 10: (105, 224.2)}),
    ("N-06", "right", "top", 23.8, 4.2, {1: (23.8, 4.2), 2: (114.8, 4.2), 3: (23.8, 59.2), 10: (114.8, 224.2)}),
    ("N-07", "left", "center", 4.2, 11, {1: (4.2, 11), 2: (95.2, 11), 3: (4.2, 66), 10: (95.2, 231)}),
    ("N-08", "right", "center", 23.8, 11, {1: (23.8, 11), 2: (114.8, 11), 3: (23.8, 66), 10: (114.8, 231)}),
    ("N-09", "left", "bottom", 4.2, 17.8, {1: (4.2, 17.8), 2: (95.2, 17.8), 3: (4.2, 72.8), 10: (95.2, 237.8)}),
    ("N-10", "center", "bottom", 14, 17.8, {1: (14, 17.8), 2: (105, 17.8), 3: (14, 72.8), 10: (105, 237.8)}),
    ("N-11", "right", "bottom", 23.8, 17.8, {1: (23.8, 17.8), 2: (114.8, 17.8), 3: (23.8, 72.8), 10: (114.8, 237.8)}),
]


@pytest.mark.parametrize("tc,ax,ay,X0,Y0,pts", POS10, ids=[p[0] for p in POS10])
def test_N04_to_N11_nine_positions(mk, tc, ax, ay, X0, Y0, pts):
    # 配置を比べるため、9通りとも同じ3種類・10枠を同じ順で指定する。
    e = mk(cfgS(ax, ay), "J3")
    assert e.c.post("/api/ingest").status_code == 200
    cards = e.q("SELECT image_path FROM cards ORDER BY idx")
    assert len(cards) == 3
    files = [str(e.abspdf(cards[i - 1]["image_path"])) for i in DUP10]
    pdf = e.home.root / "ten.pdf"
    assert main(["impose", *files, "--out", str(pdf), "--home", str(e.home.root)]) == 0
    lay = json.loads(pdf.with_name(pdf.name + ".layout.json").read_text())
    slot_ok(lay, X0, Y0)
    check_slots(lay, pts)
    if tc == "N-04":
        assert [Path(s["card"]).name for s in sorted(lay["slots"], key=lambda s: s["index"])] == \
            [f"{i:02d}.png" for i in DUP10]
        inside(lay, corner=True)
    if tc == "N-06":
        assert near(by_index(lay)[2]["x"] + 91, 205.8)
    if tc == "N-11":
        s10 = by_index(lay)[10]
        assert near(s10["x"] + 91, 205.8) and near(s10["y"] + 55, 292.8)


def test_N12_three_cards_right_bottom(mk, capsys):
    _, (lay,) = go(mk, capsys, cfgS("right", "bottom"))
    slot_ok(lay, 23.8, 182.8, n=3, order=[1, 2, 3])
    check_slots(lay, {1: (23.8, 182.8), 2: (114.8, 182.8), 3: (23.8, 237.8)})
    d = by_index(lay)
    assert near(d[2]["x"] + 91, 205.8) and near(d[3]["y"] + 55, 292.8)


def test_N13_one_card_left_top(mk, capsys):
    _, (lay,) = go(mk, capsys, cfgS("left", "top"), "J1")
    check_slots(lay, {1: (0, 0)}, n=1)


def test_N14_one_card_right_bottom(mk, capsys):
    _, (lay,) = go(mk, capsys, cfgS("right", "bottom"), "J1")
    check_slots(lay, {1: (114.8, 237.8)}, n=1)
    s = by_index(lay)[1]
    assert near(s["x"] + 91, 205.8) and near(s["y"] + 55, 292.8)


def test_N15_cards_per_sheet_4_right_bottom(mk, capsys):
    _, (lay,) = go(mk, capsys, cfg("right", "bottom", layout={"cards_per_sheet": 4}))
    check_slots(lay, {1: (23.8, 182.8), 2: (114.8, 182.8), 3: (23.8, 237.8), 4: (114.8, 237.8)}, n=4)


def test_N16_fill_left_bottom_n3(mk, capsys):
    e, L = go(mk, capsys, cfg("left", "bottom", timing="fill", layout={"cards_per_sheet": 3}))
    assert len(L) == 1
    check_slots(L[0], {1: (4.2, 182.8), 2: (95.2, 182.8), 3: (4.2, 237.8)}, n=3)


def test_N17_duplicate_count_4_right_top(mk, capsys):
    _, (lay,) = go(mk, capsys, cfg("right", "top", print_={"duplicate_count": 4}), "J1")
    check_slots(lay, {1: (23.8, 4.2), 2: (114.8, 4.2), 3: (23.8, 59.2), 4: (114.8, 59.2)}, n=4)
    assert card_order(lay) == [1, 1, 1, 1]


GAP = {"gap_x_mm": 2, "gap_y_mm": 15}


def test_N18_gap_grid_right_bottom(mk, capsys):
    e, (lay,) = go(mk, capsys, cfg("right", "bottom", layout=GAP))
    assert cli_json(e, capsys, "capacity") == {"capacity": 8, "columns": 2, "rows": 4, "card_rotated": False}
    slot_ok(lay, 21.8, 27.8, n=8, gx=2, gy=15, order=None)
    check_slots(lay, {1: (21.8, 27.8), 2: (114.8, 27.8), 3: (21.8, 97.8), 8: (114.8, 237.8)})
    assert same_vals([s["x"] for s in lay["slots"]], [21.8, 114.8])
    assert same_vals([s["y"] for s in lay["slots"]], [27.8, 97.8, 167.8, 237.8])
    s8 = by_index(lay)[8]
    assert near(s8["x"] + 91, 205.8) and near(s8["y"] + 55, 292.8)


def test_N19_gap_grid_left_top(mk, capsys):
    _, (lay,) = go(mk, capsys, cfg("left", "top", layout=GAP))
    slot_ok(lay, 0, 0, n=8, gx=2, gy=15, order=None)
    check_slots(lay, {1: (0, 0), 2: (93, 0), 3: (0, 70), 8: (93, 210)})


def test_N20_gap_grid_center(mk, capsys):
    _, (lay,) = go(mk, capsys, cfg("center", "center", layout=GAP))
    slot_ok(lay, 13, 16, n=8, gx=2, gy=15, order=None)
    check_slots(lay, {1: (13, 16), 2: (106, 16), 3: (13, 86), 8: (106, 226)})


def test_N21_all_six_values_saved(mk, capsys):
    e = mk(None)
    for axis, v in [("align_x", "left"), ("align_x", "center"), ("align_x", "right"),
                    ("align_y", "top"), ("align_y", "center"), ("align_y", "bottom")]:
        r = putcfg(e, lambda c: c["layout"].__setitem__(axis, v))
        assert r.status_code == 200, (axis, v, r.text)
        assert get_preset_data(e.c)["layout"][axis] == v
        shown = cli_json(e, capsys, "config", "show")
        assert shown["layout"][axis] == v
        saved = get_preset_data(TestClient(create_app(e.home)))
        assert saved["layout"][axis] == v and isinstance(saved["layout"][axis], str)


def test_N22_missing_keys_in_put_body_become_center(mk):
    e = mk(None)
    assert putcfg(e, lambda c: c["layout"].update(align_x="right", align_y="bottom")).status_code == 200
    assert get_preset_data(e.c)["layout"]["align_x"] == "right"

    def drop(c):
        del c["layout"]["align_x"]
        del c["layout"]["align_y"]

    r = putcfg(e, drop)
    assert r.status_code == 200, r.text
    c = get_preset_data(e.c)
    assert c["layout"]["align_x"] == "center" and c["layout"]["align_y"] == "center"


def _schema_prop(schema, sec, key):
    def deref(n):
        if "$ref" in n:
            return deref(schema["$defs"][n["$ref"].split("/")[-1]])
        if "allOf" in n and len(n["allOf"]) == 1:
            return deref(n["allOf"][0])
        return n

    raw = deref(schema["properties"][sec])["properties"][key]
    return raw, deref(raw)


def _allowed(schema, n):
    if "$ref" in n:
        return _allowed(schema, schema["$defs"][n["$ref"].split("/")[-1]])
    if "enum" in n:
        return set(n["enum"])
    if "const" in n:
        return {n["const"]}
    out = set()
    for k in ("anyOf", "oneOf", "allOf"):
        for sub in n.get(k, []):
            out |= _allowed(schema, sub)
    return out


def test_N23_schema_has_both_items(mk, capsys):
    e = mk(None)
    api = e.c.get("/api/presets/schema").json()
    cli = cli_json(e, capsys, "config", "schema")
    for schema in (api, cli):
        for key, vals in (("align_x", {"left", "center", "right"}), ("align_y", {"top", "center", "bottom"})):
            raw, res = _schema_prop(schema, "layout", key)
            assert _allowed(schema, raw) == vals or _allowed(schema, res) == vals, (key, raw)
            assert raw.get("default", res.get("default")) == "center", (key, raw)


def test_N24_impose_command_right_bottom(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PRINT_EDIT_HOME", str(tmp_path / "h"))
    O = tmp_path / "O"
    assert main(["detect", str(FX / FILES["J3"]), "--out", str(O)]) == 0
    C = tmp_path / "C.json"
    C.write_text(json.dumps(cfgS("right", "bottom")))
    cards = [str(O / "cards" / f"0{i}.png") for i in (1, 2, 3)]
    assert main(["impose", *cards, "--out", str(O / "x.pdf"), "--config", str(C)]) == 0
    lay = json.loads((O / "x.pdf.layout.json").read_text())
    check_slots(lay, {1: (23.8, 182.8), 2: (114.8, 182.8), 3: (23.8, 237.8)}, n=3)


def test_N25_approve_makes_sheet_with_align(mk, capsys):
    e = mk(cfgS("right", "bottom"), "JR1")
    code, out = ing(e, capsys)
    assert e.q("SELECT COUNT(*) AS n FROM sheets")[0]["n"] == 0
    cid = e.q("SELECT id FROM cards WHERE status='review'")[0]["id"]
    r = e.c.post(f"/api/cards/{cid}/approve")
    assert r.status_code == 200, r.text
    (lay,) = layouts(e)
    check_slots(lay, {1: (114.8, 237.8)}, n=1)


def test_N26_api_ingest_left_top(mk):
    e = mk(cfg("left", "top"), "J1")
    r = e.c.post("/api/ingest/create", json={})
    assert r.status_code == 200, r.text
    (lay,) = layouts(e)
    slot_ok(lay, 0, 0, order=[1] * 10)
    check_slots(lay, POS10[0][5])


SCALE = [
    ("N-27", "center", "center", 1.02, 1.02, 92.82, 56.1,
     {1: (12.18, 8.25), 2: (105, 8.25), 3: (12.18, 64.35), 10: (105, 232.65)}),
    ("N-28", "left", "top", 1.02, 1.02, 92.82, 56.1,
     {1: (0, 0), 2: (92.82, 0), 3: (0, 56.1), 10: (92.82, 224.4)}),
    ("N-29", "right", "bottom", 1.02, 1.02, 92.82, 56.1,
     {1: (20.16, 12.3), 2: (112.98, 12.3), 3: (20.16, 68.4), 10: (112.98, 236.7)}),
    ("N-30", "left", "center", 1.02, 1.02, 92.82, 56.1,
     {1: (4.2, 8.25), 2: (97.02, 8.25), 10: (97.02, 232.65)}),
    ("N-31", "center", "bottom", 1.02, 1.02, 92.82, 56.1,
     {1: (12.18, 12.3), 2: (105, 12.3), 10: (105, 236.7)}),
    ("N-32", "right", "top", 1.02, 1.02, 92.82, 56.1,
     {1: (20.16, 4.2), 2: (112.98, 4.2), 10: (112.98, 228.6)}),
    ("N-33", "right", "bottom", 1.02, 0.98, 92.82, 53.9,
     {1: (20.16, 23.3), 2: (112.98, 23.3), 10: (112.98, 238.9)}),
    ("B-10", "right", "bottom", 0.95, 0.95, 86.45, 52.25,
     {1: (32.9, 31.55), 2: (119.35, 31.55), 10: (119.35, 240.55)}),
    ("B-11", "right", "top", 1.05, 1.0, 95.55, 55,
     {1: (14.7, 4.2), 2: (110.25, 4.2), 10: (110.25, 224.2)}),
]


@pytest.mark.parametrize("tc,ax,ay,sx,sy,w,h,pts", SCALE, ids=[s[0] for s in SCALE])
def test_N27_to_N33_B10_B11_scale(mk, capsys, tc, ax, ay, sx, sy, w, h, pts):
    _, (lay,) = go(mk, capsys, cfg(ax, ay, print_={"scale_x": sx, "scale_y": sy}), "J1")
    check_slots(lay, pts, w=w, h=h, n=10)
    d = by_index(lay)
    if tc == "N-28":
        inside(lay, corner=True)
    if tc == "N-29":
        assert near(d[2]["x"] + w, 205.8) and near(d[10]["y"] + h, 292.8)
    if tc == "B-11":
        assert near(d[2]["x"] + w, 205.8)


def test_N34_marks_use_scaled_coordinates(mk, capsys):
    _, (lay,) = go(mk, capsys, cfg("left", "top", print_={"scale_x": 1.02, "scale_y": 1.02}), "J1")
    xs = [0, 92.82, 185.64]
    ys = [0, 56.1, 112.2, 168.3, 224.4, 280.5]
    check_slots(lay, {1: (0, 0), 2: (92.82, 0)}, w=92.82, h=56.1, n=10)
    check_marks(lay, left=None, top=None, right=M(ys, 186.66, 189.72), bottom=M(xs, 281.52, 284.58), corner=True)
    # スロットの x・y 境界（列・行の境界）
    sl = lay["slots"]
    assert same_vals([s["x"] for s in sl] + [s["x"] + s["w"] for s in sl], xs)
    assert same_vals([s["y"] for s in sl] + [s["y"] + s["h"] for s in sl], ys)


Y6_C = [11, 66, 121, 176, 231, 286]
Y6_T = [4.2, 59.2, 114.2, 169.2, 224.2, 279.2]
Y6_B = [17.8, 72.8, 127.8, 182.8, 237.8, 292.8]
X3_C = [14, 105, 196]
X3_L = [4.2, 95.2, 186.2]
X3_R = [23.8, 114.8, 205.8]

MARK10 = [
    ("N-35", "center", "center", dict(left=M(Y6_C, 10, 13), right=M(Y6_C, 197, 200),
                                      top=M(X3_C, 7, 10), bottom=M(X3_C, 287, 290))),
    ("N-36", "left", "center", dict(left=None, right=M(Y6_C, 187.2, 190.2),
                                    top=M(X3_L, 7, 10), bottom=M(X3_L, 287, 290))),
    ("N-37", "right", "center", dict(left=M(Y6_C, 19.8, 22.8), right=None,
                                     top=M(X3_R, 7, 10), bottom=M(X3_R, 287, 290))),
    ("N-38", "center", "top", dict(left=M(Y6_T, 10, 13), right=M(Y6_T, 197, 200),
                                   top=None, bottom=M(X3_C, 280.2, 283.2))),
    ("N-39", "center", "bottom", dict(left=M(Y6_B, 10, 13), right=M(Y6_B, 197, 200),
                                      top=M(X3_C, 13.8, 16.8), bottom=None)),
    ("N-40", "left", "top", dict(left=None, right=M([0, 55, 110, 165, 220, 275], 183, 186),
                                 top=None, bottom=M([0, 91, 182], 276, 279), corner=True)),
    ("N-41", "right", "top", dict(left=M(Y6_T, 19.8, 22.8), right=None,
                                  top=None, bottom=M(X3_R, 280.2, 283.2))),
    ("N-42", "left", "bottom", dict(left=None, right=M(Y6_B, 187.2, 190.2),
                                    top=M(X3_L, 13.8, 16.8), bottom=None)),
    ("N-43", "right", "bottom", dict(left=M(Y6_B, 19.8, 22.8), right=None,
                                     top=M(X3_R, 13.8, 16.8), bottom=None)),
]


@pytest.mark.parametrize("tc,ax,ay,exp", MARK10, ids=[m[0] for m in MARK10])
def test_N35_to_N43_marks_by_side(mk, capsys, tc, ax, ay, exp):
    _, (lay,) = go(mk, capsys, cfg(ax, ay), "J1")
    check_marks(lay, **exp)


@pytest.mark.parametrize("tc,a,b", [("N-44", ("left", "top"), ("right", "bottom")),
                                    ("N-45", ("right", "top"), ("left", "bottom"))],
                         ids=["N-44", "N-45"])
def test_N44_N45_symmetry(mk, capsys, tc, a, b):
    _, (la,) = go(mk, capsys, cfg(*a))
    _, (lb,) = go(mk, capsys, cfg(*b))
    mk_b, rc_b = mirror(lb)
    same_segset(marks_of(la), mk_b)
    match_all([rect_of(s) for s in la["slots"]], rc_b)


def test_N46_capacity_same_for_nine_alignments(mk, capsys):
    prev_prev = None
    for ax, ay in NINE:
        e = mk(cfg(ax, ay))
        assert cli_json(e, capsys, "capacity") == CAP10, (ax, ay)
        r = e.c.get("/api/capacity")
        assert r.status_code == 200 and r.json() == CAP10, (ax, ay)
        r = e.c.get("/api/layout/preview")
        assert r.status_code == 200, r.text
        p = r.json()
        got = (p["capacity"], p["columns"], p["rows"])
        assert got == (10, 2, 5), (ax, ay, got)
        if prev_prev is not None:
            assert got == prev_prev
        prev_prev = got


def test_N47_layout_json_capacity_and_paper_same_for_nine(mk, capsys):
    for ax, ay in NINE:
        _, (lay,) = go(mk, capsys, cfg(ax, ay))
        assert lay["capacity"] == 10 and lay["columns"] == 2 and lay["rows"] == 5 and lay["card_rotated"] is False
        assert all(near(a, b) for a, b in zip(lay["paper_mm"], [210, 297])), (ax, ay)
        assert all(near(a, b) for a, b in zip(lay["printable_mm"], [4.2, 4.2, 201.6, 288.6])), (ax, ay)


@pytest.mark.parametrize("ax,ay", [("left", "top"), ("center", "center"), ("right", "bottom")],
                         ids=["N-48-lt", "N-48-cc", "N-48-rb"])
def test_N48_gap_capacity_same(mk, capsys, ax, ay):
    e, (lay,) = go(mk, capsys, cfg(ax, ay, layout=GAP))
    want = {"capacity": 8, "columns": 2, "rows": 4, "card_rotated": False}
    assert cli_json(e, capsys, "capacity") == want
    assert {k: lay[k] for k in want} == want


@pytest.mark.parametrize("ax,ay", [("left", "top"), ("center", "center"), ("right", "bottom")],
                         ids=["N-49-lt", "N-49-cc", "N-49-rb"])
def test_N49_pdf_images_match_slots(mk, capsys, ax, ay):
    e, (lay,) = go(mk, capsys, cfg(ax, ay))
    (pdf,) = pdfs(e)
    w, h = pdf_page_pt(pdf)
    assert abs(w * PT - 210) <= 0.1 and abs(h * PT - 297) <= 0.1, (w, h)
    assert abs(w - 595.28) <= 0.3 and abs(h - 841.89) <= 0.3
    rects, _ = pdf_items(pdf)
    assert len(rects) == 10
    match_all(rects, [rect_of(s) for s in lay["slots"]])


def test_N50_pdf_matches_layout_with_scale(mk, capsys):
    e, (lay,) = go(mk, capsys, cfg("right", "bottom", print_={"scale_x": 1.02, "scale_y": 0.98}))
    check_slots(lay, {1: (20.16, 23.3), 2: (112.98, 23.3), 10: (112.98, 238.9)}, w=92.82, h=53.9, n=10)
    (pdf,) = pdfs(e)
    rects, _ = pdf_items(pdf)
    assert len(rects) == 10
    match_all(rects, [rect_of(s) for s in lay["slots"]])


@pytest.mark.parametrize("ax,ay", [("left", "top"), ("right", "bottom")], ids=["N-51-lt", "N-51-rb"])
def test_N51_pdf_lines_match_marks(mk, capsys, ax, ay):
    e, (lay,) = go(mk, capsys, cfg(ax, ay, layout={"mark_style": "solid"}))
    (pdf,) = pdfs(e)
    _, lines = pdf_items(pdf)
    same_segset(lines, marks_of(lay))
    box = box_of(lay)
    absent = {"left" if ax == "left" else "right", "top" if ay == "top" else "bottom"}
    kinds = {classify({"x1": a, "y1": b, "x2": c, "y2": d}, box) for a, b, c, d in lines}
    assert None not in kinds and not (kinds & absent), (kinds, absent)


def test_N52_sheet_image_marks_dark_and_edge_white(mk, capsys):
    e, (lay,) = go(mk, capsys, cfg("left", "top"))
    sid = sheet_rows(e)[0]["id"]
    r = e.c.get(f"/api/sheets/{sid}/image.png")
    assert r.status_code == 200, r.text
    im = Image.open(io.BytesIO(r.content)).convert("L")
    W, H = im.size
    assert abs(W - 2480) <= 1 and abs(H - 3508) <= 1, im.size
    a = np.array(im)
    k = 300 / 25.4

    def dark_near(x1, y1, x2, y2):
        n = int(max(abs(x2 - x1), abs(y2 - y1)) * k) + 1
        best = 255
        for i in range(n + 1):
            x = (x1 + (x2 - x1) * i / n) * k
            y = (y1 + (y2 - y1) * i / n) * k
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    xi, yi = int(round(x)) + dx, int(round(y)) + dy
                    if 0 <= xi < W and 0 <= yi < H:
                        best = min(best, int(a[yi, xi]))
        return best

    assert dark_near(187.2, 59.2, 190.2, 59.2) < 200
    assert dark_near(95.2, 280.2, 95.2, 283.2) < 200
    band = slice(int(round(0.2 * k)), int(round(3.2 * k)) + 1)
    assert a[:, band].min() >= 200
    assert a[band, :].min() >= 200


def test_N53_reprint_keeps_saved_pdf(mk, lp, capsys):
    e = mk(cfg("center", "center", print_={"output": "lp", "printer_name": "Q1"}), "J3")
    code, out = ing(e, capsys)
    assert code == 0 and len(out) == 1
    jid = out[0]["job_id"]
    (pdf,) = pdfs(e)
    h0, lay0 = sha(pdf), lay_of(pdf)
    assert putcfg(e, lambda c: c["layout"].update(align_x="right", align_y="bottom")).status_code == 200
    lp.clear()
    r = e.c.post(f"/api/jobs/{jid}/reprint")
    assert r.status_code == 200, r.text
    assert r.json()["output"] == "lp"
    assert len(lp.calls()) == 1
    assert sha(pdf) == h0 and lay_of(pdf) == lay0
    check_slots(lay_of(pdf), {1: (14, 11)})
    # ② 取り込み直し（D-J1）で新しい寄せ先が反映される
    feed(e, "J1")
    code, out2 = ing(e, capsys)
    assert code == 0 and len(out2) == 1
    p2 = e.abspdf(e.q("SELECT pdf_path FROM sheets WHERE job_id=?", out2[0]["job_id"])[0]["pdf_path"])
    check_slots(lay_of(p2), {1: (23.8, 17.8)}, n=10)


def test_N54_lp_args_and_states_right_bottom(mk, lp, capsys):
    res = {}
    for name, (ax, ay) in (("rb", ("right", "bottom")), ("cc", ("center", "center"))):
        e = mk(cfg(ax, ay, print_={"output": "lp", "printer_name": "Q1", "auto_print": True}), "J3")
        lp.clear()
        code, out = ing(e, capsys)
        assert code == 0
        calls = lp.calls()
        assert len(calls) == 1, calls
        a = calls[0].split()
        assert a[:4] == ["-d", "Q1", "-n", "1"], a
        want = e.home.root / "jobs" / out[0]["job_id"] / "sheets" / "01.pdf"
        assert os.path.realpath(a[-1]) == os.path.realpath(str(want)), (a[-1], want)
        assert [r["status"] for r in e.q("SELECT status FROM sheets")] == ["sent"]
        st = [r["status"] for r in e.q("SELECT status FROM cards")]
        assert len(st) == 3 and set(st) == {"printed"}
        res[name] = (a[:4], [r["status"] for r in e.q("SELECT status FROM sheets")], st)
    assert res["rb"] == res["cc"]


def test_N55_one_card_marks_right_bottom(mk, capsys):
    _, (lay,) = go(mk, capsys, cfgS("right", "bottom"), "J1")
    check_slots(lay, {1: (114.8, 237.8)}, n=1)
    check_marks(lay, left=M([237.8, 292.8], 110.8, 113.8), right=None,
                top=M([114.8, 205.8], 233.8, 236.8), bottom=None)


def test_N56_one_card_marks_left_top(mk, capsys):
    _, (lay,) = go(mk, capsys, cfgS("left", "top"), "J1")
    check_slots(lay, {1: (0, 0)}, n=1)
    check_marks(lay, left=None, right=M([0, 55], 92, 95),
                top=None, bottom=M([0, 91], 56, 59), corner=True)


def test_N57_one_card_marks_center(mk, capsys):
    _, (lay,) = go(mk, capsys, cfgS("center", "center"), "J1")
    check_slots(lay, {1: (14, 11)}, n=1)
    check_marks(lay, left=M([11, 66], 10, 13), right=M(None, 106, 109),
                top=M([14, 105], 7, 10), bottom=M(None, 67, 70))


def test_N58_gap_few_cards_right_bottom(mk, capsys):
    _, (lay,) = go(mk, capsys, cfg("right", "bottom", layout={**GAP, "cards_per_sheet": 3}))
    slot_ok(lay, 21.8, 167.8, n=3, gx=2, gy=15, order=None)
    check_slots(lay, {1: (21.8, 167.8), 2: (114.8, 167.8), 3: (21.8, 237.8)}, n=3)
    assert near(by_index(lay)[3]["y"] + 55, 292.8)


# ================================================================ E 異常系
def _put_bad(e, mutate):
    before = cfgsnap(e)
    # 前提: 既定の全体に両項目がある（キー自体が無いための 422 を、値の検査の 422 と取り違えない）
    assert before[1]["layout"].get("align_x") == "center" and before[1]["layout"].get("align_y") == "center"
    r = putcfg(e, mutate)
    assert r.status_code == 422, (r.status_code, r.text)
    assert cfgsnap(e) == before
    return r


def _setter(axis, v):
    return lambda c: c["layout"].__setitem__(axis, v)


def test_E01_align_x_vertical_value(mk):
    e = mk(None)
    _put_bad(e, _setter("align_x", "top"))
    assert not (e.home.root / "config.json").exists()


def test_E02_align_y_horizontal_value(mk):
    e = mk(None)
    _put_bad(e, _setter("align_y", "left"))
    assert not (e.home.root / "config.json").exists()


def test_E03_case_differences_rejected(mk):
    e = mk(None)
    for axis, v in (("align_x", "Left"), ("align_x", "RIGHT"), ("align_y", "Top")):
        _put_bad(e, _setter(axis, v))


def test_E04_empty_string_rejected(mk):
    e = mk(None)
    for axis in ("align_x", "align_y"):
        _put_bad(e, _setter(axis, ""))


def test_E05_null_rejected(mk):
    e = mk(None)
    for axis in ("align_x", "align_y"):
        _put_bad(e, _setter(axis, None))


def test_E06_number_and_bool_rejected(mk):
    e = mk(None)
    _put_bad(e, _setter("align_x", 1))
    _put_bad(e, _setter("align_y", True))


def test_E07_one_bad_axis_saves_nothing(mk):
    e = mk(None)
    assert get_preset_data(e.c)["layout"].get("align_x") == "center"
    r = putcfg(e, lambda c: c["layout"].update(align_x="right", align_y="middle"))
    assert r.status_code == 422, r.text
    assert get_preset_data(e.c)["layout"]["align_x"] == "center"
    assert not (e.home.root / "config.json").exists()


def test_E08_saved_values_remain_after_422(mk):
    e = mk(None)
    assert putcfg(e, lambda c: c["layout"].update(align_x="right", align_y="bottom")).status_code == 200
    before = cfgsnap(e)
    r = putcfg(e, _setter("align_x", "up"))
    assert r.status_code == 422, r.text
    c = get_preset_data(e.c)
    assert c["layout"]["align_x"] == "right" and c["layout"]["align_y"] == "bottom"
    assert cfgsnap(e) == before


def _capacity_cli(e):
    exe = Path(sys.executable).parent / "print-edit"
    env = {**os.environ, "PRINT_EDIT_HOME": str(e.home.root)}
    return subprocess.run([str(exe), "capacity", "--home", str(e.home.root)], capture_output=True, text=True,
                          env=env, timeout=120)


def test_E09_hand_written_bad_value_fails_capacity(mk):
    e = mk(None)
    (e.home.root / "config.json").write_text(json.dumps({"layout": {"align_x": "up"}}))
    p = _capacity_cli(e)
    assert p.returncode != 0 and p.stderr.strip() != "", (p.returncode, p.stderr)
    (e.home.root / "config.json").write_text(json.dumps({"layout": {"align_x": "left"}}))
    p = _capacity_cli(e)
    assert p.returncode == 0, (p.returncode, p.stderr)
    out = json.loads(p.stdout)
    assert out["capacity"] == 10 and out["columns"] == 2 and out["rows"] == 5


def test_E10_lp_failure_keeps_error_states_right_bottom(mk, lp, capsys):
    e = mk(cfg("right", "bottom", print_={"output": "lp", "printer_name": "Q1", "auto_print": True}), "J3")
    lp.plan(1)
    lp.clear()
    code, out = ing(e, capsys)
    assert code != 0
    calls = lp.calls()
    assert len(calls) == 1, calls
    a = calls[0].split()
    assert a[:4] == ["-d", "Q1", "-n", "1"], a
    jid = out[0]["job_id"]
    want = e.home.root / "jobs" / jid / "sheets" / "01.pdf"
    assert os.path.realpath(a[-1]) == os.path.realpath(str(want))
    assert [r["status"] for r in e.q("SELECT status FROM sheets")] == ["error"]
    job = e.q("SELECT status, error FROM jobs WHERE id=?", jid)[0]
    assert job["status"] == "error" and job["error"]
    st = [r["status"] for r in e.q("SELECT status FROM cards")]
    assert len(st) == 3 and "printed" not in st


# ================================================================ B 境界値
U0 = {"unprintable_mm": 0}


def test_B01_unprintable_0_left_top(mk, capsys):
    e, (lay,) = go(mk, capsys, cfg("left", "top", device=U0))
    assert cli_json(e, capsys, "capacity") == CAP10
    assert all(near(a, b) for a, b in zip(lay["printable_mm"], [0, 0, 210, 297]))
    slot_ok(lay, 0, 0)
    check_slots(lay, {1: (0, 0), 2: (91, 0), 3: (0, 55), 10: (91, 220)})


def test_B02_unprintable_0_right_bottom(mk, capsys):
    _, (lay,) = go(mk, capsys, cfg("right", "bottom", device=U0))
    slot_ok(lay, 28, 22)
    check_slots(lay, {1: (28, 22), 2: (119, 22), 10: (119, 242)})
    s = by_index(lay)[10]
    assert near(s["x"] + 91, 210) and near(s["y"] + 55, 297)


def test_B03_unprintable_0_center(mk, capsys):
    _, (lay,) = go(mk, capsys, cfg("center", "center", device=U0))
    slot_ok(lay, 14, 11)
    check_slots(lay, {1: (14, 11), 10: (105, 231)})


B04 = [("center", "top", (14, 0), (105, 220)), ("right", "top", (28, 0), (119, 220)),
       ("left", "center", (0, 11), (91, 231)), ("right", "center", (28, 11), (119, 231)),
       ("left", "bottom", (0, 22), (91, 242)), ("center", "bottom", (14, 22), (105, 242))]


@pytest.mark.parametrize("ax,ay,s1,s10", B04, ids=[f"B-04-{a}-{b}" for a, b, _, _ in B04])
def test_B04_unprintable_0_other_six(mk, capsys, ax, ay, s1, s10):
    _, (lay,) = go(mk, capsys, cfg(ax, ay, device=U0))
    slot_ok(lay, s1[0], s1[1])
    check_slots(lay, {1: s1, 10: s10})


def test_B05_unprintable_0_marks(mk, capsys):
    _, (lay,) = go(mk, capsys, cfg("left", "top", device=U0))
    check_marks(lay, left=None, top=None, right=M(ys_n10(0), 183, 186),
                bottom=M([0, 91, 182], 276, 279), u=0)
    _, (lay,) = go(mk, capsys, cfg("right", "bottom", device=U0))
    check_marks(lay, right=None, bottom=None, left=M([22, 77, 132, 187, 242, 297], 24, 27),
                top=M([28, 119, 210], 18, 21), u=0)


@pytest.mark.parametrize("ax,ay,s1,s2,s10", [
    ("left", "top", (0, 0), (91, 0), (91, 220)),
    ("right", "bottom", (18, 12), (109, 12), (109, 232))], ids=["B-06-lt", "B-06-rb"])
def test_B06_unprintable_10(mk, capsys, ax, ay, s1, s2, s10):
    e, (lay,) = go(mk, capsys, cfg(ax, ay, device={"unprintable_mm": 10}), "J1")
    assert all(near(a, b) for a, b in zip(lay["printable_mm"], [10, 10, 190, 277]))
    assert lay["capacity"] == 10
    check_slots(lay, {1: s1, 2: s2, 10: s10}, n=10)
    if ax == "right":
        s = by_index(lay)[10]
        assert near(s["x"] + 91, 200) and near(s["y"] + 55, 287)


@pytest.mark.parametrize("ax,ay", NINE, ids=[f"B-07-{a}-{b}" for a, b in NINE])
def test_B07_grid_exactly_fits_width(mk, capsys, ax, ay):
    e, (lay,) = go(mk, capsys, cfg(ax, ay, layout={"paper_width_mm": 182, "paper_height_mm": 297},
                                   device=U0))
    assert lay["capacity"] == 10
    assert same_vals([s["x"] for s in lay["slots"]], [0, 91]), ax
    assert near(by_index(lay)[1]["y"], {"top": 0, "center": 11, "bottom": 22}[ay])
    (pdf,) = pdfs(e)
    w, h = pdf_page_pt(pdf)
    assert abs(w * PT - 182) <= 0.1 and abs(w - 515.91) <= 0.3 and abs(h * PT - 297) <= 0.1


def test_B08_multiple_sheets_same_position(mk, capsys):
    e, L = go(mk, capsys, cfg("right", "bottom", print_={"duplicate_count": 10}))
    assert len(L) == 3
    for lay in L:
        check_slots(lay, {1: (23.8, 17.8), 10: (114.8, 237.8)}, n=10)


def test_B09_long_mark_clipped_at_printable_edge(mk, capsys):
    _, (lay,) = go(mk, capsys, cfg("center", "center", layout={"mark_length_mm": 20}))
    check_marks(lay, left=M(Y6_C, 4.2, 13), right=M(Y6_C, 197, 205.8),
                top=M(X3_C, 4.2, 10), bottom=M(X3_C, 287, 292.8))


@pytest.mark.parametrize("tc,lay_over,right_x,bottom_y", [
    ("B-14-1", {"mark_length_mm": 20}, (183, 203), (276, 292.8)),
    ("B-14-2", {"mark_offset_mm": 0}, (182, 185), (275, 278)),
    ("B-14-3", {"mark_offset_mm": 10}, (192, 195), (285, 288))], ids=["B-14-1", "B-14-2", "B-14-3"])
def test_B14_aligned_side_marks_never_drawn(mk, capsys, tc, lay_over, right_x, bottom_y):
    _, (lay,) = go(mk, capsys, cfg("left", "top", layout=lay_over), "J1")
    check_marks(lay, left=None, top=None, right=M(ys_n10(0), *right_x), bottom=M([0, 91, 182], *bottom_y), corner=True)


def test_B12_capacity_one_paper(mk, capsys):
    caps = []
    want = {"center_center": (4.5, 7.5), "left_top": (0, 0), "right_bottom": (4.8, 10.8)}
    for ax, ay in (("left", "top"), ("center", "center"), ("right", "bottom")):
        e, (lay,) = go(mk, capsys, cfgS(ax, ay, layout={"paper_width_mm": 100, "paper_height_mm": 70}), "J1")
        c = cli_json(e, capsys, "capacity")
        assert (c["capacity"], c["columns"], c["rows"]) == (1, 1, 1)
        caps.append(c)
        check_slots(lay, {1: want[f"{ax}_{ay}"]}, n=1)
        assert lay["capacity"] == 1 and lay["columns"] == 1 and lay["rows"] == 1
    assert caps[0] == caps[1] == caps[2]


def test_B13_only_align_x_key(mk, capsys):
    raw = {"intake": {"stable_wait_s": 0, "expected_dpi": 600}, "layout": {"align_x": "right"},
           "print": {"timing": "duplicate"}}
    e = mk(raw, "J3")
    code, out = ing(e, capsys)
    assert code == 0
    c = get_preset_data(e.c)
    assert c["layout"]["align_x"] == "right" and c["layout"]["align_y"] == "center"
    (lay,) = layouts(e)
    slot_ok(lay, 23.8, 11)
    check_slots(lay, {1: (23.8, 11), 2: (114.8, 11), 3: (23.8, 66), 10: (114.8, 231)})


def test_B15_large_scale_keeps_current_behavior(mk, capsys):
    cases = [
        ("center", "center", 1.05, 1.05, 95.55, 57.75, {1: (9.45, 4.125), 10: (105, 235.125)}),
        ("right", "bottom", 1.0, 1.05, 91, 57.75, {1: (23.8, 4.05), 10: (114.8, 235.05)}),
    ]
    for ax, ay, sx, sy, w, h, pts in cases:
        # このケースは満杯のシートの倍率と座標を調べる。1名刺で全10枠を使う。
        e = mk(cfg(ax, ay, print_={"scale_x": sx, "scale_y": sy}), "J1")
        code, out = ing(e, capsys)
        assert code == 0
        (lay,) = layouts(e)
        check_slots(lay, pts, w=w, h=h, n=10)
        mark_common(lay)


B16 = {
    ("left", "top"): (0, 0), ("center", "top"): (14, 4.2), ("right", "top"): (114.8, 4.2),
    ("left", "center"): (4.2, 11), ("center", "center"): (14, 11), ("right", "center"): (114.8, 11),
    ("left", "bottom"): (4.2, 237.8), ("center", "bottom"): (14, 237.8), ("right", "bottom"): (114.8, 237.8),
}


@pytest.mark.parametrize("ax,ay", NINE, ids=[f"B-16-{a}-{b}" for a, b in NINE])
def test_B16_one_card_nine(mk, capsys, ax, ay):
    _, (lay,) = go(mk, capsys, cfgS(ax, ay), "J1")
    check_slots(lay, {1: B16[(ax, ay)]}, n=1)


B17 = {
    ("left", "top"): [(0, 0), (91, 0), (0, 55)],
    ("center", "top"): [(14, 4.2), (105, 4.2), (14, 59.2)],
    ("right", "top"): [(23.8, 4.2), (114.8, 4.2), (23.8, 59.2)],
    ("left", "center"): [(4.2, 11), (95.2, 11), (4.2, 66)],
    ("center", "center"): [(14, 11), (105, 11), (14, 66)],
    ("right", "center"): [(23.8, 11), (114.8, 11), (23.8, 66)],
    ("left", "bottom"): [(4.2, 182.8), (95.2, 182.8), (4.2, 237.8)],
    ("center", "bottom"): [(14, 182.8), (105, 182.8), (14, 237.8)],
    ("right", "bottom"): [(23.8, 182.8), (114.8, 182.8), (23.8, 237.8)],
}


@pytest.mark.parametrize("ax,ay", NINE, ids=[f"B-17-{a}-{b}" for a, b in NINE])
def test_B17_three_cards_nine(mk, capsys, ax, ay):
    _, (lay,) = go(mk, capsys, cfgS(ax, ay))
    check_slots(lay, dict(enumerate(B17[(ax, ay)], 1)), n=3)
    if ay == "bottom":  # n=10 の同じ寄せ先（y=17.8/72.8）とは同一でない
        assert not near(by_index(lay)[1]["y"], 17.8)


@pytest.mark.parametrize("ax,exp", [("right", [(23.8, 237.8), (114.8, 237.8)]),
                                    ("left", [(4.2, 237.8), (95.2, 237.8)])], ids=["B-18-rb", "B-18-lb"])
def test_B18_two_cards_one_row(mk, capsys, ax, exp):
    e, L = go(mk, capsys, cfg(ax, "bottom", layout={"cards_per_sheet": 2}))
    lay = L[0]
    check_slots(lay, dict(enumerate(exp, 1)), n=2)
    assert card_order(lay) == [1, 2]
    s2 = by_index(lay)[2]
    assert near(s2["y"] + 55, 292.8)


def test_B19_five_cards(mk, capsys):
    _, (lay,) = go(mk, capsys, cfg("right", "bottom", layout={"cards_per_sheet": 5}))
    check_slots(lay, {1: (23.8, 127.8), 2: (114.8, 127.8), 3: (23.8, 182.8), 4: (114.8, 182.8),
                      5: (23.8, 237.8)}, n=5)
    assert card_order(lay) == [1, 2, 3, 1, 2]
    _, (lay,) = go(mk, capsys, cfg("left", "top", layout={"cards_per_sheet": 5}))
    check_slots(lay, {1: (0, 0), 5: (0, 110)}, n=5)
    assert card_order(lay) == [1, 2, 3, 1, 2]


def test_B20_reprint_after_align_change_keeps_pdf(mk, lp, capsys):
    e = mk(cfgS("right", "bottom", print_={"output": "lp", "printer_name": "Q1"}), "J1")
    lp.plan(0)
    code, out = ing(e, capsys)
    assert code == 0 and len(out) == 1
    jid = out[0]["job_id"]
    first = lp.calls()
    assert len(first) == 1
    (pdf,) = pdfs(e)
    h0, lay0 = sha(pdf), lay_of(pdf)
    check_slots(lay0, {1: (114.8, 237.8)}, n=1)
    sheets_dir = e.home.root / "jobs" / jid / "sheets"
    files0 = sorted(p.name for p in sheets_dir.iterdir())
    r = putcfg(e, lambda c: c["layout"].update(align_x="left", align_y="top"))
    assert r.status_code == 200, r.text
    lp.clear()
    r = e.c.post(f"/api/jobs/{jid}/reprint")
    assert r.status_code == 200, r.text
    calls = lp.calls()
    assert len(calls) == 1
    assert os.path.realpath(calls[0].split()[-1]) == os.path.realpath(first[0].split()[-1])
    assert sha(pdf) == h0 and lay_of(pdf) == lay0
    check_slots(lay_of(pdf), {1: (114.8, 237.8)}, n=1)
    assert sorted(p.name for p in sheets_dir.iterdir()) == files0
