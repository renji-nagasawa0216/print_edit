"""docs/spec.md 11.8b「cross と寄せ先」（周 4）の受け入れテスト。
正本: ai_docs/specs/spec_11_8c_tc.md の C-01〜C-33（目視 X-11〜13 は skip）。

期待値は TC の値のまま（実装に合わせて変えない）。
- 判定は TC に書かれた材料だけで組む: 件数（54−10px−4py 等）・「出る線／出ない線」の直書き・P 上の線 0 本・
  寄せていない側の 10 本／4 本・inward ⊂ cross・交点ごとの本数・腕の長さ。cross の期待集合を規則から自作して全件照合はしない。
- lp は実行しない: test_spec_11_3 の fake_lp（autouse）が PATH 先頭に偽 lp を置く。PRINT_EDIT_HOME は tmp_path 配下へ向ける。
- Home は毎回 tmp_path 配下の新しい空ディレクトリ。デグレの基準は `git archive <rev>` を新しい空ディレクトリへ展開して取る。
- 画面の DOM・目視が要る TC は skip を 1 TC ごとに残す（reason に TC ID と「目視/DOM」）。
"""
from __future__ import annotations

import io
import json
import subprocess
import tarfile
from collections import Counter

import pytest

from test_spec_11_3 import fake_lp, lp  # noqa: F401  (fake_lp は autouse。import が無いと効かない)
from test_spec_11_8 import (  # noqa: F401
    CR, LY, PT_1MM, PT_2MM, REPO, S10, S10X, S10XLT, S1X, S2C, S2X, S3LT, S3X, TOL,
    _base_py, _body, _layout_def, _near, assert_contains, assert_same, base_cli, base_src, cli,
    client, get_cfg, impose, imgs, inner_marks_of, inner_segs, is_horizontal, is_vertical, layout_json,
    mark_tuples, match, mg, mkhome, post_preview, preview, put_cfg, raster, read_pdf, same_image, shift,
    tuples,
)

BED_REV = "bed031a"  # 11.8b 実装時点（C-30 の基準）


@pytest.fixture(autouse=True)
def _home_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PRINT_EDIT_HOME", str(tmp_path / "env_home"))


@pytest.fixture(scope="session")
def base_bed(tmp_path_factory):
    d = tmp_path_factory.mktemp("base_bed031a")
    r = subprocess.run(["git", "archive", BED_REV], cwd=REPO, capture_output=True, check=True)
    with tarfile.open(fileobj=io.BytesIO(r.stdout)) as t:
        t.extractall(d, filter="data")
    chk = _base_py(d, "import print_edit;print(print_edit.__file__)")
    assert chk.stdout.strip().startswith(str(d)), f"基準の print_edit が展開先から読まれていない: {chk.stdout!r} {chk.stderr!r}"
    return d


# ================================================================ 共通部品（TC の写像表・共通の期待）
# TC 4「座標の導出」の写像表
XT = {"left": (4.2, 95.2, 186.2), "center": (14, 105, 196), "right": (23.8, 114.8, 205.8)}
YT = {"top": (4.2, 59.2, 114.2, 169.2, 224.2, 279.2), "center": (11, 66, 121, 176, 231, 286),
      "bottom": (17.8, 72.8, 127.8, 182.8, 237.8, 292.8)}
DX = {"left": -9.8, "center": 0, "right": 9.8}   # S10（center）→ 各寄せ先の写像（TC: x・y の写像）
DY = {"top": -6.8, "center": 0, "bottom": 6.8}
COMBOS = [(ax, ay) for ay in ("center", "top", "bottom") for ax in ("center", "left", "right")]


def AL(ax, ay, **kw):
    return mg(LY(align_x=ax, align_y=ay), CR(3, "cross", True), kw)


def AI(ax, ay):
    """inward 版（C-32・C-33）。"""
    return mg(LY(align_x=ax, align_y=ay), CR(3, "inward", True))


def vlines(got, x):
    """x1=x2=x の縦の線。"""
    return [t for t in got if is_vertical(t) and _near(t[0], x, TOL)]


def hlines(got, y):
    """y1=y2=y の横の線。"""
    return [t for t in got if is_horizontal(t) and _near(t[1], y, TOL)]


def assert_absent(got, lines, what=""):
    for ln in lines:
        missing, _ = match(got, [ln], directed=True)
        assert missing, f"{what} 出てはいけない線がある: {ln}"


def from_point(got, x, y):
    """(x1,y1)=(x,y) の線（交点側が端点）。"""
    return [t for t in got if _near(t[0], x, TOL) and _near(t[1], y, TOL)]


def touching(lines, x, y):
    """どちらかの端点が (x,y) の線（向きを問わない。PDF 用）。"""
    return [t for t in lines if (_near(t[0], x, TOL) and _near(t[1], y, TOL)) or (_near(t[2], x, TOL) and _near(t[3], y, TOL))]


def pdf_inner(tmp_path, diff, files):
    pdfs, _, _ = impose(tmp_path, diff, files)
    inner, _, _ = inner_segs(pdfs[0])
    return tuples(inner)


def check_alignment(tmp_path, imgs, ax, ay, count, absent, present, tag):
    """C-01〜C-09 の共通の期待 + その行の 件数・出ない線・出る線。A と P の一致を含む。"""
    px, py = int(ax != "center"), int(ay != "center")
    diff = AL(ax, ay)
    got = inner_marks_of(preview(tmp_path, diff))
    # 件数（TC の値と、式 N = 54−10px−4py）
    assert len(got) == count, f"{tag} 件数 期待 {count} 実際 {len(got)}"
    assert len(got) == 54 - 10 * px - 4 * py, f"{tag} 式 54−10px−4py"
    # 出る線はすべて存在し、出ない線は 1 本も存在しない
    assert_contains(got, present, directed=True, what=f"{tag} 出る線")
    assert_absent(got, absent, what=tag)
    if (ax, ay) == ("center", "center"):
        assert_same(got, S10X, directed=True, what=f"{tag} N-63 と同じ集合（S10x）")
    # P 上の線 0 本・寄せていない側の外周の線の線はそのまま（縦 10・横 4）
    xs, ys = XT[ax], YT[ay]
    if ax == "left":
        assert vlines(got, xs[0]) == [], f"{tag} x={xs[0]} 上の縦の線が残っている"
        assert len(vlines(got, xs[-1])) == 10, f"{tag} x={xs[-1]} 上の縦の線は 10 本"
    if ax == "right":
        assert vlines(got, xs[-1]) == [], f"{tag} x={xs[-1]} 上の縦の線が残っている"
        assert len(vlines(got, xs[0])) == 10, f"{tag} x={xs[0]} 上の縦の線は 10 本"
    if ay == "top":
        assert hlines(got, ys[0]) == [], f"{tag} y={ys[0]} 上の横の線が残っている"
        assert len(hlines(got, ys[-1])) == 4, f"{tag} y={ys[-1]} 上の横の線は 4 本"
    if ay == "bottom":
        assert hlines(got, ys[-1]) == [], f"{tag} y={ys[-1]} 上の横の線が残っている"
        assert len(hlines(got, ys[0])) == 4, f"{tag} y={ys[0]} 上の横の線は 4 本"
    # inward（同じ寄せ先）の 26 本をすべて含む
    assert_contains(got, shift(S10, DX[ax], DY[ay]), directed=True, what=f"{tag} inward 26 本")
    # P（PDF）: 内側の線が A と一致
    assert_same(pdf_inner(tmp_path, diff, imgs["white10"]), got, what=f"{tag} PDF 内側 vs inner_marks")
    return got


# ================================================================ 4.1 寄せ先 9 通り（n=10）
def test_C01_center_center_regression(tmp_path, imgs):
    """C-01 center / center: 54 件（N-63 と同じ集合。デグレ）。"""
    check_alignment(
        tmp_path, imgs, "center", "center", 54, [],
        [(14, 11, 14, 14), (14, 11, 17, 11), (105, 11, 102, 11), (196, 286, 193, 286)], "C-01")


def test_C02_left_center(tmp_path, imgs):
    """C-02 left / center: 44 = 54 − 10。x=4.2 上の縦の線 0 本。x=186.2 上の縦の線 10 本。"""
    check_alignment(
        tmp_path, imgs, "left", "center", 44,
        [(4.2, 11, 4.2, 14), (4.2, 66, 4.2, 63), (4.2, 66, 4.2, 69), (4.2, 286, 4.2, 283)],
        [(4.2, 11, 7.2, 11), (4.2, 66, 7.2, 66), (4.2, 286, 7.2, 286), (186.2, 11, 186.2, 14),
         (186.2, 11, 183.2, 11), (95.2, 11, 92.2, 11)], "C-02")


def test_C03_right_center(tmp_path, imgs):
    """C-03 right / center: 44 = 54 − 10。x=205.8 上の縦の線 0 本。x=23.8 上の縦の線 10 本。"""
    check_alignment(
        tmp_path, imgs, "right", "center", 44,
        [(205.8, 11, 205.8, 14), (205.8, 66, 205.8, 63), (205.8, 66, 205.8, 69), (205.8, 286, 205.8, 283)],
        [(205.8, 11, 202.8, 11), (205.8, 66, 202.8, 66), (23.8, 11, 23.8, 14), (23.8, 11, 26.8, 11)], "C-03")


def test_C04_center_top(tmp_path, imgs):
    """C-04 center / top: 50 = 54 − 4。y=4.2 上の横の線 0 本。y=279.2 上の横の線 4 本。"""
    check_alignment(
        tmp_path, imgs, "center", "top", 50,
        [(14, 4.2, 17, 4.2), (105, 4.2, 102, 4.2), (105, 4.2, 108, 4.2), (196, 4.2, 193, 4.2)],
        [(14, 4.2, 14, 7.2), (105, 4.2, 105, 7.2), (196, 4.2, 196, 7.2), (14, 279.2, 17, 279.2),
         (14, 279.2, 14, 276.2)], "C-04")


def test_C05_center_bottom(tmp_path, imgs):
    """C-05 center / bottom: 50 = 54 − 4。y=292.8 上の横の線 0 本。y=17.8 上の横の線 4 本。"""
    check_alignment(
        tmp_path, imgs, "center", "bottom", 50,
        [(14, 292.8, 17, 292.8), (105, 292.8, 102, 292.8), (105, 292.8, 108, 292.8), (196, 292.8, 193, 292.8)],
        [(14, 292.8, 14, 289.8), (105, 292.8, 105, 289.8), (196, 292.8, 196, 289.8), (14, 17.8, 17, 17.8)], "C-05")


def test_C06_left_top(tmp_path, imgs):
    """C-06 left / top: 40 = 54 − 10 − 4。P 上の線 0 本。全端点が x∈[4.2,186.2]・y∈[4.2,279.2]。"""
    got = check_alignment(
        tmp_path, imgs, "left", "top", 40,
        [(4.2, 4.2, 4.2, 7.2), (4.2, 4.2, 7.2, 4.2), (4.2, 59.2, 4.2, 56.2), (4.2, 59.2, 4.2, 62.2),
         (95.2, 4.2, 92.2, 4.2), (95.2, 4.2, 98.2, 4.2), (186.2, 4.2, 183.2, 4.2)],
        [(4.2, 59.2, 7.2, 59.2), (95.2, 4.2, 95.2, 7.2), (186.2, 4.2, 186.2, 7.2), (4.2, 279.2, 7.2, 279.2),
         (186.2, 279.2, 186.2, 276.2), (186.2, 279.2, 183.2, 279.2), (186.2, 59.2, 186.2, 56.2),
         (186.2, 59.2, 183.2, 59.2)], "C-06")
    for t in got:
        for x in (t[0], t[2]):
            assert 4.2 - TOL <= x <= 186.2 + TOL, t
        for y in (t[1], t[3]):
            assert 4.2 - TOL <= y <= 279.2 + TOL, t


def test_C07_right_top(tmp_path, imgs):
    """C-07 right / top: 40。P 上の線 0 本（x=205.8 の縦・y=4.2 の横）。"""
    check_alignment(
        tmp_path, imgs, "right", "top", 40,
        [(205.8, 4.2, 205.8, 7.2), (205.8, 4.2, 202.8, 4.2), (114.8, 4.2, 111.8, 4.2), (114.8, 4.2, 117.8, 4.2),
         (205.8, 59.2, 205.8, 56.2), (205.8, 59.2, 205.8, 62.2)],
        [(23.8, 4.2, 23.8, 7.2), (114.8, 4.2, 114.8, 7.2), (205.8, 59.2, 202.8, 59.2), (205.8, 279.2, 202.8, 279.2),
         (23.8, 279.2, 23.8, 276.2), (23.8, 279.2, 26.8, 279.2)], "C-07")


def test_C08_left_bottom(tmp_path, imgs):
    """C-08 left / bottom: 40。P 上の線 0 本（x=4.2 の縦・y=292.8 の横）。"""
    check_alignment(
        tmp_path, imgs, "left", "bottom", 40,
        [(4.2, 292.8, 4.2, 289.8), (4.2, 292.8, 7.2, 292.8), (4.2, 72.8, 4.2, 69.8), (4.2, 72.8, 4.2, 75.8),
         (95.2, 292.8, 92.2, 292.8), (95.2, 292.8, 98.2, 292.8)],
        [(186.2, 292.8, 186.2, 289.8), (4.2, 17.8, 7.2, 17.8), (95.2, 292.8, 95.2, 289.8), (186.2, 17.8, 186.2, 20.8),
         (186.2, 17.8, 183.2, 17.8)], "C-08")


def test_C09_right_bottom(tmp_path, imgs):
    """C-09 right / bottom: 40。P 上の線 0 本（x=205.8 の縦・y=292.8 の横）。"""
    check_alignment(
        tmp_path, imgs, "right", "bottom", 40,
        [(205.8, 292.8, 205.8, 289.8), (205.8, 292.8, 202.8, 292.8), (205.8, 72.8, 205.8, 69.8),
         (205.8, 72.8, 205.8, 75.8), (114.8, 292.8, 111.8, 292.8), (114.8, 292.8, 117.8, 292.8)],
        [(23.8, 292.8, 23.8, 289.8), (205.8, 17.8, 202.8, 17.8), (114.8, 292.8, 114.8, 289.8), (23.8, 17.8, 23.8, 20.8),
         (23.8, 17.8, 26.8, 17.8)], "C-09")


# ================================================================ 4.2 ユーザーの 3 例・差分・不変
def test_C10_user_three_examples(tmp_path, imgs):
    """C-10 left / top: (4.2,4.2) を端点（x1,y1）とする線は 0 本。(4.2,59.2) からは {7.2,59.2} の 1 本だけ。
    (95.2,4.2) からは {95.2,7.2} の 1 本だけ。PDF の線分も同じ。"""
    diff = AL("left", "top")
    got = inner_marks_of(preview(tmp_path, diff))
    assert from_point(got, 4.2, 4.2) == []
    a = from_point(got, 4.2, 59.2)
    assert len(a) == 1 and _near(a[0][2], 7.2, TOL) and _near(a[0][3], 59.2, TOL), a
    b = from_point(got, 95.2, 4.2)
    assert len(b) == 1 and _near(b[0][2], 95.2, TOL) and _near(b[0][3], 7.2, TOL), b
    pdf = pdf_inner(tmp_path, diff, imgs["white10"])
    assert touching(pdf, 4.2, 4.2) == [], "PDF: (4.2,4.2) に線がある"
    pa = touching(pdf, 4.2, 59.2)
    assert len(pa) == 1, pa
    assert_same(pa, [(4.2, 59.2, 7.2, 59.2)], what="PDF (4.2,59.2)")
    pb = touching(pdf, 95.2, 4.2)
    assert len(pb) == 1, pb
    assert_same(pb, [(95.2, 4.2, 95.2, 7.2)], what="PDF (95.2,4.2)")


def test_C11_diff_from_old_N69(tmp_path):
    """C-11 left / top: C-06 の 40 件と旧規則の 54 件（S10x の写像）の差は 14 本。x1=x2=4.2 の 10 本と y1=y2=4.2 の 4 本。他に残る線なし。"""
    got = inner_marks_of(preview(tmp_path, AL("left", "top")))
    assert len(S10XLT) == 54
    missing, extra = match(S10XLT, got, directed=True)  # missing: 40 件にあって旧 54 件に無い線 / extra: 旧 54 件にだけある線
    assert len(got) == 40, f"件数 期待 40 実際 {len(got)}"
    assert not missing, f"40 件のうち旧 54 件に無い線がある: {missing[:6]}"
    assert len(extra) == 14, f"差 期待 14 実際 {len(extra)}"
    assert len(vlines(extra, 4.2)) == 10 and len(hlines(extra, 4.2)) == 4, extra
    assert len(vlines(extra, 4.2)) + len(hlines(extra, 4.2)) == len(extra), f"差集合に他の線: {extra}"


def test_C12_non_aligned_side_unchanged(tmp_path):
    """C-12 left / top: x1=x2=186.2 の縦の線が 10 本（y=4.2〜224.2 から下 5 本・y=59.2〜279.2 から上 5 本）。
    y1=y2=279.2 の横の線が 4 本。"""
    got = inner_marks_of(preview(tmp_path, AL("left", "top")))
    assert len(got) == 40, f"件数 期待 40 実際 {len(got)}"
    ys = YT["top"]
    v = vlines(got, 186.2)
    assert len(v) == 10, f"x=186.2 の縦の線 期待 10 実際 {len(v)}"
    assert_same(v, [(186.2, y, 186.2, y + 3) for y in ys[:-1]] + [(186.2, y, 186.2, y - 3) for y in ys[1:]],
                directed=True, what="x=186.2 の縦の線")
    h = hlines(got, 279.2)
    assert len(h) == 4, f"y=279.2 の横の線 期待 4 実際 {len(h)}"
    assert_same(h, [(4.2, 279.2, 7.2, 279.2), (95.2, 279.2, 92.2, 279.2), (95.2, 279.2, 98.2, 279.2),
                    (186.2, 279.2, 183.2, 279.2)], directed=True, what="y=279.2 の横の線")


def test_C13_outer_marks_unchanged(tmp_path, imgs):
    """C-13 left / top: marks が L=0 の応答の marks と完全に一致。PDF の外周の線分も L=0 の PDF と一致。"""
    diff = AL("left", "top")
    pv = preview(tmp_path, diff)
    p0 = preview(tmp_path, mg(LY(align_x="left", align_y="top"), CR(0, "cross", True)))
    assert_same(mark_tuples(pv["marks"]), mark_tuples(p0["marks"]), directed=True, tol=1e-9, what="marks")
    assert len(pv["marks"]) == len(p0["marks"])
    pdfs, _, _ = impose(tmp_path, diff, imgs["white10"])
    inner, segs, _ = inner_segs(pdfs[0])
    outer = [s.t for s in segs if s not in inner]
    base, _, _ = impose(tmp_path, mg(LY(align_x="left", align_y="top"), CR(0, "cross", True)), imgs["white10"])
    bsegs, _ = read_pdf(base[0])
    assert_same(outer, tuples(bsegs), what="PDF 外周の線分 vs L=0")


def test_C14_dashed_pdf_starts_at_intersection(tmp_path, imgs):
    """C-14 left / top・dashed（2/1）: 内側 40 本。実線部 2mm・空白部 1mm。各線の始点が交点側。"""
    dashed = LY(mark_style="dashed", mark_dash_mm=2, mark_gap_mm=1)
    diff = mg(AL("left", "top"), dashed)
    got = inner_marks_of(preview(tmp_path, diff))
    assert len(got) == 40, f"A 件数 期待 40 実際 {len(got)}"
    pdfs, _, _ = impose(tmp_path, diff, imgs["white10"])
    inner, _, _ = inner_segs(pdfs[0])
    assert len(inner) == 40, f"PDF 内側 期待 40 実際 {len(inner)}"
    assert_same(tuples(inner), got, directed=True, what="PDF 内側（始点つき）vs inner_marks")
    assert_contains(tuples(inner), [(4.2, 59.2, 7.2, 59.2), (95.2, 4.2, 95.2, 7.2), (186.2, 279.2, 183.2, 279.2)],
                    directed=True, what="始点が交点側")
    for s in inner:
        assert len(s.dash) == 2 and abs(s.dash[0] - PT_2MM) < 0.01 and abs(s.dash[1] - PT_1MM) < 0.01, s


# ================================================================ 4.3 枚数の端・gap・unprintable
def test_C15_n1_both_axes(tmp_path, imgs):
    """C-15 n=1・両軸寄せ（a=2・b=2）: left/top は 4 件でキーあり、(4.2,4.2) から出る線なし、PDF の内側も 4 本。right/bottom も 4 本。"""
    one = imgs["white10"][:1]
    d1 = mg(LY(cards_per_sheet=1), AL("left", "top"))
    got = inner_marks_of(preview(tmp_path, d1))
    assert len(got) == 4, f"left/top 件数 期待 4 実際 {len(got)}"
    assert_same(got, [(95.2, 4.2, 95.2, 7.2), (4.2, 59.2, 7.2, 59.2), (95.2, 59.2, 95.2, 56.2), (95.2, 59.2, 92.2, 59.2)],
                directed=True, what="left/top")
    assert from_point(got, 4.2, 4.2) == []
    pdf = pdf_inner(tmp_path, d1, one)
    assert len(pdf) == 4, f"left/top PDF 内側 期待 4 実際 {len(pdf)}"
    assert_same(pdf, got, what="left/top PDF vs A")
    d2 = mg(LY(cards_per_sheet=1), AL("right", "bottom"))
    got2 = inner_marks_of(preview(tmp_path, d2))
    assert len(got2) == 4, f"right/bottom 件数 期待 4 実際 {len(got2)}"
    assert_same(got2, [(114.8, 237.8, 114.8, 240.8), (114.8, 237.8, 117.8, 237.8), (205.8, 237.8, 202.8, 237.8),
                       (114.8, 292.8, 114.8, 289.8)], directed=True, what="right/bottom")
    pdf2 = pdf_inner(tmp_path, d2, one)
    assert len(pdf2) == 4, f"right/bottom PDF 内側 期待 4 実際 {len(pdf2)}"
    assert_same(pdf2, got2, what="right/bottom PDF vs A")


def test_C16_n1_one_axis(tmp_path):
    """C-16 n=1・片軸寄せ（6 本 = 8 − 2）: left / center は 6 件。x=4.2 上の縦の線なし。center / center は 8 本のまま。"""
    got_c = inner_marks_of(preview(tmp_path, mg(LY(cards_per_sheet=1), AL("center", "center"))))
    assert len(got_c) == 8, f"center/center 件数 期待 8 実際 {len(got_c)}"
    assert_same(got_c, S1X, directed=True, what="center/center（B-15）")
    got = inner_marks_of(preview(tmp_path, mg(LY(cards_per_sheet=1), AL("left", "center"))))
    assert len(got) == 6, f"left/center 件数 期待 6 実際 {len(got)}"
    assert_same(got, [(4.2, 11, 7.2, 11), (4.2, 66, 7.2, 66), (95.2, 11, 95.2, 14), (95.2, 11, 92.2, 11),
                      (95.2, 66, 95.2, 63), (95.2, 66, 92.2, 66)], directed=True, what="left/center")
    assert vlines(got, 4.2) == []


def test_C17_n2(tmp_path, imgs):
    """C-17 n=2（1 行・a=3・b=2）: left/top は 8 件。S2lt の inward 2 本を含む。center / center は 14 本のまま。"""
    two = imgs["white10"][:2]
    got_c = inner_marks_of(preview(tmp_path, mg(LY(cards_per_sheet=2), AL("center", "center"))))
    assert len(got_c) == 14, f"center/center 件数 期待 14 実際 {len(got_c)}"
    assert_same(got_c, S2X, directed=True, what="center/center（B-16）")
    diff = mg(LY(cards_per_sheet=2), AL("left", "top"))
    got = inner_marks_of(preview(tmp_path, diff))
    assert len(got) == 8, f"left/top 件数 期待 8 実際 {len(got)}"
    assert_same(got, [(95.2, 4.2, 95.2, 7.2), (186.2, 4.2, 186.2, 7.2), (4.2, 59.2, 7.2, 59.2), (95.2, 59.2, 95.2, 56.2),
                      (95.2, 59.2, 92.2, 59.2), (95.2, 59.2, 98.2, 59.2), (186.2, 59.2, 186.2, 56.2),
                      (186.2, 59.2, 183.2, 59.2)], directed=True, what="left/top")
    assert_contains(got, shift(S2C, -9.8, -6.8), directed=True, what="S2lt（inward 2 本）")
    assert_same(pdf_inner(tmp_path, diff, two), got, what="PDF vs A")


def test_C18_n3(tmp_path, imgs):
    """C-18 n=3（a=3・b=3）: left/top 16 件（交点ごとの内訳つき）。left/center 20 件。center/center 24 件。"""
    three = imgs["white3"]
    got_c = inner_marks_of(preview(tmp_path, mg(LY(cards_per_sheet=3), AL("center", "center"))))
    assert len(got_c) == 24, f"center/center 件数 期待 24 実際 {len(got_c)}"
    assert_same(got_c, S3X, directed=True, what="center/center（N-68）")
    diff = mg(LY(cards_per_sheet=3), AL("left", "top"))
    got = inner_marks_of(preview(tmp_path, diff))
    assert len(got) == 16, f"left/top 件数 期待 16 実際 {len(got)}"
    per = Counter((round(t[0], 1), round(t[1], 1)) for t in got)
    want = {(95.2, 4.2): 1, (186.2, 4.2): 1, (4.2, 59.2): 1, (95.2, 59.2): 4, (186.2, 59.2): 3,
            (4.2, 114.2): 1, (95.2, 114.2): 3, (186.2, 114.2): 2}
    assert dict(per) == want, f"交点ごとの本数 期待 {want} 実際 {dict(per)}"
    assert_contains(got, S3LT, directed=True, what="S3lt（inward 8 本）")
    assert from_point(got, 4.2, 4.2) == []
    assert_same(pdf_inner(tmp_path, diff, three), got, what="left/top PDF vs A")
    got_lc = inner_marks_of(preview(tmp_path, mg(LY(cards_per_sheet=3), AL("left", "center"))))
    assert len(got_lc) == 20, f"left/center 件数 期待 20 実際 {len(got_lc)}"
    assert vlines(got_lc, 4.2) == []


def test_C19_n7_empty_slot(tmp_path, imgs):
    """C-19 n=7（2 列×4 行・最後の行に空き）right/bottom: 32 件 = 44 − 8 − 4。x=205.8 の縦 0 本。y=292.8 の横 0 本（空きスロットの下も）。"""
    diff = mg(LY(cards_per_sheet=7), AL("right", "bottom"))
    got = inner_marks_of(preview(tmp_path, diff))
    assert len(got) == 32, f"件数 期待 32 実際 {len(got)}"
    assert vlines(got, 205.8) == [], "x=205.8 上の縦の線が残っている"
    assert hlines(got, 292.8) == [], "y=292.8 上の横の線が残っている（空きスロットの下を含む）"
    assert_contains(got, [(23.8, 292.8, 23.8, 289.8), (114.8, 292.8, 114.8, 289.8), (205.8, 72.8, 202.8, 72.8),
                          (23.8, 72.8, 26.8, 72.8)], directed=True, what="出る線")
    assert_absent(got, [(114.8, 292.8, 117.8, 292.8), (205.8, 292.8, 202.8, 292.8)], what="C-19")
    assert_same(pdf_inner(tmp_path, diff, imgs["white10"][:7]), got, what="PDF vs A")


def test_C20_gap_x2(tmp_path):
    """C-20 gap_x_mm=2（a=4・b=6）: left/center 66 件。left/top 60 件。center/center 76 件。"""
    gap = LY(gap_x_mm=2)
    got_c = inner_marks_of(preview(tmp_path, mg(gap, AL("center", "center"))))
    assert len(got_c) == 76, f"center/center 件数 期待 76 実際 {len(got_c)}"
    got = inner_marks_of(preview(tmp_path, mg(gap, AL("left", "center"))))
    assert len(got) == 66, f"left/center 件数 期待 66 実際 {len(got)}"
    assert vlines(got, 4.2) == [], "x=4.2 上の縦の線が残っている"
    assert len(vlines(got, 188.2)) == 10, f"x=188.2 の縦の線 期待 10 実際 {len(vlines(got, 188.2))}"
    got_t = inner_marks_of(preview(tmp_path, mg(gap, AL("left", "top"))))
    assert len(got_t) == 60, f"left/top 件数 期待 60 実際 {len(got_t)}"
    assert hlines(got_t, 4.2) == [], "y=4.2 上の横の線が残っている"
    assert len(hlines(got_t, 279.2)) == 6, f"y=279.2 の横の線 期待 6 実際 {len(hlines(got_t, 279.2))}"
    assert_contains(got_t, [(95.2, 4.2, 95.2, 7.2), (97.2, 4.2, 97.2, 7.2)], directed=True, what="境目 2 本の内向きの腕")
    assert_absent(got_t, [(4.2, 59.2, 4.2, 56.2)], what="C-20")


def _guard_capacity(tmp_path, diff, tc):
    root = mkhome(tmp_path, diff)
    cap = client(root).get("/api/capacity").json()
    if not (cap.get("capacity") == 10 and cap.get("columns") == 2 and cap.get("rows") == 5):
        pytest.skip(f"{tc} 不成立: ガード（capacity=10・2 列×5 行）が外れた。実測 {cap}")


def test_C21_unprintable_zero(tmp_path, imgs):
    """C-21 device.unprintable_mm=0・left/top（P が用紙の端と一致）: 40 件。設定値で決めるので規則どおり消える。"""
    diff = mg({"device": {"unprintable_mm": 0}}, AL("left", "top"))
    _guard_capacity(tmp_path, diff, "C-21")
    got = inner_marks_of(preview(tmp_path, diff))
    assert len(got) == 40, f"件数 期待 40 実際 {len(got)}"
    assert_absent(got, [(0, 0, 0, 3), (0, 0, 3, 0), (0, 55, 0, 52), (91, 0, 88, 0)], what="C-21")
    assert_contains(got, [(0, 55, 3, 55), (91, 0, 91, 3), (182, 0, 182, 3), (182, 275, 182, 272), (182, 275, 179, 275)],
                    directed=True, what="出る線")
    assert_same(pdf_inner(tmp_path, diff, imgs["white10"]), got, what="PDF vs A")


def test_C22_center_grid_on_printable_edge(tmp_path):
    """C-22 unprintable_mm=11・center/center（格子が域の端に一致しても消さない）: 54 件。(14,11)→(17,11)・(196,286)→(193,286) が出る。"""
    diff = mg({"device": {"unprintable_mm": 11}}, AL("center", "center"))
    _guard_capacity(tmp_path, diff, "C-22")
    got = inner_marks_of(preview(tmp_path, diff))
    assert len(got) == 54, f"件数 期待 54 実際 {len(got)}"
    assert_contains(got, [(14, 11, 17, 11), (196, 286, 193, 286)], directed=True, what="境界ちょうどの線")


# ================================================================ 4.4 scale との関係
def test_C23_scale_y_left_top(tmp_path, imgs):
    """C-23 print.scale_y=1.05・left/top: 36 件 = 54 − 14 − 4。縦の腕の長さ 3.15（クリップ 2 本を除く）。横の腕の長さ 3。y=4.2 の横の線 0 本。"""
    diff = mg({"print": {"scale_y": 1.05}}, AL("left", "top"))
    got = inner_marks_of(preview(tmp_path, diff))
    assert len(got) == 36, f"件数 期待 36 実際 {len(got)}"
    clipped = [(95.2, 292.8, 95.2, 289.8), (186.2, 292.8, 186.2, 289.8)]
    assert_contains(got, clipped, directed=True, tol=1e-3, what="クリップされる縦の腕")
    assert_contains(got, [(95.2, 4.2, 95.2, 7.35), (95.2, 61.95, 95.2, 58.8), (95.2, 61.95, 95.2, 65.1),
                          (4.2, 61.95, 7.2, 61.95)], directed=True, tol=1e-3, what="TC の例")
    assert hlines(got, 4.2) == [], "y=4.2 上の横の線が残っている"
    assert [t for t in got if is_horizontal(t) and t[1] > 292.8 + 1e-3] == [], "y'=292.95 上の横の腕が残っている"
    for t in got:
        if is_vertical(t):
            if any(abs(t[0] - c[0]) < 1e-3 and abs(t[1] - c[1]) < 1e-3 and abs(t[3] - c[3]) < 1e-3 for c in clipped):
                continue
            assert abs(abs(t[3] - t[1]) - 3.15) < 1e-3, f"縦の腕の長さ 期待 3.15: {t}"
        else:
            assert abs(abs(t[2] - t[0]) - 3.0) < 1e-3, f"横の腕の長さ 期待 3: {t}"
    assert_same(pdf_inner(tmp_path, diff, imgs["white10"]), got, what="PDF vs A")


def test_C24_scale_x_right_center(tmp_path, imgs):
    """C-24 print.scale_x=0.9・right/center: 44 件。x=205.8 の縦の線 0 本。横の腕の長さ 2.7・縦の腕 3。"""
    diff = mg({"print": {"scale_x": 0.9}}, AL("right", "center"))
    got = inner_marks_of(preview(tmp_path, diff))
    assert len(got) == 44, f"件数 期待 44 実際 {len(got)}"
    assert vlines(got, 205.8) == [], "x=205.8 上の縦の線が残っている"
    assert_contains(got, [(42, 11, 42, 14), (42, 11, 44.7, 11), (123.9, 66, 121.2, 66), (123.9, 66, 126.6, 66),
                          (205.8, 66, 203.1, 66), (205.8, 11, 203.1, 11)], directed=True, tol=1e-3, what="TC の例")
    for t in got:
        if is_vertical(t):
            assert abs(abs(t[3] - t[1]) - 3.0) < 1e-3, f"縦の腕の長さ 期待 3: {t}"
        else:
            assert abs(abs(t[2] - t[0]) - 2.7) < 1e-3, f"横の腕の長さ 期待 2.7: {t}"
    assert_same(pdf_inner(tmp_path, diff, imgs["white10"]), got, what="PDF vs A")


# ================================================================ 4.5 API・SVG・独立・不変
C06_ABSENT = [(4.2, 4.2, 4.2, 7.2), (4.2, 4.2, 7.2, 4.2), (4.2, 59.2, 4.2, 56.2), (4.2, 59.2, 4.2, 62.2),
              (95.2, 4.2, 92.2, 4.2), (95.2, 4.2, 98.2, 4.2), (186.2, 4.2, 183.2, 4.2)]
C06_PRESENT = [(4.2, 59.2, 7.2, 59.2), (95.2, 4.2, 95.2, 7.2), (186.2, 4.2, 186.2, 7.2), (4.2, 279.2, 7.2, 279.2),
               (186.2, 279.2, 186.2, 276.2), (186.2, 279.2, 183.2, 279.2), (186.2, 59.2, 186.2, 56.2),
               (186.2, 59.2, 183.2, 59.2)]


def test_C25_post_preview_unsaved_align(tmp_path):
    """C-25 空の HOME。POST /api/layout/preview（cross・L=3・left/top）: 200・inner_marks 40 件で C-06 と一致・キー集合は GET と同じ。
    config.json は作られない。GET の応答に inner_marks なし。GET /api/config は center/center のまま。DB はバイト列が同じ。"""
    root = mkhome(tmp_path)
    c = client(root)
    body = _body(c, inner_mark_mode="cross", inner_mark_length_mm=3, align_x="left", align_y="top")
    dbp = root / "db.sqlite3"
    db_before = dbp.read_bytes() if dbp.exists() else None
    r = post_preview(c, body)
    assert r.status_code == 200, r.text
    pv = r.json()
    got = inner_marks_of(pv)
    assert len(got) == 40, f"件数 期待 40 実際 {len(got)}"
    assert_contains(got, C06_PRESENT, directed=True, what="C-06 出る線")
    assert_absent(got, C06_ABSENT, what="C-25")
    saved = client(mkhome(tmp_path, AL("left", "top"))).get("/api/layout/preview").json()
    assert set(pv) == set(saved), (sorted(pv), sorted(saved))
    assert_same(got, inner_marks_of(saved), directed=True, what="POST vs 同じ設定を保存した HOME の GET")
    assert not (root / "config.json").exists(), "POST で config.json が作られた"
    assert "inner_marks" not in c.get("/api/layout/preview").json()
    lay = get_cfg(c)["layout"]
    assert lay["align_x"] == "center" and lay["align_y"] == "center"
    if db_before is not None:
        assert dbp.read_bytes() == db_before, "POST で DB のバイト列が変わった"


def test_C26_get_equals_post_saved_cross_aligned(tmp_path):
    """C-26 config.json に cross・L=3・left/top: GET と同じ内容の全体の POST が deep equal。inner_marks は 40 件。"""
    root = mkhome(tmp_path, AL("left", "top"))
    c = client(root)
    g = c.get("/api/layout/preview")
    assert g.status_code == 200, g.text
    r = post_preview(c, get_cfg(c))
    assert r.status_code == 200, r.text
    assert len(inner_marks_of(g.json())) == 40, f"GET 件数 期待 40 実際 {len(inner_marks_of(g.json()))}"
    assert r.json() == g.json(), "GET と POST の応答が全体で一致しない"


@pytest.mark.skip(reason="C-27: 目視/DOM（管理画面タブ「面付けプレビュー」と設定画面右側の SVG の line 本数・座標・stroke-width は DOM でしか確認できない）。browser-test で判定する")
def test_C27_slot_diagram_svg_matches_api_and_pdf():
    """C-27 cross・L=3・W=0.5・left/top: SVG の内側の線 40 本・座標は C-06 と一致・stroke-width 0.35（外周 0.2）。line 総数 = marks の件数 + 40。"""


def test_C28_outer_inner_independent(tmp_path, imgs):
    """C-28 left/top・cross・L=3: mark_enabled と inner_mark_enabled の 4 通り。"""
    base = LY(align_x="left", align_y="top")
    w = imgs["white10"]
    # (true, true)
    pv = preview(tmp_path, mg(base, LY(mark_enabled=True), CR(3, "cross", True)))
    assert len(inner_marks_of(pv)) == 40, "(true,true) 内側 40 件"
    # (false, true)
    d_ft = mg(base, LY(mark_enabled=False), CR(3, "cross", True))
    pv = preview(tmp_path, d_ft)
    assert pv["marks"] == [], "(false,true) marks は []"
    assert len(inner_marks_of(pv)) == 40, f"(false,true) 内側 期待 40 実際 {len(pv.get('inner_marks', []))}"
    pdfs, _, _ = impose(tmp_path, d_ft, w)
    segs, _ = read_pdf(pdfs[0])
    assert len(segs) == 40, f"(false,true) PDF の線分 期待 40 実際 {len(segs)}"
    # (true, false)
    d_tf = mg(base, LY(mark_enabled=True), CR(3, "cross", False))
    pv = preview(tmp_path, d_tf)
    assert "inner_marks" not in pv, "(true,false) inner_marks のキーなし"
    pdfs, _, _ = impose(tmp_path, d_tf, w)
    segs, _ = read_pdf(pdfs[0])
    p0, _, _ = impose(tmp_path, mg(base, LY(mark_enabled=True), CR(0, "cross", True)), w)
    s0, _ = read_pdf(p0[0])
    assert_same(tuples(segs), tuples(s0), what="(true,false) PDF の線分 vs L=0")
    # (false, false)
    d_ff = mg(base, LY(mark_enabled=False), CR(3, "cross", False))
    pv = preview(tmp_path, d_ff)
    assert "inner_marks" not in pv, "(false,false) inner_marks のキーなし"
    pdfs, _, _ = impose(tmp_path, d_ff, w)
    segs, _ = read_pdf(pdfs[0])
    assert len(segs) == 0, f"(false,false) PDF の線分 期待 0 実際 {len(segs)}"


def test_C29_length_zero_regression(tmp_path, imgs, base_src):
    """C-29 left/top・cross・L=0: inner_marks のキーなし。PDF の全画素が 0f713ff と一致（solid・dashed）。layout.json は変わらない。"""
    al = LY(align_x="left", align_y="top")
    assert "inner_marks" not in preview(tmp_path, mg(al, CR(0, "cross", True)))
    for style in (None, {"layout": {"mark_style": "dashed"}}):
        diff = mg(al, CR(0, "cross", True), style)
        pdfs, _, _ = impose(tmp_path, diff, imgs["white10"])
        broot = mkhome(tmp_path, mg(al, style))  # 基準側の config.json に新キーは入れない
        bout = tmp_path / f"b_{broot.name}"
        bout.mkdir()
        code, so, se = base_cli(base_src, "impose", *imgs["white10"], "--out", bout / "out.pdf", "--home", broot)
        assert code == 0, se
        assert same_image(raster(pdfs[0]), raster(bout / "out.pdf")), f"全画素が一致しない（{style}）"
        assert layout_json(pdfs[0]) == layout_json(bout / "out.pdf"), f"layout.json が基準と違う（{style}）"


def test_C30_schema_keys_unchanged(tmp_path, base_bed):
    """C-30 空の HOME: layout のキー集合が bed031a と同じ（新しいキーなし）。inner_mark_mode の enum は ["inward","cross"] のまま。"""
    root = mkhome(tmp_path)
    api = _layout_def(client(root).get("/api/config/schema").json())
    code, so, se = cli(["config", "schema", "--home", root])
    assert code == 0, se
    cl = _layout_def(json.loads(so))
    broot = mkhome(tmp_path)
    code, bso, bse = base_cli(base_bed, "config", "schema", "--home", broot)
    assert code == 0, bse
    base = _layout_def(json.loads(bso))
    assert set(api) == set(base), f"API: 増減 +{sorted(set(api) - set(base))} -{sorted(set(base) - set(api))}"
    assert set(cl) == set(base), f"CLI: 増減 +{sorted(set(cl) - set(base))} -{sorted(set(base) - set(cl))}"
    assert api["inner_mark_mode"]["enum"] == ["inward", "cross"]
    assert cl["inner_mark_mode"]["enum"] == ["inward", "cross"]
    code, so, se = cli(["config", "show", "--home", root])
    assert code == 0, se
    code, bso, bse = base_cli(base_bed, "config", "show", "--home", broot)
    assert code == 0, bse
    assert set(json.loads(so)["layout"]) == set(json.loads(bso)["layout"]), "config show の layout キー集合が bed031a と違う"


def test_C31_saved_settings_readable(tmp_path, imgs):
    """C-31 config.json に cross・L=3・left/top: GET /api/config は保存値のまま・読込エラーなし → 出力 40 本 → PUT（全体）後も cross・left・top。"""
    diff = AL("left", "top")
    root = mkhome(tmp_path, diff)
    c = client(root)
    cfg = get_cfg(c)
    lay = cfg["layout"]
    assert lay["inner_mark_mode"] == "cross" and lay["align_x"] == "left" and lay["align_y"] == "top"
    assert lay["inner_mark_length_mm"] == 3
    f = json.loads((root / "config.json").read_text(encoding="utf-8"))["layout"]
    assert f["inner_mark_mode"] == "cross" and f["align_x"] == "left" and f["align_y"] == "top"
    got = inner_marks_of(c.get("/api/layout/preview").json())
    assert len(got) == 40, f"A 件数 期待 40 実際 {len(got)}"
    pdf = pdf_inner(tmp_path, diff, imgs["white10"])
    assert len(pdf) == 40, f"P 件数 期待 40 実際 {len(pdf)}"
    assert_same(pdf, got, what="PDF vs A")
    assert put_cfg(c, cfg).status_code == 200
    f = json.loads((root / "config.json").read_text(encoding="utf-8"))["layout"]
    assert f["inner_mark_mode"] == "cross" and f["align_x"] == "left" and f["align_y"] == "top", f
    lay = get_cfg(c)["layout"]
    assert lay["inner_mark_mode"] == "cross" and lay["align_x"] == "left" and lay["align_y"] == "top"


def test_C32_inward_unchanged_nine_alignments(tmp_path, imgs):
    """C-32 inner_mark_mode=inward・L=3・9 通りの寄せ先: どれも 26 件（S10 の x・y の写像）。PDF の内側も一致。"""
    for ax, ay in COMBOS:
        diff = AI(ax, ay)
        got = inner_marks_of(preview(tmp_path, diff))
        assert len(got) == 26, f"({ax}/{ay}) 件数 期待 26 実際 {len(got)}"
        assert_same(got, shift(S10, DX[ax], DY[ay]), directed=True, what=f"({ax}/{ay}) S10 の写像")
        assert_same(pdf_inner(tmp_path, diff, imgs["white10"]), got, what=f"({ax}/{ay}) PDF vs A")


def test_C33_cross_contains_inward_difference(tmp_path):
    """C-33 cross・9 通り: inward の集合 ⊂ cross の集合。差の本数 center/center 28・left or right/center 18・center/top or bottom 24・角寄せ 14。
    差の線はすべて寄せていない外周の線に沿う腕。"""
    want = {("center", "center"): 28, ("left", "center"): 18, ("right", "center"): 18,
            ("center", "top"): 24, ("center", "bottom"): 24,
            ("left", "top"): 14, ("right", "top"): 14, ("left", "bottom"): 14, ("right", "bottom"): 14}
    for ax, ay in COMBOS:
        tag = f"({ax}/{ay})"
        cross = inner_marks_of(preview(tmp_path, AL(ax, ay)))
        inward = inner_marks_of(preview(tmp_path, AI(ax, ay)))
        missing, extra = match(cross, inward, directed=True)  # missing: inward にあって cross に無い / extra: cross にだけある（差）
        assert not missing, f"{tag} inward が cross に含まれていない: {missing[:6]}"
        assert len(extra) == want[(ax, ay)], f"{tag} 差の本数 期待 {want[(ax, ay)]} 実際 {len(extra)}"
        xs, ys = XT[ax], YT[ay]
        vx = {"left": [xs[-1]], "right": [xs[0]], "center": [xs[0], xs[-1]]}[ax]   # 寄せていない外周の縦の線
        hy = {"top": [ys[-1]], "bottom": [ys[0]], "center": [ys[0], ys[-1]]}[ay]   # 寄せていない外周の横の線
        for t in extra:
            ok = (is_vertical(t) and any(_near(t[0], x, TOL) for x in vx)) or \
                 (is_horizontal(t) and any(_near(t[1], y, TOL) for y in hy))
            assert ok, f"{tag} 差の線が寄せていない外周の線に沿う腕でない: {t}"


# ================================================================ 自動実行不可（目視確認項目）
@pytest.mark.skip(reason="X-11: 目視（見た目の判定が人の目になる。代替: C-06・C-10・C-27）")
def test_X11_attached_image_look():
    """X-11 2 列×5 行・左上寄せ・cross: 名刺 1 の左上に線がなく、左下は右の線だけ、右上は下の線だけに見える。"""


@pytest.mark.skip(reason="X-12: 目視（見た目の判定が人の目になる。代替: C-02〜C-09 の座標と本数）")
def test_X12_aligned_sides_look():
    """X-12 右下・右上・左下・片軸寄せで、詰めた側の線が消え、反対側は残って見える。"""


@pytest.mark.skip(reason="X-13: 目視（実機での印刷・裁断は対象外。利用者判断）")
def test_X13_usability_and_real_print():
    """X-13 寄せた側の外周の線に名刺間トンボが無くても裁断の目印として使いやすいか。実機で端の線が刷れるか。"""
