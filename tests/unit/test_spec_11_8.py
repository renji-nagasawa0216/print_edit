"""docs/spec.md 11.8（名刺間トンボ）の受け入れテスト（正本: ai_docs/specs/spec_11_8_tc.md の TC 80 件）。

実装前に書いた Red テスト。期待値は正本の値のまま。
- lp は実行しない: test_spec_11_3 の fake_lp（autouse）が PATH 先頭に偽 lp を置く。
- Home は毎回 tmp_path 配下の新しい空ディレクトリ。実 ~/PrintEdit・本番 config.json・実プリンタは使わない。
- デグレ TC の基準は `git archive 0f713ff` を新しい空ディレクトリへ展開して取る（worktree は作らない）。
- ブラウザ（管理画面の DOM）・実機・pytest 全体の再帰実行が要る TC は skip を 1 TC ごとに残す。
- 部分判定（名前に partial）: スロット図の SVG 部分はブラウザ判定、ここでは API・PDF の部分だけ。
- ingest 系 TC は tests/acceptance/fixtures/images/（gitignore 対象。make_fixtures.py が作る）の
  a3_three_col.png・a1_deg_0.png を使う。無ければ fail（再生成はしない）。
"""
from __future__ import annotations

import contextlib
import ctypes
import hashlib
import io
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
import pypdfium2.raw as pdfraw
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageChops

from print_edit.api.app import create_app
from print_edit.cli import main
from print_edit.home import Home

from preset_api import get_preset_data, put_preset_data
from test_spec_11_3 import Env, fake_lp, lp  # noqa: F401  (fake_lp は autouse。import が無いと効かない)

REPO = Path(__file__).resolve().parents[2]
BASE_REV = "0f713ff"
TOL = 0.01  # mm（A8）
PT2MM = 25.4 / 72
FX = REPO / "tests" / "acceptance" / "fixtures" / "images"
PT_2MM = 2 * 72 / 25.4  # 5.669
PT_1MM = 1 * 72 / 25.4  # 2.835
PT_01MM = 0.1 * 72 / 25.4
PT_02MM = 0.2 * 72 / 25.4  # 0.567


# ================================================================ 共通部品
def mg(*ds):
    """設定の差分を深くマージ。"""
    out: dict = {}
    for d in ds:
        for k, v in (d or {}).items():
            if isinstance(v, dict) and isinstance(out.get(k), dict):
                out[k] = {**out[k], **v}
            else:
                out[k] = dict(v) if isinstance(v, dict) else v
    return out


def IM(L=None, W=None):
    lay = {}
    if L is not None:
        lay["inner_mark_length_mm"] = L
    if W is not None:
        lay["inner_mark_width_mm"] = W
    return {"layout": lay}


def newhome(tmp_path: Path) -> Path:
    i = 0
    while (tmp_path / f"home{i}").exists():
        i += 1
    return tmp_path / f"home{i}"


def prep_home(root: Path, diff: dict | None) -> Path:
    for d in (root, root / "inbox", root / "processed", root / "jobs"):
        d.mkdir(parents=True, exist_ok=True)
    if diff is not None:
        (root / "config.json").write_text(json.dumps(diff, ensure_ascii=False), encoding="utf-8")
    return root


def mkhome(tmp_path, diff=None) -> Path:
    return prep_home(newhome(tmp_path), diff)


def client(root: Path, raise_exc=True) -> TestClient:
    return TestClient(create_app(Home(root)), raise_server_exceptions=raise_exc)


def cli(args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main([str(a) for a in args])
    return code, out.getvalue(), err.getvalue()


def sha(p) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


# ---------------------------------------------------------------- 画像
def _png(path: Path, arr):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(arr).save(path)


@pytest.fixture(scope="session")
def imgs(tmp_path_factory):
    d = tmp_path_factory.mktemp("imgs_11_8")
    white = np.full((1299, 2150), 255, np.uint8)
    yy, xx = np.mgrid[0:1299, 0:2150]
    out = {"white10": [], "white3": [], "img10": []}
    for i in range(10):
        p = d / "w10" / f"{i + 1:02d}.png"
        _png(p, white)
        out["white10"].append(p)
        p = d / "i10" / f"{i + 1:02d}.png"
        _png(p, ((xx * (i + 1) + yy * 3 + i * 17) % 256).astype(np.uint8))
        out["img10"].append(p)
    out["white3"] = out["white10"][:3]
    return out


def small_pngs(tmp_path, n):
    d = tmp_path / "small"
    out = []
    for i in range(n):
        p = d / f"{i + 1:02d}.png"
        _png(p, np.full((360, 600), 255, np.uint8))
        out.append(p)
    return out


# ---------------------------------------------------------------- 基準コミットの展開
def _checkout_baseline(tmp_path_factory, revision):
    d = tmp_path_factory.mktemp(f"base_{revision}")
    r = subprocess.run(["git", "archive", revision], cwd=REPO, capture_output=True, check=True)
    with tarfile.open(fileobj=io.BytesIO(r.stdout)) as t:
        t.extractall(d, filter="data")
    chk = _base_py(d, "import print_edit;print(print_edit.__file__)")
    assert chk.stdout.strip().startswith(str(d)), f"基準の print_edit が展開先から読まれていない: {chk.stdout!r} {chk.stderr!r}"
    return d


@pytest.fixture(scope="session")
def base_src(tmp_path_factory):
    return _checkout_baseline(tmp_path_factory, BASE_REV)


@pytest.fixture(scope="session")
def mono_base(tmp_path_factory):
    # 600dpi・1bit のモノクロ出力と、左上の紙端配置を含む改修前の基準。
    return _checkout_baseline(tmp_path_factory, "7aacd05")


def _base_py(base: Path, code: str, *args):
    env = dict(os.environ)
    env.pop("PRINT_EDIT_HOME", None)
    env["PYTHONPATH"] = str(base / "src")
    return subprocess.run([sys.executable, "-c", code, *map(str, args)], env=env, cwd=str(base),
                          capture_output=True, text=True, timeout=600)


_CLI_CODE = "import sys;from print_edit.cli import main;sys.exit(main(sys.argv[1:]))"


def base_cli(base, *args):
    r = _base_py(base, _CLI_CODE, *args)
    return r.returncode, r.stdout, r.stderr


_API_CODE = """
import sys, json
from pathlib import Path
from fastapi.testclient import TestClient
from print_edit.api.app import create_app
from print_edit.home import Home
root, method, path = sys.argv[1:4]
c = TestClient(create_app(Home(Path(root))), raise_server_exceptions=False)
r = c.request(method, path)
try:
    j = r.json()
except Exception:
    j = None
print(json.dumps({"status": r.status_code, "json": j}))
"""

_PUT_CODE = """
import sys, json
from pathlib import Path
from fastapi.testclient import TestClient
from print_edit.api.app import create_app
from print_edit.home import Home
root, mod = sys.argv[1:3]
mod = json.loads(mod)
c = TestClient(create_app(Home(Path(root))), raise_server_exceptions=False)
cfg = c.get("/api/config").json()
for k, v in mod.items():
    cfg[k].update(v)
r = c.put("/api/config", json=cfg)
print(json.dumps({"status": r.status_code, "json": r.json()}))
"""


def base_api(base, root, method, path):
    r = _base_py(base, _API_CODE, root, method, path)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def base_put(base, root, mod):
    r = _base_py(base, _PUT_CODE, root, json.dumps(mod))
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------- PDF 解析（pypdfium2。内容ストリームの m・l・S 相当）
class Seg:
    __slots__ = ("t", "w", "gray", "dash", "idx")

    def __init__(self, t, w, gray, dash, idx):
        self.t, self.w, self.gray, self.dash, self.idx = t, w, gray, dash, idx

    def __repr__(self):
        return f"Seg({tuple(round(v, 3) for v in self.t)}, w={self.w:.3f}, g={self.gray}, d={self.dash})"


def read_pdf(pdf):
    """(線分のリスト, 画像オブジェクトの順位のリスト)。座標は mm（x = pt×25.4/72、y = 297 − pt×25.4/72）。
    1 つのパスに複数の m/l があっても 1 本ずつに分ける。"""
    doc = pdfium.PdfDocument(str(pdf))
    try:
        page = doc[0]
        segs, imgs = [], []
        for i, o in enumerate(page.get_objects()):
            if o.type == pdfraw.FPDF_PAGEOBJ_IMAGE:
                imgs.append(i)
                continue
            if o.type != pdfraw.FPDF_PAGEOBJ_PATH:
                continue
            a, b, c, d, e, f = o.get_matrix().get()
            n = pdfraw.FPDFPath_CountSegments(o.raw)
            pts = []
            for k in range(n):
                sg = pdfraw.FPDFPath_GetPathSegment(o.raw, k)
                x, y = ctypes.c_float(), ctypes.c_float()
                pdfraw.FPDFPathSegment_GetPoint(sg, x, y)
                pts.append((pdfraw.FPDFPathSegment_GetType(sg), a * x.value + c * y.value + e, b * x.value + d * y.value + f))
            w = ctypes.c_float()
            pdfraw.FPDFPageObj_GetStrokeWidth(o.raw, w)
            r_, g_, b_, a_ = (ctypes.c_uint() for _ in range(4))
            pdfraw.FPDFPageObj_GetStrokeColor(o.raw, r_, g_, b_, a_)
            nd = pdfraw.FPDFPageObj_GetDashCount(o.raw)
            dash = ()
            if nd:
                arr = (ctypes.c_float * nd)()
                pdfraw.FPDFPageObj_GetDashArray(o.raw, arr, nd)
                dash = tuple(arr)
            cur = None
            for typ, px, py in pts:
                if typ == pdfraw.FPDF_SEGMENT_MOVETO:
                    cur = (px, py)
                elif typ == pdfraw.FPDF_SEGMENT_LINETO and cur is not None:
                    t = (cur[0] * PT2MM, 297 - cur[1] * PT2MM, px * PT2MM, 297 - py * PT2MM)
                    segs.append(Seg(t, w.value, r_.value, dash, i))
                    cur = (px, py)
        return segs, imgs
    finally:
        doc.close()


def raster(pdf, dpi=300):
    doc = pdfium.PdfDocument(str(pdf))
    try:
        return doc[0].render(scale=dpi / 72).to_pil().convert("RGB")
    finally:
        doc.close()


def same_image(a: Image.Image, b: Image.Image) -> bool:
    return a.size == b.size and ImageChops.difference(a, b).getbbox() is None


def _close(a, b, directed, tol):
    if all(abs(p - q) <= tol for p, q in zip(a, b)):
        return True
    if not directed:
        r = (b[2], b[3], b[0], b[1])
        return all(abs(p - q) <= tol for p, q in zip(a, r))
    return False


def match(actual, expected, directed=False, tol=TOL):
    """多重集合として照合。(expected のうち見つからないもの, actual のうち余るもの) を返す。"""
    pool = [tuple(t) for t in actual]
    missing = []
    for e in expected:
        for i, a in enumerate(pool):
            if _close(a, e, directed, tol):
                del pool[i]
                break
        else:
            missing.append(tuple(e))
    return missing, pool


def assert_same(actual, expected, directed=False, tol=TOL, what=""):
    missing, extra = match(actual, expected, directed, tol)
    assert not missing and not extra, (
        f"{what} 不一致: 期待にあって無い {len(missing)}件 {missing[:6]} / 余り {len(extra)}件 {extra[:6]}"
        f"（実際 {len(list(actual))}件・期待 {len(list(expected))}件）")


def assert_contains(actual, expected, directed=False, tol=TOL, what=""):
    missing, _ = match(actual, expected, directed, tol)
    assert not missing, f"{what} 含まれていない: {missing}"


def layout_json(pdf):
    return json.loads(Path(str(pdf) + ".layout.json").read_text(encoding="utf-8"))


def mark_tuples(marks):
    return [(m["x1"], m["y1"], m["x2"], m["y2"]) for m in marks]


def inner_segs(pdf, layout=None):
    """PDF の線分から、layout.json の marks（外周）に当たるものを除いた残り＝内側の線。"""
    segs, imgs = read_pdf(pdf)
    lay = layout if layout is not None else layout_json(pdf)
    pool = list(segs)
    for m in mark_tuples(lay["marks"]):
        for i, s in enumerate(pool):
            if _close(s.t, m, False, TOL):
                del pool[i]
                break
        else:
            raise AssertionError(f"layout.json の marks {m} に当たる PDF の線が無い")
    return pool, segs, imgs


def tuples(segs):
    return [s.t for s in segs]


# ---------------------------------------------------------------- 期待セット（正本「内側の線の期待セット」）
def s10(L=3.0):
    out = []
    for y in (66, 121, 176, 231):
        out += [(105, y, 105, y - L), (105, y, 105, y + L), (105, y, 105 - L, y), (105, y, 105 + L, y)]
    for y in (66, 121, 176, 231):
        out.append((14, y, 14 + L, y))
        out.append((196, y, 196 - L, y))
    out += [(105, 11, 105, 11 + L), (105, 286, 105, 286 - L)]
    return out


def shift(S, dx, dy):
    return [(a + dx, b + dy, c + dx, d + dy) for a, b, c, d in S]


S3C = [(105, 11, 105, 14), (105, 66, 105, 63), (105, 66, 105, 69), (105, 66, 102, 66), (105, 66, 108, 66),
       (105, 121, 105, 118), (14, 66, 17, 66), (196, 66, 193, 66)]
S3LT = [(91, 0, 91, 3), (91, 55, 91, 52), (91, 55, 91, 58), (91, 55, 88, 55),
        (91, 55, 94, 55), (91, 110, 91, 107), (0, 55, 3, 55), (182, 55, 179, 55)]
S2C = [(105, 11, 105, 14), (105, 66, 105, 63)]
S10 = s10(3.0)
S10LT = shift(S10, -14, -11)   # 左上の紙端を原点にする
S10RB = shift(S10, 9.8, 6.8)     # x: 14→23.8・105→114.8・196→205.8、y: 11→17.8 … 286→292.8

LAYOUT_KEYS = {"paper_mm", "printable_mm", "capacity", "columns", "rows", "card_rotated", "slots", "marks"}


def impose(tmp_path, diff, files, name="out.pdf"):
    """impose を実行して (PDF パスのリスト, stdout, stderr) を返す。Home・出力先は新しい空ディレクトリ。"""
    root = mkhome(tmp_path, diff)
    outdir = tmp_path / f"o_{root.name}"
    outdir.mkdir(parents=True)
    out = outdir / name
    code, so, se = cli(["impose", *files, "--out", out, "--home", root])
    assert code == 0, f"impose 失敗 code={code} {se}"
    pdfs = [out] + sorted(outdir.glob(f"{out.stem}-*.pdf"))
    return pdfs, so, se


def preview(tmp_path, diff):
    root = mkhome(tmp_path, diff)
    r = client(root).get("/api/layout/preview")
    assert r.status_code == 200, r.text
    return r.json()


def inner_marks_of(resp):
    assert "inner_marks" in resp, f"inner_marks のキーが無い（応答キー {sorted(resp)}）"
    for m in resp["inner_marks"]:
        assert set(m) == {"x1", "y1", "x2", "y2"}, f"inner_marks 要素のキー {sorted(m)}"
    return mark_tuples(resp["inner_marks"])


def is_vertical(t):
    return abs(t[0] - t[2]) < 1e-6


def is_horizontal(t):
    return abs(t[1] - t[3]) < 1e-6


def ingest(tmp_path, diff, fixture_names):
    """inbox に fixtures の画像を置いて ingest。(root, job 出力, [シート PDF のパス]) を返す。"""
    root = mkhome(tmp_path, mg({"intake": {"stable_wait_s": 0}}, diff))
    for n in fixture_names:
        src = FX / n
        assert src.is_file(), f"fixture が無い: {src}（make_fixtures.py の生成物。再生成はしない）"
        shutil.copy(src, root / "inbox" / n)
    code, so, se = cli(["ingest", "--home", root])
    assert code == 0, f"ingest 失敗 code={code} {se} {so}"
    res = json.loads(so)
    assert res and res[0].get("status") == "ok", f"ingest の結果が ok でない: {res}"
    jid = res[0]["job_id"]
    sheets = sorted((root / "jobs" / str(jid) / "sheets").glob("*.pdf"))
    return root, jid, sheets


# ================================================================ 正常系
def test_N01_defaults_zero_and_point1(tmp_path):
    """N-01 [M1,M3] 既定値が 0 / 0.1。根拠: TC N-01 期待結果列"""
    c = client(mkhome(tmp_path))
    lay = get_preset_data(c)["layout"]
    assert lay["inner_mark_length_mm"] == 0
    assert lay["inner_mark_width_mm"] == 0.1


def test_N02_put_saves_and_get_shows(tmp_path):
    """N-02 [M2,M3] 保存値が GET と再起動後の既定プリセットに出る。根拠: TC N-02 操作・期待結果列"""
    root = mkhome(tmp_path)
    c = client(root)
    cfg = get_preset_data(c)
    cfg["layout"]["inner_mark_length_mm"] = 3
    cfg["layout"]["inner_mark_width_mm"] = 0.2
    assert put_preset_data(c, cfg).status_code == 200
    lay = get_preset_data(c)["layout"]
    assert lay["inner_mark_length_mm"] == 3 and lay["inner_mark_width_mm"] == 0.2
    f = get_preset_data(client(root))["layout"]
    assert f["inner_mark_length_mm"] == 3 and f["inner_mark_width_mm"] == 0.2


def _layout_def(schema):
    ref = schema["properties"]["layout"]
    name = (ref.get("$ref") or ref["allOf"][0]["$ref"]).split("/")[-1]
    return schema["$defs"][name]["properties"]


def test_N03_schema_ranges_api_and_cli_agree(tmp_path):
    """N-03 [M1,M4] JSON Schema に範囲が出る（API と CLI が同じ）。根拠: TC N-03 期待結果列"""
    root = mkhome(tmp_path)
    api = _layout_def(client(root).get("/api/presets/schema").json())
    code, so, se = cli(["config", "schema", "--home", root])
    assert code == 0, se
    cl = _layout_def(json.loads(so))
    for props in (api, cl):
        L, W = props["inner_mark_length_mm"], props["inner_mark_width_mm"]
        assert L["minimum"] == 0 and L["maximum"] == 10 and L["title"] == "名刺間トンボ長さ(mm)", L
        assert W["exclusiveMinimum"] == 0 and W["title"] == "名刺間トンボ線幅(mm)", W
    assert api["inner_mark_length_mm"] == cl["inner_mark_length_mm"]
    assert api["inner_mark_width_mm"] == cl["inner_mark_width_mm"]


def test_N04_cli_config_show_has_two_keys(tmp_path):
    """N-04 [M3] CLI config show に 2 キーが出る。根拠: TC N-04 前提データ・期待結果列"""
    root = mkhome(tmp_path, IM(3, 0.2))
    code, so, se = cli(["config", "show", "--home", root])
    assert code == 0, se
    lay = json.loads(so)["layout"]
    assert lay["inner_mark_length_mm"] == 3 and lay["inner_mark_width_mm"] == 0.2


def test_N05_old_config_without_keys_reads_default_and_saves_keys(tmp_path):
    """N-05 [M3,M5] 2 キー無しの既存 config.json を読む。根拠: TC N-05 前提データ・期待結果列"""
    root = mkhome(tmp_path, {"layout": {"gap_x_mm": 0}})
    cfgp = root / "config.json"
    legacy = cfgp.read_bytes()
    c = client(root)
    assert (root / "config.json.bak").read_bytes() == legacy
    before = cfgp.read_bytes()
    cfg = get_preset_data(c)
    assert cfg["layout"]["inner_mark_length_mm"] == 0 and cfg["layout"]["inner_mark_width_mm"] == 0.1
    assert cfgp.read_bytes() == before, "GET だけで config.json が変わった"
    assert put_preset_data(c, cfg).status_code == 200
    f = get_preset_data(client(root))["layout"]
    assert "inner_mark_length_mm" in f and "inner_mark_width_mm" in f


def test_N06_put_without_keys_returns_default(tmp_path):
    """N-06 [M2,M8] キーを省いた PUT は既定に戻る。根拠: TC N-06 操作・期待結果列"""
    c = client(mkhome(tmp_path, IM(3, 0.2)))
    cfg = get_preset_data(c)
    del cfg["layout"]["inner_mark_length_mm"]
    del cfg["layout"]["inner_mark_width_mm"]
    assert put_preset_data(c, cfg).status_code == 200
    lay = get_preset_data(c)["layout"]
    assert lay["inner_mark_length_mm"] == 0 and lay["inner_mark_width_mm"] == 0.1


def test_N07_readme_notes_restart_and_old_version():
    """N-07 [M7,M8,M26] README に旧版の注記と serve 再起動の注記がある。根拠: TC N-07 期待結果列"""
    lines = (REPO / "README.md").read_text(encoding="utf-8").splitlines()
    assert any("再起動" in ln and "serve" in ln for ln in lines), "「再起動」と serve を含む行が無い"
    assert any("旧版" in ln and "config.json" in ln for ln in lines), "「旧版」と config.json を含む行が無い"


def test_N08_readme_describes_inner_marks():
    """N-08 [M26] README に名刺間トンボの説明がある。根拠: TC N-08 期待結果列"""
    text = (REPO / "README.md").read_text(encoding="utf-8")
    lines = text.splitlines()
    assert "layout.inner_mark_length_mm" in text, "layout.inner_mark_length_mm が README に無い"
    assert "layout.inner_mark_width_mm" in text, "layout.inner_mark_width_mm が README に無い"
    i = next(k for k, ln in enumerate(lines) if "inner_mark_length_mm" in ln)
    win = "\n".join(lines[max(0, i - 20): i + 20])
    assert re.search(r"既定[^\n]{0,12}0", win), "既定 0 の記述が無い"
    assert "推奨" in win and "3mm" in win, "推奨 3mm の記述が無い"
    assert "線幅の半分" in win and "縁" in win, "線幅の半分が縁に残る旨が無い"


def test_N09_preview_inner_marks_equal_S10(tmp_path):
    """N-09 [M9,M10,M16,M17] プレビューの inner_marks が S10 と一致。根拠: TC N-09 期待結果列・S10 の定義"""
    got = inner_marks_of(preview(tmp_path, IM(3)))
    assert len(got) == 26
    assert_same(got, S10, directed=True, tol=1e-6, what="inner_marks")
    assert {round(t[0], 6) for t in got if is_vertical(t)} == {105}
    assert all(round(v, 6) == v for t in got for v in t), "座標が小数 7 桁以上"
    corners = {(14, 11), (14, 286), (196, 11), (196, 286)}
    assert not [t for t in got if any(abs(t[0] - cx) < 1e-6 and abs(t[1] - cy) < 1e-6 for cx, cy in corners)]


def test_N10_inner_marks_not_in_marks(tmp_path):
    """N-10 [M9,M16] inner_marks は marks に入らず、外周トンボは L=0 と同じ。根拠: TC N-10 期待結果列"""
    r3 = preview(tmp_path, IM(3))
    r0 = preview(tmp_path, IM(0))
    assert len(r3["marks"]) == 18
    assert_same(mark_tuples(r3["marks"]), mark_tuples(r0["marks"]), directed=True, tol=1e-6, what="marks")
    hit, _ = match(mark_tuples(r3["marks"]), S10)
    assert len(hit) == len(S10), "marks に S10 の線が含まれている"
    assert "inner_marks" in r3


def test_N11_pdf_lines_equal_S10_and_preview(tmp_path, imgs):
    """N-11 [M9,M14,M16] PDF の線が S10 とプレビューに一致。根拠: TC N-11 期待結果列"""
    pdfs, _, _ = impose(tmp_path, IM(3), imgs["white10"])
    segs, _ = read_pdf(pdfs[0])
    assert len(segs) == 44
    inner, _, _ = inner_segs(pdfs[0])
    assert_same(tuples(inner), S10, what="内側")
    pv = inner_marks_of(preview(tmp_path, IM(3)))
    assert_same(tuples(inner), pv, what="PDF 内側 vs プレビュー")
    base_pdfs, _, _ = impose(tmp_path, None, imgs["white10"])
    base_segs, _ = read_pdf(base_pdfs[0])
    assert len(base_segs) == 18
    outer, _ = match(tuples(segs), tuples(base_segs))
    assert not outer, "外周 18 本が L=0 の PDF と一致しない"


def test_N12_inner_width_and_gray(tmp_path, imgs):
    """N-12 [M14] 内側の線の太さ・濃さ。根拠: TC N-12 期待結果列"""
    diff = mg(IM(3, 0.2), {"layout": {"mark_width_mm": 0.1, "mark_gray": 128}})
    pdfs, _, _ = impose(tmp_path, diff, imgs["white10"])
    inner, segs, _ = inner_segs(pdfs[0])
    assert len(inner) == 26 and len(segs) == 44
    for s in inner:
        assert abs(s.w - PT_02MM) < 0.01 and s.gray == 128, s
    outer = [s for s in segs if s not in inner]
    assert len(outer) == 18
    for s in outer:
        assert abs(s.w - PT_01MM) < 0.01 and s.gray == 128, s


def test_N13_not_hidden_under_card_image(tmp_path, imgs):
    """N-13 [M14] カード画像の下に隠れない（描画順と画素）。根拠: TC N-13 操作・期待結果列"""
    pdfs, _, _ = impose(tmp_path, IM(3, 0.2), imgs["white10"])
    inner, _, image_idx = inner_segs(pdfs[0])
    assert image_idx and len(inner) == 26
    assert max(image_idx) < min(s.idx for s in inner), "画像描画が内側の線より後にある"
    pdf0, _, _ = impose(tmp_path, None, imgs["white10"])
    win = (1239, 761, 1242, 764)
    lo3 = raster(pdfs[0]).convert("L").crop(win).getextrema()[0]
    lo0 = raster(pdf0[0]).convert("L").crop(win).getextrema()[0]
    assert lo3 < 200, f"L=3 の周囲に 200 未満の画素が無い（最小 {lo3}）"
    assert lo0 == 255, f"L=0 の同じ位置が 255 でない（最小 {lo0}）"


def test_N14_outer_zero_inner_only_with_style(tmp_path, imgs):
    """N-14 [M14] 外周トンボが 0 本でも内側だけ描かれ、線種・濃さが効く。根拠: TC N-14 期待結果列"""
    diff = mg(IM(3), {"layout": {"mark_length_mm": 0, "mark_gray": 128, "mark_style": "dashed",
                                  "mark_dash_mm": 2, "mark_gap_mm": 1}})
    pdfs, _, _ = impose(tmp_path, diff, imgs["white10"])
    assert layout_json(pdfs[0])["marks"] == []
    segs, _ = read_pdf(pdfs[0])
    assert len(segs) == 26
    assert_same(tuples(segs), S10, what="S10")
    for s in segs:
        assert s.gray == 128, s
        assert len(s.dash) == 2 and abs(s.dash[0] - PT_2MM) < 0.01 and abs(s.dash[1] - PT_1MM) < 0.01, s


def test_N15_mark_enabled_false_still_draws_inner(tmp_path, imgs):
    """N-15（11.8b で期待値差し替え）[M9,M14,M16,M29] mark_enabled=false（inner_mark_enabled は既定 true）でも内側は描く。
    (1) inner_marks 26 件で S10 と一致・marks は 0 件 (2) PDF の線分 26 本（S10）・layout.json の marks は []。
    根拠: spec_11_8b_tc.md 変更表 N-15"""
    diff = mg(IM(3), {"layout": {"mark_enabled": False, "inner_mark_enabled": True}})
    pv = preview(tmp_path, diff)
    got = inner_marks_of(pv)
    assert len(got) == 26
    assert_same(got, S10, directed=True, tol=1e-6, what="inner_marks")
    assert pv["marks"] == []
    pdfs, _, _ = impose(tmp_path, diff, imgs["white10"])
    segs, _ = read_pdf(pdfs[0])
    assert len(segs) == 26
    assert_same(tuples(segs), S10, what="S10")
    assert layout_json(pdfs[0])["marks"] == []


def test_N16_dashed_pdf_starts_at_intersection(tmp_path, imgs):
    """N-16 [M14,M19] dashed の PDF: 破線の値と、各線が交点側から始まる。根拠: TC N-16 期待結果列"""
    dashed = {"layout": {"mark_style": "dashed", "mark_dash_mm": 2, "mark_gap_mm": 1}}
    pdfs, _, _ = impose(tmp_path, mg(IM(3), dashed), imgs["white10"])
    inner, segs, _ = inner_segs(pdfs[0])
    assert len(inner) == 26
    assert_same(tuples(inner), S10, directed=True, what="内側（始点つき）")
    for s in inner:
        assert len(s.dash) == 2 and abs(s.dash[0] - PT_2MM) < 0.01 and abs(s.dash[1] - PT_1MM) < 0.01, s
    base, _, _ = impose(tmp_path, dashed, imgs["white10"])
    bsegs, _ = read_pdf(base[0])
    miss, _ = match([s.t for s in segs if s not in inner], tuples(bsegs))
    assert not miss, "外周 18 本の位置が L=0 の PDF と違う"


def test_N17_n3_center_lines(tmp_path, imgs):
    """N-17 [M9,M23,M24] n=3（中央）の線（空きスロットの分も含む）。根拠: TC N-17・S3c"""
    pdfs, _, _ = impose(tmp_path, IM(3), imgs["white3"])
    inner, _, _ = inner_segs(pdfs[0])
    assert len(inner) == 8
    assert_same(tuples(inner), S3C, what="S3c")


def test_N18_n3_left_top(tmp_path, imgs):
    """N-18 [M9] n=3・left/top の線。根拠: TC N-18・S3lt"""
    al = {"layout": {"align_x": "left", "align_y": "top"}}
    pdfs, _, _ = impose(tmp_path, mg(al, IM(3)), imgs["white3"])
    inner, segs, _ = inner_segs(pdfs[0])
    assert len(inner) == 8
    assert_same(tuples(inner), S3LT, what="S3lt")
    assert_contains(tuples(inner), [(0, 55, 3, 55), (91, 0, 91, 3)], what="境界ちょうどの線")
    base, _, _ = impose(tmp_path, al, imgs["white3"])
    bsegs, _ = read_pdf(base[0])
    miss, _ = match([s.t for s in segs if s not in inner], tuples(bsegs))
    assert not miss and len(segs) - 8 == len(bsegs), "外周が L=0 と違う"


def test_N19_n10_left_top(tmp_path, imgs):
    """N-19 [M9,M16] n=10・left/top。根拠: TC N-19・S10lt"""
    diff = mg({"layout": {"align_x": "left", "align_y": "top"}}, IM(3))
    pdfs, _, _ = impose(tmp_path, diff, imgs["white10"])
    inner, _, _ = inner_segs(pdfs[0])
    assert_same(tuples(inner), S10LT, what="S10lt")
    pv = inner_marks_of(preview(tmp_path, diff))
    assert_same(tuples(inner), pv, what="PDF vs プレビュー")


def test_N20_n10_right_bottom(tmp_path, imgs):
    """N-20 [M9,M16] n=10・right/bottom。根拠: TC N-20・S10rb"""
    diff = mg({"layout": {"align_x": "right", "align_y": "bottom"}}, IM(3))
    pdfs, _, _ = impose(tmp_path, diff, imgs["white10"])
    inner, _, _ = inner_segs(pdfs[0])
    assert_same(tuples(inner), S10RB, what="S10rb")
    assert_contains(tuples(inner), [(205.8, 72.8, 202.8, 72.8), (114.8, 292.8, 114.8, 289.8)])
    pv = inner_marks_of(preview(tmp_path, diff))
    assert_same(tuples(inner), pv, what="PDF vs プレビュー")


def test_N21_n2_one_row(tmp_path, imgs):
    """N-21 [M9] n=2（1 行）の線。根拠: TC N-21・S2c"""
    pdfs, _, _ = impose(tmp_path, IM(3), imgs["white3"][:2])
    inner, _, _ = inner_segs(pdfs[0])
    assert len(inner) == 2
    assert_same(tuples(inner), S2C, what="S2c")
    assert not [t for t in tuples(inner) if is_horizontal(t)], "横の線がある"


def test_N22_scale_x_length_and_position(tmp_path):
    """N-22 [M9,M16] scale_x=1.05 の長さ・位置。根拠: TC N-22 期待結果列"""
    got = inner_marks_of(preview(tmp_path, mg({"print": {"scale_x": 1.05}}, IM(3))))
    assert len(got) == 26
    assert_contains(got, [(105, 66, 101.85, 66), (105, 66, 108.15, 66), (9.45, 66, 12.6, 66), (105, 66, 105, 63)],
                    directed=True, tol=1e-6)
    for t in got:
        ln = abs(t[0] - t[2]) if is_horizontal(t) else abs(t[1] - t[3])
        want = 3.15 if is_horizontal(t) else 3
        assert abs(ln - want) < 1e-6, (t, ln)


def test_N23_width_and_dash_not_scaled(tmp_path, imgs):
    """N-23 [M14] 線幅・破線は scale で拡縮しない。根拠: TC N-23 期待結果列"""
    base_cfg = mg({"layout": {"mark_style": "dashed", "mark_dash_mm": 2, "mark_gap_mm": 1}}, IM(3, 0.2))
    sc = mg(base_cfg, {"print": {"scale_x": 1.05, "scale_y": 1.05}})
    pdfs, _, _ = impose(tmp_path, sc, imgs["white10"])
    inner, _, _ = inner_segs(pdfs[0])
    assert inner, "内側の線が 0 本"
    for s in inner:
        assert abs(s.w - PT_02MM) < 0.01, s
        assert len(s.dash) == 2 and abs(s.dash[0] - PT_2MM) < 0.01 and abs(s.dash[1] - PT_1MM) < 0.01, s
    ref, _, _ = impose(tmp_path, base_cfg, imgs["white10"])
    rin, _, _ = inner_segs(ref[0])
    assert {(round(s.w, 3), tuple(round(d, 3) for d in s.dash)) for s in inner} == \
           {(round(s.w, 3), tuple(round(d, 3) for d in s.dash)) for s in rin}


def test_N24_gap_x2_two_cut_lines_not_merged(tmp_path):
    """N-24 [M9,M11,M16] gap_x=2: 境目の 2 本の線に別々の線を引く。根拠: TC N-24 期待結果列"""
    got = inner_marks_of(preview(tmp_path, mg({"layout": {"gap_x_mm": 2}}, IM(3))))
    assert len(got) == 44
    row66 = [t for t in got if is_horizontal(t) and abs(t[1] - 66) < 1e-6]
    exp = [(13, 66, 16, 66), (104, 66, 101, 66), (104, 66, 107, 66), (106, 66, 103, 66), (106, 66, 109, 66),
           (197, 66, 194, 66)]
    assert_same(row66, exp, directed=True, tol=1e-6, what="y=66 の横の線")


def test_N25_gap_xy2_count(tmp_path):
    """N-25 [M9,M11,M16] gap_x=2・gap_y=2 の件数。根拠: TC N-25 期待結果列"""
    root = mkhome(tmp_path, mg({"layout": {"gap_x_mm": 2, "gap_y_mm": 2}}, IM(3)))
    c = client(root)
    assert c.get("/api/capacity").json()["capacity"] == 10
    got = inner_marks_of(c.get("/api/layout/preview").json())
    assert len(got) == 84
    assert len([t for t in got if is_vertical(t)]) == 36 and len([t for t in got if is_horizontal(t)]) == 48
    assert_contains(got, [(104, 62, 104, 59), (104, 62, 104, 65), (104, 64, 104, 61), (104, 64, 104, 67)],
                    directed=True, tol=1e-6)


def test_N26_gap_dashed_count_and_endpoints(tmp_path, imgs):
    """N-26 [M11,M12,M14] gap > 0 × dashed: 本数と端点だけを判定。根拠: TC N-26 期待結果列"""
    diff = mg({"layout": {"gap_x_mm": 2, "mark_style": "dashed", "mark_dash_mm": 2, "mark_gap_mm": 1}}, IM(3))
    pdfs, _, _ = impose(tmp_path, diff, imgs["white10"])
    inner, _, _ = inner_segs(pdfs[0])
    assert len(inner) == 44
    assert_contains(tuples(inner), [(104, 66, 107, 66), (106, 66, 103, 66)], directed=True, what="端点")
    X = (13, 104, 106, 197)
    Y = (11, 66, 121, 176, 231, 286)
    for s in inner:
        assert any(abs(s.t[0] - x) <= TOL and abs(s.t[1] - y) <= TOL for x in X for y in Y), f"始点が交点側でない {s}"


@pytest.mark.skip(reason="N-27（11.8b で期待値差し替え）: 管理画面の SVG（DOM）でしか確認できない。browser-test で判定する")
def test_N27_slot_diagram_draws_inner_solid():
    """N-27 [M18,M33] スロット図に内側の線が描かれる（solid）。新: 内側 26 本の stroke-width は 0.35、外周 18 本は 0.2
    （W=0.5 は反映されない）。line 総数 44・座標・stroke・dasharray なしは旧のまま。根拠: spec_11_8b_tc.md 変更表 N-27"""


@pytest.mark.skip(reason="管理画面の SVG（DOM）でしか確認できない。browser-test で判定する")
def test_N28_slot_diagram_dashed_starts_at_intersection():
    """N-28 [M18,M19] スロット図の dashed。根拠: TC N-28（SVG の line・stroke-dasharray）"""


def test_N29_partial_preview_matches_pdf_S10(tmp_path, imgs):
    """N-29 [M14,M16,M17,M18] 部分判定: inner_marks と PDF の内側 26 本が ±0.01 mm で一致（SVG 部分は browser-test）。根拠: TC N-29"""
    pdfs, _, _ = impose(tmp_path, IM(3), imgs["white10"])
    inner, _, _ = inner_segs(pdfs[0])
    pv = inner_marks_of(preview(tmp_path, IM(3)))
    assert len(inner) == 26 and len(pv) == 26
    assert_same(tuples(inner), pv, what="PDF vs inner_marks")


@pytest.mark.skip(reason="管理画面の設定フォーム（DOM）でしか確認できない。browser-test で判定する")
def test_N30_settings_screen_shows_two_fields():
    """N-30 [M20] 設定画面の「面付け」に 2 項目が出る。根拠: TC N-30（画面のラベルと入力）"""


@pytest.mark.skip(reason="管理画面の保存操作と再読み込み（DOM）でしか確認できない。browser-test で判定する")
def test_N31_settings_saved_survives_reload():
    """N-31 [M20] 設定画面で保存して再読み込みしても残る。根拠: TC N-31"""


@pytest.mark.skip(reason="N-32（11.8b で期待値差し替え）: 管理画面の入力欄の並び順（DOM）でしか確認できない。browser-test で判定する")
def test_N32_two_fields_at_end_of_layout_section():
    """N-32 [M21,M35] 新: 「名刺間トンボを描く」「名刺間トンボの形」が layout 節の最後の 2 項目（順は問わない）。
    「名刺間トンボ長さ(mm)」「名刺間トンボ線幅(mm)」は既存項目より後ろで、上記 2 項目より前。根拠: spec_11_8b_tc.md 変更表 N-32"""


def _assert_layout_keys(lay):
    assert set(lay) == LAYOUT_KEYS, f"layout.json のキー {sorted(lay)}"


def test_N33_ingest_per_scan_3_cards(tmp_path):
    """N-33 [M13,M23] ingest（per_scan）で 3 枚のシートの線が決まる。根拠: TC N-33 期待結果列・S3c"""
    root, jid, sheets = ingest(tmp_path, IM(3), ["a3_three_col.png"])
    assert len(sheets) == 1
    inner, _, _ = inner_segs(sheets[0], json.loads(sheets[0].with_suffix(".layout.json").read_text(encoding="utf-8")))
    assert len(inner) == 8
    assert_same(tuples(inner), S3C, what="S3c")
    _assert_layout_keys(json.loads(sheets[0].with_suffix(".layout.json").read_text(encoding="utf-8")))


def test_N34_ingest_duplicate_fills_10(tmp_path):
    """N-34 [M23] ingest（duplicate）で 10 枠を埋めたシート。根拠: TC N-34 期待結果列・S10"""
    diff = mg({"print": {"timing": "duplicate", "duplicate_count": None}}, IM(3))
    root, jid, sheets = ingest(tmp_path, diff, ["a3_three_col.png"])
    assert len(sheets) == 1
    lay = json.loads(sheets[0].with_suffix(".layout.json").read_text(encoding="utf-8"))
    inner, _, _ = inner_segs(sheets[0], lay)
    assert len(inner) == 26
    assert_same(tuples(inner), S10, what="S10")


def test_N35_ingest_fill_3(tmp_path):
    """N-35 [M23] ingest（fill）で枚数がたまったシート。根拠: TC N-35 期待結果列・S3c"""
    diff = mg({"print": {"timing": "fill"}, "layout": {"cards_per_sheet": 3}}, IM(3))
    root, jid, sheets = ingest(tmp_path, diff, ["a3_three_col.png"])
    assert len(sheets) == 1
    lay = json.loads(sheets[0].with_suffix(".layout.json").read_text(encoding="utf-8"))
    inner, _, _ = inner_segs(sheets[0], lay)
    assert len(inner) == 8
    assert_same(tuples(inner), S3C, what="S3c")


def test_N36_held_sheet_keeps_creation_time_settings(tmp_path, lp):
    """N-36 [M6,M23] held シートは保留作成時の設定のまま印刷される。根拠: TC N-36 操作・期待結果列"""
    diff = mg({"print": {"output": "lp", "auto_print": False, "printer_name": "Q1"}}, IM(3))
    root, jid, sheets = ingest(tmp_path, diff, ["a3_three_col.png"])
    assert len(sheets) == 1
    pdf = sheets[0]
    lay = json.loads(pdf.with_suffix(".layout.json").read_text(encoding="utf-8"))
    inner, _, _ = inner_segs(pdf, lay)
    assert len(inner) == 8
    h0 = sha(pdf)
    c = client(root)
    held = c.get("/api/sheets", params={"status": "held"}).json()
    assert len(held) == 1, held
    cfg = get_preset_data(c)
    cfg["layout"]["inner_mark_length_mm"] = 0
    assert put_preset_data(c, cfg).status_code == 200
    r = c.post(f"/api/sheets/{held[0]['id']}/print")
    assert r.status_code == 200, r.text
    assert sha(pdf) == h0, "印刷後に PDF が再生成された"
    calls = lp.calls()
    assert len(calls) == 1, calls
    sent = Path(calls[0].split()[-1])
    sinner, _, _ = inner_segs(sent, lay)
    assert len(sinner) == 8, "送られた PDF の内側が 8 本でない"


def test_N37_impose_multi_sheet(tmp_path, imgs):
    """N-37 [M13,M24] impose（複数シート）で各シートの n ごとに線が決まる。根拠: TC N-37 期待結果列"""
    files = imgs["white10"] + imgs["white10"][:2]
    pdfs, so, se = impose(tmp_path, IM(3), files)
    assert len(pdfs) == 2 and pdfs[1].name == "out-2.pdf"
    i1, _, _ = inner_segs(pdfs[0])
    i2, _, _ = inner_segs(pdfs[1])
    assert_same(tuples(i1), S10, what="out.pdf")
    assert_same(tuples(i2), S2C, what="out-2.pdf")
    for p in pdfs:
        assert "inner_marks" not in Path(str(p) + ".layout.json").read_text(encoding="utf-8")
    assert "inner_marks" not in so and "inner_marks" not in se


def test_N38_layout_json_independent_of_L(tmp_path, imgs):
    """N-38 [M13] layout.json は L の値によらず変わらない。根拠: TC N-38 期待結果列"""
    p3, _, _ = impose(tmp_path, IM(3), imgs["white10"])
    p0, _, _ = impose(tmp_path, IM(0), imgs["white10"])
    l3, l0 = layout_json(p3[0]), layout_json(p0[0])
    assert l3 == l0
    _assert_layout_keys(l3)
    assert l3["marks"] and all(set(m) == {"x1", "y1", "x2", "y2"} for m in l3["marks"])


def test_N39_created_pdf_and_reprint_unchanged(tmp_path, lp):
    """N-39 [M6] 作成済みシート PDF と reprint は変わらない。根拠: TC N-39 操作・期待結果列"""
    diff = mg(IM(0), {"print": {"output": "lp", "printer_name": "Q1", "auto_print": True}})
    root, jid, sheets = ingest(tmp_path, diff, ["a3_three_col.png"])
    assert len(lp.calls()) == 1
    lp.clear()
    pdf = sheets[0]
    h0 = sha(pdf)
    c = client(root)
    cfg = get_preset_data(c)
    cfg["layout"]["inner_mark_length_mm"] = 3
    assert put_preset_data(c, cfg).status_code == 200
    sheet, = c.get(f"/api/jobs/{jid}").json()["sheets"]
    result = c.post(f"/api/sheets/{sheet['id']}/reprint")
    assert result.status_code == 200, result.text
    assert result.json()["sent"] is True
    call, = lp.calls()
    assert Path(call.split()[-1]).samefile(pdf)
    assert sha(pdf) == h0
    lay = json.loads(pdf.with_suffix(".layout.json").read_text(encoding="utf-8"))
    inner, _, _ = inner_segs(pdf, lay)
    assert len(inner) == 0


def test_N40_db_schema_unchanged(tmp_path, base_src):
    """N-40 トンボ用の列を増やさない。旧列の型・制約・順序を保ち、M7/M19の追加列だけを許す。"""
    def schema(root):
        con = sqlite3.connect(root / "db.sqlite3")
        try:
            return {t: con.execute(f"PRAGMA table_info({t})").fetchall() for t in ("jobs", "cards", "sheets")}
        finally:
            con.close()

    root, _, _ = ingest(tmp_path, None, ["a3_three_col.png"])
    broot = mkhome(tmp_path, {"intake": {"stable_wait_s": 0}})
    shutil.copy(FX / "a3_three_col.png", broot / "inbox" / "a3_three_col.png")
    code, so, se = base_cli(base_src, "ingest", "--home", broot)
    assert code == 0, se
    current, legacy = schema(root), schema(broot)
    added = {"jobs": [], "cards": ["reg", "name", "migrated"], "sheets": ["snapshot"]}
    for table, columns in legacy.items():
        assert current[table][:len(columns)] == columns
        assert [row[1] for row in current[table][len(columns):]] == added[table]


def test_N41_regression_L0_pixels_equal_base(tmp_path, imgs, mono_base):
    """N-41 デグレ: L=0 の PDF が全画素同じ（solid・dashed。基準 7aacd05）。根拠: TC N-41 操作・期待結果列"""
    for diff in (None, {"layout": {"mark_style": "dashed"}}):
        pdfs, _, _ = impose(tmp_path, diff, imgs["img10"])
        broot = mkhome(tmp_path, diff)
        bout = tmp_path / f"b_{broot.name}"
        bout.mkdir()
        code, so, se = base_cli(mono_base, "impose", *imgs["img10"], "--out", bout / "out.pdf", "--home", broot)
        assert code == 0, se
        assert same_image(raster(pdfs[0]), raster(bout / "out.pdf")), f"全画素が一致しない（{diff}）"


def test_N42_regression_L0_width_ignored(tmp_path, imgs, mono_base):
    """N-42 デグレ: L=0 なら W を変えても同じ。根拠: TC N-42 前提データ・期待結果列"""
    pdfs, _, _ = impose(tmp_path, IM(None, 2), imgs["img10"])
    broot = mkhome(tmp_path, None)
    bout = tmp_path / f"b_{broot.name}"
    bout.mkdir()
    code, so, se = base_cli(mono_base, "impose", *imgs["img10"], "--out", bout / "out.pdf", "--home", broot)
    assert code == 0, se
    assert same_image(raster(pdfs[0]), raster(bout / "out.pdf")), "全画素が一致しない"
    a, _ = read_pdf(pdfs[0])
    b, _ = read_pdf(bout / "out.pdf")
    assert_same(tuples(a), tuples(b), what="PDF 線分")


def test_N43_partial_regression_L0_preview_layout_capacity_equal_base(tmp_path, imgs, base_src):
    """N-43 [M13,M15,M25] 部分判定: デグレ L=0 のプレビュー・layout.json・capacity が同じ（スロット図 line 18 本は browser-test）。根拠: TC N-43"""
    root = mkhome(tmp_path, None)
    broot = mkhome(tmp_path, None)
    c = client(root)
    pv = c.get("/api/layout/preview").json()
    assert "inner_marks" not in pv
    assert pv == base_api(base_src, broot, "GET", "/api/layout/preview")["json"]
    assert c.get("/api/capacity").json() == base_api(base_src, broot, "GET", "/api/capacity")["json"]
    code, so, _ = cli(["capacity", "--home", root])
    bcode, bso, _ = base_cli(base_src, "capacity", "--home", broot)
    assert code == bcode == 0 and json.loads(so) == json.loads(bso)
    pdfs, _, _ = impose(tmp_path, None, imgs["img10"])
    bout = tmp_path / "bimp"
    bout.mkdir()
    code, _, se = base_cli(base_src, "impose", *imgs["img10"], "--out", bout / "out.pdf", "--home", broot)
    assert code == 0, se
    assert layout_json(pdfs[0]) == layout_json(bout / "out.pdf")


def test_N44_capacity_unchanged_with_L3(tmp_path, base_src):
    """N-44 [M25] L>0 でも容量の出力は変わらない。根拠: TC N-44 期待結果列"""
    want = {"capacity": 10, "columns": 2, "rows": 5, "card_rotated": False}
    root = mkhome(tmp_path, IM(3))
    code, so, se = cli(["capacity", "--home", root])
    assert code == 0, se
    assert json.loads(so) == want
    assert client(root).get("/api/capacity").json() == want
    broot = mkhome(tmp_path, None)
    assert base_api(base_src, broot, "GET", "/api/capacity")["json"] == want


@pytest.mark.skip(reason="pytest 全体の再帰実行はテスト内でしない。実行 3（tests/unit 全体）と実装後の uv run pytest で確認")
def test_N45_regression_existing_tests_pass():
    """N-45 [M15] デグレ: 既存の自動テストがすべて通る。根拠: TC N-45（uv run pytest）"""


def test_N46_cps3_preview_inner_marks_match_3_sheet(tmp_path, imgs):
    """N-46 [M9,M16,M17] cps=3 のプレビューの inner_marks は 3 枚のシートの線（中央）。根拠: TC N-46 期待結果列"""
    diff = mg({"layout": {"cards_per_sheet": 3}}, IM(3))
    pv = preview(tmp_path, diff)
    got = inner_marks_of(pv)
    assert len(got) == 8
    assert_same(got, S3C, directed=True, tol=1e-6, what="S3c")
    assert not [t for t in got if any(abs(t[1] - y) < 1e-6 for y in (176, 231, 286))]
    assert pv["capacity"] == 10
    pdfs, _, _ = impose(tmp_path, diff, imgs["white3"])
    inner, _, _ = inner_segs(pdfs[0])
    assert len(inner) == 8
    assert_same(tuples(inner), got, what="PDF vs inner_marks")


def test_N47_cps3_preview_marks_match_3_sheet(tmp_path, imgs):
    """N-47 [M16,M17] cps=3 のプレビューの marks は 3 枚のシートの外周トンボと同じ配置。根拠: TC N-47 期待結果列"""
    diff = mg({"layout": {"cards_per_sheet": 3}}, IM(3))
    pv = preview(tmp_path, diff)
    pdfs, _, _ = impose(tmp_path, diff, imgs["white3"])
    lj = layout_json(pdfs[0])
    assert_same(mark_tuples(pv["marks"]), mark_tuples(lj["marks"]), directed=True, tol=1e-6, what="marks")
    hit, _ = match(mark_tuples(pv["marks"]), S3C)
    assert len(hit) == len(S3C), "marks に S3c の線が含まれている"


def test_N48_cps3_left_top_preview(tmp_path, imgs):
    """N-48 [M9,M16,M17] cps=3・left/top のプレビューの inner_marks。根拠: TC N-48 期待結果列・S3lt"""
    diff = mg({"layout": {"align_x": "left", "align_y": "top", "cards_per_sheet": 3}}, IM(3))
    got = inner_marks_of(preview(tmp_path, diff))
    assert len(got) == 8
    assert_same(got, S3LT, directed=True, tol=1e-6, what="S3lt")
    assert not [t for t in got if t[1] >= 165 - 1e-6 or t[3] >= 165 - 1e-6]
    pdfs, _, _ = impose(tmp_path, diff, imgs["white3"])
    inner, _, _ = inner_segs(pdfs[0])
    assert len(inner) == 8
    assert_same(tuples(inner), got, what="PDF vs inner_marks")


def test_N49_partial_cps3_preview_matches_pdf(tmp_path, imgs):
    """N-49（11.8b で期待値差し替え）[M16,M17,M18,M33] 部分判定: cps=3 で inner_marks 8 件と PDF の内側 8 本が一致。
    SVG 部分（内側 8 本の stroke-width 0.35・外周 0.2・line 総数 = marks 件数 + 8）は browser-test。根拠: spec_11_8b_tc.md 変更表 N-49"""
    diff = mg({"layout": {"cards_per_sheet": 3}}, IM(3, 0.5))
    got = inner_marks_of(preview(tmp_path, diff))
    pdfs, _, _ = impose(tmp_path, diff, imgs["white3"])
    inner, _, _ = inner_segs(pdfs[0])
    assert len(got) == 8 and len(inner) == 8
    assert_same(got, S3C, directed=True, tol=1e-6, what="S3c")
    assert_same(tuples(inner), got, what="PDF vs inner_marks")


def test_N50_partial_cps3_dashed_pdf_starts_at_intersection(tmp_path, imgs):
    """N-50 [M18,M19,M17] 部分判定: cps=3 の PDF の同じ線の始点が交点側（SVG 部分は browser-test）。根拠: TC N-50 期待結果列"""
    diff = mg({"layout": {"cards_per_sheet": 3, "mark_style": "dashed", "mark_dash_mm": 2, "mark_gap_mm": 1}}, IM(3))
    pdfs, _, _ = impose(tmp_path, diff, imgs["white3"])
    inner, _, _ = inner_segs(pdfs[0])
    assert_contains(tuples(inner), [(105, 66, 105, 63), (14, 66, 17, 66), (196, 66, 193, 66), (105, 121, 105, 118)],
                    directed=True, what="始点")
    got = inner_marks_of(preview(tmp_path, diff))
    assert_contains(got, [(105, 66, 105, 63), (14, 66, 17, 66), (196, 66, 193, 66), (105, 121, 105, 118)],
                    directed=True, tol=1e-6, what="プレビューの向き")


def test_N51_partial_regression_L0_cps3_preview_equals_base(tmp_path, base_src):
    """N-51 [M15,M17] 部分判定: デグレ L=0・cps=3 のプレビュー応答が基準と同じ（SVG の line 総数は browser-test）。根拠: TC N-51"""
    diff = {"layout": {"cards_per_sheet": 3}}
    pv = preview(tmp_path, diff)
    assert "inner_marks" not in pv
    broot = mkhome(tmp_path, diff)
    assert pv == base_api(base_src, broot, "GET", "/api/layout/preview")["json"]


# ================================================================ 異常系
def _put_with(tmp_path, over, diff=None):
    root = mkhome(tmp_path, diff)
    c = client(root)
    cfg = get_preset_data(c)
    cfg["layout"].update(over)
    return root, c, put_preset_data(c, cfg)


def _locs(r):
    return [tuple(e["loc"]) for e in r.json()["detail"]]


def test_E01_length_over_10_is_422(tmp_path):
    """E-01 [M1,M2] 長さ 10 超は 422。根拠: TC E-01 期待結果列"""
    root, c, r = _put_with(tmp_path, {"inner_mark_length_mm": 10.01})
    assert r.status_code == 422
    assert any("layout" in loc and "inner_mark_length_mm" in loc for loc in _locs(r)), _locs(r)
    assert get_preset_data(c)["layout"]["inner_mark_length_mm"] == 0


def test_E02_length_negative_is_422(tmp_path):
    """E-02 [M2] 長さが負は 422。根拠: TC E-02。（判別: GET で既定値のキーが読めること。基準では extra 拒否でも 422 になるため）"""
    root, c, r = _put_with(tmp_path, {"inner_mark_length_mm": -0.01})
    assert r.status_code == 422
    assert not any(e.get("type") == "extra_forbidden" for e in r.json()["detail"]), "キー未定義による 422 になっている"
    assert get_preset_data(c)["layout"]["inner_mark_length_mm"] == 0


def test_E03_width_zero_is_422(tmp_path):
    """E-03 [M2,M22] 線幅 0 は 422。根拠: TC E-03。（判別: GET で既定値のキーが読めること）"""
    root, c, r = _put_with(tmp_path, {"inner_mark_width_mm": 0})
    assert r.status_code == 422
    assert any("inner_mark_width_mm" in loc for loc in _locs(r))
    assert not any(e.get("type") == "extra_forbidden" for e in r.json()["detail"]), "キー未定義による 422"
    assert get_preset_data(c)["layout"]["inner_mark_width_mm"] == 0.1


def test_E04_width_negative_is_422(tmp_path):
    """E-04 [M2,M22] 線幅が負は 422。根拠: TC E-04。（判別: GET で既定値のキーが読めること）"""
    root, c, r = _put_with(tmp_path, {"inner_mark_width_mm": -0.1})
    assert r.status_code == 422
    assert not any(e.get("type") == "extra_forbidden" for e in r.json()["detail"]), "キー未定義による 422"
    assert get_preset_data(c)["layout"]["inner_mark_width_mm"] == 0.1


def test_E05_length0_still_checks_width(tmp_path):
    """E-05 [M2,M22] 長さ 0 でも線幅は検査する。根拠: TC E-05。（判別: 長さ 0 は有効値なので、422 の理由に長さが含まれない）"""
    root, c, r = _put_with(tmp_path, {"inner_mark_length_mm": 0, "inner_mark_width_mm": 0})
    assert r.status_code == 422
    locs = _locs(r)
    assert any("inner_mark_width_mm" in loc for loc in locs)
    assert not any("inner_mark_length_mm" in loc for loc in locs), f"長さ 0 が拒否されている {locs}"


def test_E06_wrong_type_is_422_like_mark_length(tmp_path, base_src):
    """E-06 [M2] 型違いは 422。mark_length_mm に文字列を入れたときと同じ失敗の仕方（基準 0f713ff）。根拠: TC E-06"""
    broot = mkhome(tmp_path, None)
    b = base_put(base_src, broot, {"layout": {"mark_length_mm": "3mm"}})
    assert b["status"] == 422
    root, c, r = _put_with(tmp_path, {"inner_mark_length_mm": "3mm"})
    assert r.status_code == 422
    assert [e["type"] for e in r.json()["detail"]] == [e["type"] for e in b["json"]["detail"]]
    assert _locs(r) == [("layout", "inner_mark_length_mm")]
    assert get_preset_data(c)["layout"]["inner_mark_length_mm"] == 0


def test_E07_config_length_out_of_range_load_error(tmp_path, base_src):
    """E-07 [M3,M5] config.json の範囲外は読込エラー（mark_length_mm=-1 と同じ失敗の仕方。基準 0f713ff）。
    根拠: TC E-07。（判別: 同じキーで 10 は読める＝範囲外だけが読込エラー）"""
    broot = mkhome(tmp_path, {"layout": {"mark_length_mm": -1}})
    bcode, bso, bse = base_cli(base_src, "config", "show", "--home", broot)
    assert bcode != 0
    ok = mkhome(tmp_path, IM(10))
    code, so, se = cli(["config", "show", "--home", ok])
    assert code == 0, f"L=10 が読めない: {se}"
    root = mkhome(tmp_path, IM(11))
    code, so, se = cli(["config", "show", "--home", root])
    assert code == bcode and so == bso == "" and se.startswith("error:") and bse.startswith("error:")
    assert "inner_mark_length_mm" in se
    assert client(root, raise_exc=False).get("/api/config").status_code == \
           base_api(base_src, broot, "GET", "/api/config")["status"]


def test_E08_config_width_zero_load_error(tmp_path, base_src):
    """E-08 [M3,M22] config.json の線幅 0 は読込エラー（E-07 と同じ失敗の仕方）。根拠: TC E-08。（判別: 線幅 0.001 は読める）"""
    broot = mkhome(tmp_path, {"layout": {"mark_length_mm": -1}})
    bcode, bso, bse = base_cli(base_src, "config", "show", "--home", broot)
    ok = mkhome(tmp_path, IM(None, 0.001))
    code, so, se = cli(["config", "show", "--home", ok])
    assert code == 0, f"W=0.001 が読めない: {se}"
    root = mkhome(tmp_path, IM(None, 0))
    code, so, se = cli(["config", "show", "--home", root])
    assert code == bcode and so == bso == "" and se.startswith("error:")
    assert "inner_mark_width_mm" in se


@pytest.mark.skip(reason="管理画面の保存操作とエラー表示（DOM）でしか確認できない。browser-test で判定する")
def test_E09_screen_out_of_range_shows_error():
    """E-09 [M20,M2] 範囲外を画面で保存するとエラーが出る。根拠: TC E-09"""


@pytest.mark.skip(reason="管理画面の保存操作とエラー表示（DOM）でしか確認できない。browser-test で判定する")
def test_E10_screen_empty_width_shows_error():
    """E-10 [M20,M22] 線幅を空にして保存するとエラーが出る。根拠: TC E-10"""


def test_E11_422_keeps_saved_values(tmp_path):
    """E-11 [M2,M5] 422 のとき既存の保存値が壊れない。根拠: TC E-11 期待結果列"""
    root = mkhome(tmp_path, IM(3, 0.2))
    c = client(root)
    before = (root / "config.json").read_bytes()
    cfg = get_preset_data(c)
    cfg["layout"]["inner_mark_length_mm"] = 11
    assert put_preset_data(c, cfg).status_code == 422
    lay = get_preset_data(c)["layout"]
    assert lay["inner_mark_length_mm"] == 3 and lay["inner_mark_width_mm"] == 0.2
    assert (root / "config.json").read_bytes() == before


# ================================================================ 境界値
def test_B01_length0_saves_and_draws_nothing(tmp_path, imgs):
    """B-01 [M2,M9,M16] 長さ 0（下限）は保存でき、描かない。根拠: TC B-01 期待結果列"""
    root = mkhome(tmp_path)
    c = client(root)
    cfg = get_preset_data(c)
    cfg["layout"]["inner_mark_length_mm"] = 0
    assert put_preset_data(c, cfg).status_code == 200
    assert "inner_marks" not in c.get("/api/layout/preview").json()
    outdir = tmp_path / "o"
    code, _, se = cli(["impose", *imgs["white10"], "--out", outdir / "out.pdf", "--home", root])
    assert code == 0, se
    segs, _ = read_pdf(outdir / "out.pdf")
    assert len(segs) == 18


def test_B02_length10_draws_10mm_lines(tmp_path, imgs):
    """B-02 [M2,M9,M13] 長さ 10（上限）は保存でき、10mm の線が描かれる。根拠: TC B-02 期待結果列"""
    root = mkhome(tmp_path)
    c = client(root)
    cfg = get_preset_data(c)
    cfg["layout"]["inner_mark_length_mm"] = 10
    assert put_preset_data(c, cfg).status_code == 200
    outdir = tmp_path / "o"
    code, _, se = cli(["impose", *imgs["white10"], "--out", outdir / "out.pdf", "--home", root])
    assert code == 0, se
    inner, _, _ = inner_segs(outdir / "out.pdf")
    assert len(inner) == 26
    assert_same(tuples(inner), s10(10.0), what="L=10")
    assert_contains(tuples(inner), [(105, 66, 105, 56), (14, 66, 24, 66)])
    p0, _, _ = impose(tmp_path, None, imgs["white10"])
    assert layout_json(outdir / "out.pdf") == layout_json(p0[0])


def test_B03_width_0_001_is_saved(tmp_path):
    """B-03 [M2,M22] 線幅の下限直上（0.001）は保存できる。根拠: TC B-03 期待結果列"""
    root, c, r = _put_with(tmp_path, {"inner_mark_width_mm": 0.001})
    assert r.status_code == 200, r.text
    assert get_preset_data(c)["layout"]["inner_mark_width_mm"] == 0.001


def test_B04_n1_no_inner_lines(tmp_path, imgs):
    """B-04 [M9] n=1（全交点が外周の線）は内側の線 0 本。根拠: TC B-04 期待結果列"""
    p3, _, _ = impose(tmp_path, IM(3), imgs["white3"][:1])
    p0, _, _ = impose(tmp_path, None, imgs["white3"][:1])
    a, _ = read_pdf(p3[0])
    b, _ = read_pdf(p0[0])
    assert_same(tuples(a), tuples(b), what="L=3 と L=0 の PDF 線分")


def test_B05_capacity1_no_inner_marks_key(tmp_path):
    """B-05 [M16,M9] 容量 1 のとき inner_marks のキーを足さない。根拠: TC B-05 期待結果列"""
    pv = preview(tmp_path, mg({"detect": {"card_width_mm": 200, "card_height_mm": 150}}, IM(3)))
    assert pv["capacity"] == 1
    assert "inner_marks" not in pv


def test_B06_clipped_at_usage_range(tmp_path):
    """B-06 [M9] 使用範囲の端で線を止める。根拠: TC B-06 期待結果列"""
    diff = mg({"detect": {"card_width_mm": 10, "card_height_mm": 6}, "layout": {"mark_length_mm": 0}}, IM(8))
    pdfs, _, _ = impose(tmp_path, diff, small_pngs(tmp_path, 3))
    segs, _ = read_pdf(pdfs[0])
    assert len(segs) == 4
    exp = [(15, 4.5, 15, 10.5), (15, 10.5, 15, 4.5), (25, 4.5, 25, 10.5), (25, 10.5, 25, 4.5)]
    assert_same(tuples(segs), exp, what="使用範囲の高さ 6mm で止まる線")


def test_B07_clipped_at_printable_area(tmp_path):
    """B-07 [M9,M16] 印字可能域でクリップする（scale_y=1.05）。根拠: TC B-07 期待結果列"""
    got = inner_marks_of(preview(tmp_path, mg({"print": {"scale_y": 1.05}}, IM(3))))
    assert len(got) == 26
    assert_contains(got, [(105, 4.2, 105, 7.275), (105, 292.8, 105, 289.725), (105, 61.875, 105, 58.725)],
                    directed=True, tol=1e-3)


def test_B08_float_error_does_not_split_boundary(tmp_path):
    """B-08 [M9,M10,M16] 浮動小数の誤差で境目が 2 本にならない。根拠: TC B-08 期待結果列"""
    pv = preview(tmp_path, mg({"detect": {"card_width_mm": 30.3, "card_height_mm": 20.1}}, IM(3)))
    got = inner_marks_of(pv)
    assert pv["capacity"] == 90
    assert len(got) == 322
    v = [t for t in got if is_vertical(t)]
    h = [t for t in got if is_horizontal(t)]
    assert len(v) == 162 and len(h) == 160
    assert len({round(t[0], 4) for t in v}) == 9
    assert len({round(t[1], 4) for t in h}) == 8


def test_B09_ingest_single_card_no_inner(tmp_path):
    """B-09 [M23] ingest で 1 枚だけ（per_scan）のシートは内側の線 0 本。根拠: TC B-09 期待結果列"""
    root, jid, sheets = ingest(tmp_path, IM(3), ["a1_deg_0.png"])
    assert len(sheets) == 1
    lay = json.loads(sheets[0].with_suffix(".layout.json").read_text(encoding="utf-8"))
    inner, segs, _ = inner_segs(sheets[0], lay)
    assert len(inner) == 0
    r0, _, s0 = ingest(tmp_path, IM(0), ["a1_deg_0.png"])
    ref, _ = read_pdf(s0[0])
    assert_same(tuples(segs), tuples(ref), what="外周が L=0 と同じ")


def test_B10_L_back_to_0_keeps_created_sheet(tmp_path):
    """B-10 [M6] L を 3→0 に戻しても作成済みシートは 3 のときのまま。根拠: TC B-10 期待結果列"""
    root, jid, sheets = ingest(tmp_path, IM(3), ["a3_three_col.png"])
    pdf = sheets[0]
    lay = json.loads(pdf.with_suffix(".layout.json").read_text(encoding="utf-8"))
    h0 = sha(pdf)
    i0, _, _ = inner_segs(pdf, lay)
    assert len(i0) == 8
    c = client(root)
    cfg = get_preset_data(c)
    cfg["layout"]["inner_mark_length_mm"] = 0
    assert put_preset_data(c, cfg).status_code == 200
    assert sha(pdf) == h0
    i1, _, _ = inner_segs(pdf, lay)
    assert len(i1) == 8


def test_B11_cps1_preview_has_no_inner_marks(tmp_path, imgs):
    """B-11 [M9,M16,M17] cps=1（容量 10 のまま）のプレビューは inner_marks のキーを足さない。根拠: TC B-11 期待結果列"""
    diff = mg({"layout": {"cards_per_sheet": 1}}, IM(3))
    pv = preview(tmp_path, diff)
    assert pv["capacity"] == 10
    assert "inner_marks" not in pv
    pdfs, _, _ = impose(tmp_path, diff, imgs["white3"][:1])
    inner, _, _ = inner_segs(pdfs[0])
    assert len(inner) == 0


def test_B12_cps2_preview_inner_marks(tmp_path, imgs):
    """B-12 [M9,M16,M17] cps=2（1 行）のプレビューの inner_marks。根拠: TC B-12 期待結果列・S2c"""
    diff = mg({"layout": {"cards_per_sheet": 2}}, IM(3))
    pv = preview(tmp_path, diff)
    got = inner_marks_of(pv)
    assert pv["capacity"] == 10
    assert len(got) == 2
    assert_same(got, S2C, directed=True, tol=1e-6, what="S2c")
    pdfs, _, _ = impose(tmp_path, diff, imgs["white3"][:2])
    inner, _, _ = inner_segs(pdfs[0])
    assert len(inner) == 2
    assert_same(tuples(inner), got, what="PDF vs inner_marks")


def test_B13_cps10_same_as_null(tmp_path):
    """B-13 [M9,M16,M17] cps=10（容量ちょうど）は null と同じ。根拠: TC B-13 期待結果列"""
    a = preview(tmp_path, mg({"layout": {"cards_per_sheet": 10}}, IM(3)))
    b = preview(tmp_path, mg({"layout": {"cards_per_sheet": None}}, IM(3)))
    ia, ib = inner_marks_of(a), inner_marks_of(b)
    assert len(ia) == 26 and len(ib) == 26
    assert_same(ia, S10, directed=True, tol=1e-6, what="cps=10")
    assert_same(ib, S10, directed=True, tol=1e-6, what="cps=null")
    assert_same(ia, ib, directed=True, tol=1e-6, what="inner_marks")
    assert_same(mark_tuples(a["marks"]), mark_tuples(b["marks"]), directed=True, tol=1e-6, what="marks")


# ================================================================ 自動実行不可
@pytest.mark.skip(reason="実機（プリンタ・紙・カッター）が要る。lp は自動テストで実行しない。README 手動確認欄で確認する")
def test_X01_real_print_and_cut():
    """X-01 [M14,M26] 実機で印刷して裁断し、線幅の半分が縁に残る。根拠: TC X-01"""


@pytest.mark.skip(reason="旧版のコードを起動する必要がある（checkout 不可）。N-07 の README 注記で代替")
def test_X02_old_version_cannot_start():
    """X-02 [M7] 旧版へ戻したときの起動不能（許容する決定）。根拠: TC X-02"""


@pytest.mark.skip(reason="旧版 serve のプロセスを動かす必要がある。N-06・N-07 で代替")
def test_X03_old_serve_save_resets_keys():
    """X-03 [M8] 旧版 serve が動いたままの画面保存で 2 キーが 0 に戻る。根拠: TC X-03"""


@pytest.mark.skip(reason="未確定: 枚数 0 のシートを作る経路が仕様に無く、compute_layout の戻り値から内側の線を取り出す公開の呼び方（属性名）が正本で決まらない")
def test_X04_zero_cards_draws_nothing():
    """X-04 [M9] 載せる枚数 0 のシートで何も描かない。根拠: TC X-04（compute_layout を names=[] で直接呼ぶ）"""


@pytest.mark.skip(reason="判定しないと決定（advisor 裁定）。N-26 の本数と端点だけを判定")
def test_X05_gap_dashed_overlap_look():
    """X-05 [M12] gap>0 かつ dashed で重なった部分の見た目・画素。根拠: TC X-05"""


# ================================================================ 11.8b 追補
# 正本: ai_docs/specs/spec_11_8b_tc.md（旧 TC と食い違う場合はこちら）・docs/spec.md 11.8b。
# - 期待セットは spec 11.8b の「腕の規則」から作る生成関数 cross_set で作る。主判定は TC の件数（54・24・14・8・76・20・46）と
#   TC が挙げた例の直書き。
# - 管理画面（DOM・SVG・目視）が要る TC は skip を 1 TC ごとに残す（reason に TC ID）。
# - 基準 0f713ff 側の config.json には新キーを入れない（旧版は未知キーで読めない）。
def LY(**kw):
    return {"layout": kw}


def CR(L=3, mode="cross", enabled=True):
    """11.8b 設定の差分: 名刺間トンボの有無・形・長さ。"""
    return LY(inner_mark_enabled=enabled, inner_mark_mode=mode, inner_mark_length_mm=L)


def cross_set(X, Y, L):
    """cross の期待セット（spec 11.8b）: 各交点から、上(y>min Y)・下(y<max Y)・左(x>min X)・右(x<max X) の腕を
    使用範囲で止めて 1 本ずつ。(x1,y1) が交点側。"""
    x0, x1, y0, y1 = min(X), max(X), min(Y), max(Y)
    out = []
    for x in X:
        for y in Y:
            if y > y0:
                out.append((x, y, x, max(y - L, y0)))
            if y < y1:
                out.append((x, y, x, min(y + L, y1)))
            if x > x0:
                out.append((x, y, max(x - L, x0), y))
            if x < x1:
                out.append((x, y, min(x + L, x1), y))
    return [tuple(round(v, 6) for v in t) for t in out]


X10 = (14, 105, 196)
Y10 = (11, 66, 121, 176, 231, 286)
S10X = cross_set(X10, Y10, 3.0)
S3X = cross_set(X10, (11, 66, 121), 3.0)
S2X = cross_set(X10, (11, 66), 3.0)
S1X = cross_set((14, 105), (11, 66), 3.0)
S10XLT = shift(S10X, -14, -11)   # 左上の紙端を原点にする


def post_preview(c, body):
    return c.post("/api/layout/preview", json=body)


def _body(c, **layout):
    cfg = get_preset_data(c)
    cfg["layout"].update(layout)
    return cfg


def _near(a, b, tol=1e-6):
    return abs(a - b) <= tol


# ---------------------------------------------------------------- 正常系
def test_N52_defaults_new_keys_api_and_cli_agree(tmp_path):
    """N-52 [M27,M28] 空の HOME の既定: mark_enabled=true・inner_mark_enabled=true・inner_mark_mode="inward"。API と CLI が一致。"""
    root = mkhome(tmp_path)
    api = get_preset_data(client(root))["layout"]
    code, so, se = cli(["config", "show", "--home", root])
    assert code == 0, se
    cl = json.loads(so)["layout"]
    for lay in (api, cl):
        assert lay["mark_enabled"] is True
        assert lay["inner_mark_enabled"] is True
        assert lay["inner_mark_mode"] == "inward"
    assert api == cl


def test_N53_put_three_values_saved(tmp_path):
    """N-53 [M27,M28,M29] mark_enabled=false・inner_mark_enabled=false・inner_mark_mode="cross"を保存し、GET と再起動後の既定プリセットで確認する。"""
    root = mkhome(tmp_path)
    c = client(root)
    cfg = _body(c, mark_enabled=False, inner_mark_enabled=False, inner_mark_mode="cross")
    assert put_preset_data(c, cfg).status_code == 200
    lay = get_preset_data(c)["layout"]
    assert lay["mark_enabled"] is False and lay["inner_mark_enabled"] is False and lay["inner_mark_mode"] == "cross"
    f = get_preset_data(client(root))["layout"]
    assert f["mark_enabled"] is False and f["inner_mark_enabled"] is False and f["inner_mark_mode"] == "cross"


def test_N54_schema_new_keys_api_and_cli_agree(tmp_path):
    """N-54 [M27,M28,M35] スキーマ: inner_mark_enabled=boolean・default true・title、inner_mark_mode=enum・default・title、
    mark_enabled の title は「名刺外トンボを描く」。API と CLI が同じ。"""
    root = mkhome(tmp_path)
    api = _layout_def(client(root).get("/api/presets/schema").json())
    code, so, se = cli(["config", "schema", "--home", root])
    assert code == 0, se
    cl = _layout_def(json.loads(so))
    for props in (api, cl):
        e, m, me = props["inner_mark_enabled"], props["inner_mark_mode"], props["mark_enabled"]
        assert e["type"] == "boolean" and e["default"] is True and e["title"] == "名刺間トンボを描く", e
        assert m["enum"] == ["inward", "cross"] and m["default"] == "inward" and m["title"] == "名刺間トンボの形", m
        assert me["title"] == "名刺外トンボを描く", me
    for k in ("inner_mark_enabled", "inner_mark_mode", "mark_enabled"):
        assert api[k] == cl[k], k


def test_N55_old_config_without_new_keys(tmp_path):
    """N-55 [M34] 新 2 キー無しの config.json: GET は inner_mark_enabled=true・inner_mark_mode="inward"、GET ではファイルが変わらず、
    全体を PUT すると 2 キーが書かれる。"""
    root = mkhome(tmp_path, {"layout": {"gap_x_mm": 0, "mark_enabled": True}})
    cfgp = root / "config.json"
    legacy = cfgp.read_bytes()
    c = client(root)
    assert (root / "config.json.bak").read_bytes() == legacy
    before = cfgp.read_bytes()
    cfg = get_preset_data(c)
    assert cfg["layout"]["inner_mark_enabled"] is True and cfg["layout"]["inner_mark_mode"] == "inward"
    assert cfgp.read_bytes() == before, "GET だけで config.json が変わった"
    assert put_preset_data(c, cfg).status_code == 200
    f = get_preset_data(client(root))["layout"]
    assert "inner_mark_enabled" in f and "inner_mark_mode" in f


@pytest.mark.skip(reason="N-56: 管理画面の設定フォーム（ラベル・チェック状態・選択肢）は DOM でしか確認できない。browser-test で判定する")
def test_N56_settings_screen_labels():
    """N-56 [M35] 設定「面付け」に「名刺外トンボを描く」「名刺間トンボを描く」（オン）と「名刺間トンボの形」（inward・cross、選択中 inward）。根拠: TC N-56"""


@pytest.mark.skip(reason="N-57: 管理画面の保存操作と再読み込み（DOM）でしか確認できない。browser-test で判定する")
def test_N57_settings_screen_save_off_cross_survives_reload():
    """N-57 [M27,M28,M35] 画面で名刺間トンボをオフ・形を cross にして保存 → 再読み込みしても残る。根拠: TC N-57"""


def test_N58_outer_only_when_inner_disabled(tmp_path, imgs):
    """N-58 [M27,M29,M36] mark_enabled=true・inner_mark_enabled=false・L=3・inward: inner_marks なし・marks 18 件、PDF 18 本（L=0 と一致）、
    layout.json の marks 18 件。"""
    diff = mg(LY(mark_enabled=True, inner_mark_enabled=False, inner_mark_mode="inward", inner_mark_length_mm=3))
    pv = preview(tmp_path, diff)
    assert "inner_marks" not in pv
    assert len(pv["marks"]) == 18
    pdfs, _, _ = impose(tmp_path, diff, imgs["white10"])
    segs, _ = read_pdf(pdfs[0])
    assert len(segs) == 18
    p0, _, _ = impose(tmp_path, None, imgs["white10"])
    s0, _ = read_pdf(p0[0])
    assert_same(tuples(segs), tuples(s0), what="L=0 の PDF と一致")
    assert len(layout_json(pdfs[0])["marks"]) == 18


def test_N59_both_disabled_draws_nothing(tmp_path, imgs):
    """N-59 [M29] mark_enabled=false・inner_mark_enabled=false・L=3: inner_marks なし・marks 0 件・PDF 0 本・layout.json の marks は []。"""
    diff = mg(LY(mark_enabled=False, inner_mark_enabled=False, inner_mark_length_mm=3))
    pv = preview(tmp_path, diff)
    assert "inner_marks" not in pv
    assert pv["marks"] == []
    pdfs, _, _ = impose(tmp_path, diff, imgs["white10"])
    segs, _ = read_pdf(pdfs[0])
    assert len(segs) == 0
    assert layout_json(pdfs[0])["marks"] == []


def test_N60_inner_disabled_wins_over_cross(tmp_path, imgs):
    """N-60 [M27,M28] inner_mark_enabled=false・inner_mark_mode=cross・L=3: inner_marks なし、PDF 18 本（外周のみ）。"""
    diff = CR(3, "cross", enabled=False)
    pv = preview(tmp_path, diff)
    assert "inner_marks" not in pv
    pdfs, _, _ = impose(tmp_path, diff, imgs["white10"])
    segs, _ = read_pdf(pdfs[0])
    assert len(segs) == 18


def test_N61_regression_cross_L0_pixels_equal_base(tmp_path, imgs, mono_base):
    """N-61 [M15,M28] inner_mark_enabled=true・cross・L=0・IMG10: PDF 全画素が 7aacd05 と一致（solid・dashed）。プレビューに inner_marks なし。"""
    for style in (None, {"layout": {"mark_style": "dashed"}}):
        diff = mg(CR(0, "cross", True), style)
        pdfs, _, _ = impose(tmp_path, diff, imgs["img10"])
        broot = mkhome(tmp_path, style)  # 基準側の config.json に新キーは入れない
        bout = tmp_path / f"b_{broot.name}"
        bout.mkdir()
        code, so, se = base_cli(mono_base, "impose", *imgs["img10"], "--out", bout / "out.pdf", "--home", broot)
        assert code == 0, se
        assert same_image(raster(pdfs[0]), raster(bout / "out.pdf")), f"全画素が一致しない（{style}）"
    assert "inner_marks" not in preview(tmp_path, CR(0, "cross", True))


def test_N62_explicit_inward_equals_S10(tmp_path, imgs):
    """N-62 [M28] inner_mark_mode="inward"（明示）・L=3・WHITE10: inner_marks 26 件で S10 と一致。PDF の内側も 26 本。"""
    diff = CR(3, "inward", True)
    got = inner_marks_of(preview(tmp_path, diff))
    assert len(got) == 26
    assert_same(got, S10, directed=True, tol=1e-6, what="inner_marks")
    pdfs, _, _ = impose(tmp_path, diff, imgs["white10"])
    inner, _, _ = inner_segs(pdfs[0])
    assert len(inner) == 26
    assert_same(tuples(inner), S10, what="PDF 内側")


def test_N63_cross_preview_equals_S10x(tmp_path):
    """N-63 [M28,M30,M36] cross・L=3・既定の面付け: inner_marks 54 件で S10x と一致。内訳は隅 8・端 30・内側 16。S10 を全て含む（差分 28）。
    (x1,y1) が交点側。marks は 18 件で L=0 と同じ。"""
    pv = preview(tmp_path, CR(3))
    got = inner_marks_of(pv)
    assert len(got) == 54
    assert_same(got, S10X, directed=True, tol=1e-6, what="S10x")
    assert_contains(got, [(14, 11, 14, 14), (14, 11, 17, 11), (105, 11, 102, 11)], directed=True, tol=1e-6)
    cx, cy = (14, 196), (11, 286)

    def kind(t):
        ix = any(_near(t[0], v) for v in cx)
        iy = any(_near(t[1], v) for v in cy)
        return "corner" if ix and iy else "edge" if ix or iy else "inner"

    kinds = [kind(t) for t in got]
    assert (kinds.count("corner"), kinds.count("edge"), kinds.count("inner")) == (8, 30, 16)
    missing, extra = match(got, S10, directed=True, tol=1e-6)
    assert not missing, "inward の 26 本が含まれていない"
    assert len(extra) == 28
    p0 = preview(tmp_path, CR(0))
    assert len(pv["marks"]) == 18
    assert_same(mark_tuples(pv["marks"]), mark_tuples(p0["marks"]), directed=True, tol=1e-6, what="marks")


def test_N64_cross_pdf_matches_preview(tmp_path, imgs):
    """N-64 [M30] N-63 と同じ設定で WHITE10 を impose: PDF 72 本（外周 18 + 内側 54）。内側が inner_marks と一致。外周 18 本は L=0 と一致。"""
    diff = CR(3)
    pdfs, _, _ = impose(tmp_path, diff, imgs["white10"])
    inner, segs, _ = inner_segs(pdfs[0])
    assert len(segs) == 72 and len(inner) == 54
    pv = inner_marks_of(preview(tmp_path, diff))
    assert_same(tuples(inner), pv, what="PDF 内側 vs inner_marks")
    assert_same(tuples(inner), S10X, what="S10x")
    base, _, _ = impose(tmp_path, None, imgs["white10"])
    bsegs, _ = read_pdf(base[0])
    outer = [s.t for s in segs if s not in inner]
    assert len(outer) == 18
    assert_same(outer, tuples(bsegs), what="外周 18 本")


def test_N65_cross_all_inside_range_and_apart_from_outer_marks(tmp_path):
    """N-65 [M30] 全 54 本の両端点が x∈[14,196]・y∈[11,286]（±0.01）。名刺外トンボ 18 本のどの端点とも、内側の線の端点との距離が 1mm 以上。"""
    pv = preview(tmp_path, CR(3))
    got = inner_marks_of(pv)
    assert len(got) == 54
    pts = [(t[0], t[1]) for t in got] + [(t[2], t[3]) for t in got]
    for x, y in pts:
        assert 14 - TOL <= x <= 196 + TOL and 11 - TOL <= y <= 286 + TOL, (x, y)
    outer_pts = [(m["x1"], m["y1"]) for m in pv["marks"]] + [(m["x2"], m["y2"]) for m in pv["marks"]]
    assert len(pv["marks"]) == 18
    dmin = min(math.hypot(ox - x, oy - y) for ox, oy in outer_pts for x, y in pts)
    assert dmin >= 1.0 - TOL, f"外周トンボの端点との最小距離 {dmin}"


def test_N66_cross_dashed_starts_at_intersection(tmp_path, imgs):
    """N-66 [M30] cross・L=3・dashed（2/1）・WHITE10 を impose: 内側 54 本の破線は実線部 2mm・空白部 1mm。各線の始点が交点側。"""
    dashed = LY(mark_style="dashed", mark_dash_mm=2, mark_gap_mm=1)
    pdfs, _, _ = impose(tmp_path, mg(CR(3), dashed), imgs["white10"])
    inner, _, _ = inner_segs(pdfs[0])
    assert len(inner) == 54
    assert_same(tuples(inner), S10X, directed=True, what="内側（始点つき）")
    assert_contains(tuples(inner), [(14, 11, 14, 14), (105, 286, 102, 286)], directed=True)
    for s in inner:
        assert len(s.dash) == 2 and abs(s.dash[0] - PT_2MM) < 0.01 and abs(s.dash[1] - PT_1MM) < 0.01, s


@pytest.mark.skip(reason="N-67: 管理画面の SVG（DOM）でしか確認できない（line 72 本・内側 54 本 stroke-width 0.35・外周 18 本 0.2）。browser-test で判定する")
def test_N67_slot_diagram_cross_72_lines():
    """N-67 [M18,M30,M33] cross・L=3・W=0.5 の「面付けプレビュー」タブの SVG: line 72 本、内側 54 本は S10x と一致・stroke-width 0.35、外周 18 本は 0.2。根拠: TC N-67"""


def test_N68_cross_cps3_preview_and_pdf(tmp_path, imgs):
    """N-68 [M17,M30] cross・cards_per_sheet=3・L=3: inner_marks 24 件で S3x と一致。WHITE3 の impose の内側 24 本と一致。capacity は 10 のまま。"""
    diff = mg(LY(cards_per_sheet=3), CR(3))
    pv = preview(tmp_path, diff)
    got = inner_marks_of(pv)
    assert len(got) == 24
    assert_same(got, S3X, directed=True, tol=1e-6, what="S3x")
    assert pv["capacity"] == 10
    pdfs, _, _ = impose(tmp_path, diff, imgs["white3"])
    inner, _, _ = inner_segs(pdfs[0])
    assert len(inner) == 24
    assert_same(tuples(inner), got, what="PDF 内側 vs inner_marks")


def test_N69_cross_left_top(tmp_path):
    """N-69 [M30] cross・left/top・L=3・既定の面付け（n=10）: inner_marks は 40 件（周 4。旧 54 件から差し替え。正本 spec_11_8c_tc.md の N-69 / C-06）。
    (0,0) から出る線は 0 本。x1=x2=0 の縦の線は 0 本、y1=y2=0 の横の線は 0 本（旧 54 本との差 14 本）。S10lt の 26 本はすべて含む。"""
    diff = mg(LY(align_x="left", align_y="top"), CR(3))
    got = inner_marks_of(preview(tmp_path, diff))
    assert len(got) == 40
    assert not [t for t in got if _near(t[0], 0, TOL) and _near(t[1], 0, TOL)], "(0,0) から出る線がある"
    assert not [t for t in got if is_vertical(t) and _near(t[0], 0, TOL)], "x1=x2=0 の縦の線がある"
    assert not [t for t in got if is_horizontal(t) and _near(t[1], 0, TOL)], "y1=y2=0 の横の線がある"
    assert_contains(got, S10LT, directed=True, tol=1e-5, what="S10lt の 26 本")
    _, extra = match(S10XLT, got, directed=True, tol=1e-5)  # 旧 54 本にだけある線
    assert len(extra) == 14, f"旧 54 本との差 期待 14 実際 {len(extra)}"


def test_N70_cross_gap_x2_not_merged(tmp_path):
    """N-70 [M30] cross・gap_x=2・L=3（n=10）: inner_marks は 76 件（X={13,104,106,197}）。重なる線も別要素。"""
    got = inner_marks_of(preview(tmp_path, mg(LY(gap_x_mm=2), CR(3))))
    assert len(got) == 76
    assert_same(got, cross_set((13, 104, 106, 197), Y10, 3.0), directed=True, tol=1e-6, what="gap_x=2 の cross")


def test_N71_cross_layout_json_stdout_capacity_unchanged(tmp_path, imgs):
    """N-71 [M13,M25] cross・L=3 と L=0 の impose で layout.json が完全一致（inner_* なし）。標準出力に inner_marks なし。
    capacity（CLI・API）は {"capacity":10,"columns":2,"rows":5,"card_rotated":false}。"""
    p3, so, se = impose(tmp_path, CR(3), imgs["white10"])
    p0, _, _ = impose(tmp_path, IM(0), imgs["white10"])
    l3, l0 = layout_json(p3[0]), layout_json(p0[0])
    assert l3 == l0
    _assert_layout_keys(l3)
    assert "inner" not in Path(str(p3[0]) + ".layout.json").read_text(encoding="utf-8")
    assert "inner_marks" not in so and "inner_marks" not in se
    want = {"capacity": 10, "columns": 2, "rows": 5, "card_rotated": False}
    root = mkhome(tmp_path, CR(3))
    code, cso, cse = cli(["capacity", "--home", root])
    assert code == 0, cse
    assert json.loads(cso) == want
    assert client(root).get("/api/capacity").json() == want


def test_N72_ingest_cross_per_scan_3_cards(tmp_path):
    """N-72 [M23,M30] cross・L=3・timing=per_scan・A3（3 枚）を ingest: sheets/01.pdf の内側が 24 本で S3x と一致。layout.json に inner_* なし。"""
    diff = mg({"print": {"timing": "per_scan"}}, CR(3))
    root, jid, sheets = ingest(tmp_path, diff, ["a3_three_col.png"])
    assert len(sheets) == 1 and sheets[0].name == "01.pdf"
    ltxt = sheets[0].with_suffix(".layout.json").read_text(encoding="utf-8")
    lay = json.loads(ltxt)
    inner, _, _ = inner_segs(sheets[0], lay)
    assert len(inner) == 24
    assert_same(tuples(inner), S3X, what="S3x")
    _assert_layout_keys(lay)
    assert "inner" not in ltxt


def test_N73_impose_cross_multi_sheet(tmp_path, imgs):
    """N-73 [M24,M30] cross・L=3 で 12 枚を impose: out.pdf（10 枚）の内側は 54 本（S10x）、out-2.pdf（2 枚）の内側は 14 本（S2x）。"""
    files = imgs["white10"] + imgs["white10"][:2]
    pdfs, so, se = impose(tmp_path, CR(3), files)
    assert len(pdfs) == 2 and pdfs[1].name == "out-2.pdf"
    i1, _, _ = inner_segs(pdfs[0])
    i2, _, _ = inner_segs(pdfs[1])
    assert len(i1) == 54 and len(i2) == 14
    assert_same(tuples(i1), S10X, what="out.pdf")
    assert_same(tuples(i2), S2X, what="out-2.pdf")


def test_N74_mark_disabled_cross_inner_only(tmp_path, imgs):
    """N-74 [M29,M30] mark_enabled=false・cross・L=3・WHITE10: inner_marks 54 件・marks 0 件・PDF の線分 54 本。"""
    diff = mg(LY(mark_enabled=False), CR(3))
    pv = preview(tmp_path, diff)
    assert len(inner_marks_of(pv)) == 54
    assert pv["marks"] == []
    pdfs, _, _ = impose(tmp_path, diff, imgs["white10"])
    segs, _ = read_pdf(pdfs[0])
    assert len(segs) == 54
    assert_same(tuples(segs), S10X, what="S10x")


def test_N75_post_preview_unsaved_body(tmp_path, imgs):
    """N-75 [M17,M31] 空の HOME。POST /api/layout/preview に既定の全体 + L=3・cross・cards_per_sheet=3: 200・inner_marks 24 件で S3x と一致・
    marks は 3 枚の外周トンボ。応答のトップレベルのキー集合は、同じ設定を保存した HOME の GET /api/layout/preview と同じ。"""
    c = client(mkhome(tmp_path))
    body = _body(c, inner_mark_length_mm=3, inner_mark_mode="cross", cards_per_sheet=3)
    r = post_preview(c, body)
    assert r.status_code == 200, r.text
    pv = r.json()
    got = inner_marks_of(pv)
    assert len(got) == 24
    assert_same(got, S3X, directed=True, tol=1e-6, what="S3x")
    saved = client(mkhome(tmp_path, mg(LY(cards_per_sheet=3), CR(3)))).get("/api/layout/preview").json()
    assert set(pv) == set(saved), (sorted(pv), sorted(saved))
    pdfs, _, _ = impose(tmp_path, mg(LY(cards_per_sheet=3), CR(3)), imgs["white3"])
    assert_same(mark_tuples(pv["marks"]), mark_tuples(layout_json(pdfs[0])["marks"]), directed=True, tol=1e-6,
                what="3 枚の外周トンボ")


def test_N76_post_preview_saves_nothing(tmp_path):
    """N-76 [M31] N-75 のあと: config.json は作られていない。GET config は既定。GET preview に inner_marks なし。DB（あれば）は POST 前とバイト列が同じ。"""
    root = mkhome(tmp_path)
    c = client(root)
    body = _body(c, inner_mark_length_mm=3, inner_mark_mode="cross", cards_per_sheet=3)
    dbp = root / "db.sqlite3"
    db_before = dbp.read_bytes() if dbp.exists() else None
    assert post_preview(c, body).status_code == 200
    assert not (root / "config.json").exists(), "POST で config.json が作られた"
    if db_before is not None:
        assert dbp.read_bytes() == db_before, "POST で DB のバイト列が変わった"
    lay = get_preset_data(c)["layout"]
    assert lay["inner_mark_length_mm"] == 0 and lay["inner_mark_mode"] == "inward" and lay["cards_per_sheet"] is None
    assert "inner_marks" not in c.get("/api/layout/preview").json()


def test_N77_post_preview_differs_from_get(tmp_path):
    """N-77 [M31,M36] config.json に L=3（inward）。POST に L=0 の全体 → 応答に inner_marks なし。続けて GET → 26 件。config.json は変わらない。"""
    root = mkhome(tmp_path, CR(3, "inward", True))
    c = client(root)
    before = (root / "config.json").read_bytes()
    body = _body(c, inner_mark_length_mm=0)
    r = post_preview(c, body)
    assert r.status_code == 200, r.text
    assert "inner_marks" not in r.json()
    g = c.get("/api/layout/preview").json()
    got = inner_marks_of(g)
    assert len(got) == 26
    assert_same(got, S10, directed=True, tol=1e-6, what="GET inner_marks")
    assert (root / "config.json").read_bytes() == before


def test_N78_post_equals_get_for_saved_body(tmp_path):
    """N-78 [M31] config.json に既定を保存。POST に同じ内容の全体: POST の応答と GET の応答が全体で一致（deep equal）。"""
    root = mkhome(tmp_path)
    c = client(root)
    assert put_preset_data(c, get_preset_data(c)).status_code == 200
    body = get_preset_data(c)
    r = post_preview(c, body)
    assert r.status_code == 200, r.text
    assert r.json() == c.get("/api/layout/preview").json()


def test_N79_post_preview_independent_marks(tmp_path):
    """N-79 [M29,M31] POST に mark_enabled=false・inner_mark_enabled=true・L=3・inward: marks 0 件・inner_marks 26 件。"""
    c = client(mkhome(tmp_path))
    body = _body(c, mark_enabled=False, inner_mark_enabled=True, inner_mark_length_mm=3, inner_mark_mode="inward")
    r = post_preview(c, body)
    assert r.status_code == 200, r.text
    pv = r.json()
    assert pv["marks"] == []
    got = inner_marks_of(pv)
    assert len(got) == 26
    assert_same(got, S10, directed=True, tol=1e-6, what="inner_marks")


@pytest.mark.skip(reason="N-80: 管理画面の設定タブとタブ「面付けプレビュー」の SVG（DOM）でしか確認できない。browser-test で判定する")
def test_N80_preview_tab_shows_saved_settings_only():
    """N-80 [M37] 設定タブで長さに 3 を入れて保存せずタブ「面付けプレビュー」へ: SVG は保存済みのまま（内側 line 0 本・全 line 18 本）。config.json は変わらない。根拠: TC N-80"""


# ---------------------------------------------------------------- 異常系
def _loc_keys(r):
    return [e["loc"][-1] for e in r.json()["detail"]]


def test_E12_inner_mark_mode_invalid_values_422(tmp_path):
    """E-12 [M28] inner_mark_mode に "star"・"Cross"・""・null・1 を PUT（5 回）: すべて 422・detail の loc に inner_mark_mode・GET の値は変わらない。"""
    root = mkhome(tmp_path)
    c = client(root)
    for v in ("star", "Cross", "", None, 1):
        cfg = get_preset_data(c)
        cfg["layout"]["inner_mark_mode"] = v
        r = put_preset_data(c, cfg)
        assert r.status_code == 422, (v, r.status_code)
        assert any("inner_mark_mode" in tuple(e["loc"]) for e in r.json()["detail"]), (v, r.json())
        assert get_preset_data(c)["layout"]["inner_mark_mode"] == "inward", v


def test_E13_inner_mark_enabled_non_bool_422_like_mark_enabled(tmp_path):
    """E-13 [M27] inner_mark_enabled="maybe" で PUT: 422（mark_enabled に同じ値を入れたときと同じ失敗の仕方）。"""
    c = client(mkhome(tmp_path))
    cfg = get_preset_data(c)
    cfg["layout"]["mark_enabled"] = "maybe"
    ref = put_preset_data(c, cfg)
    assert ref.status_code == 422
    cfg = get_preset_data(c)
    cfg["layout"]["inner_mark_enabled"] = "maybe"
    r = put_preset_data(c, cfg)
    assert r.status_code == 422
    assert [e["type"] for e in r.json()["detail"]] == [e["type"] for e in ref.json()["detail"]]
    assert _loc_keys(r) == ["inner_mark_enabled"] and _loc_keys(ref) == ["mark_enabled"]


def test_E14_config_json_invalid_mode_load_error(tmp_path, base_src):
    """E-14 [M28,M34] config.json に inner_mark_mode="star" → `config show`: 読込エラー（E-07 と同じ失敗の仕方・基準 0f713ff の mark_length_mm=-1）。
    内容に inner_mark_mode を含む。（判別: "cross" は読める）"""
    broot = mkhome(tmp_path, {"layout": {"mark_length_mm": -1}})
    bcode, bso, bse = base_cli(base_src, "config", "show", "--home", broot)
    assert bcode != 0
    ok = mkhome(tmp_path, LY(inner_mark_mode="cross"))
    code, so, se = cli(["config", "show", "--home", ok])
    assert code == 0, f"inner_mark_mode=cross が読めない: {se}"
    root = mkhome(tmp_path, LY(inner_mark_mode="star"))
    code, so, se = cli(["config", "show", "--home", root])
    assert code == bcode and so == bso == "" and se.startswith("error:") and bse.startswith("error:")
    assert "inner_mark_mode" in se


def test_E15_post_invalid_mode_422_same_as_put(tmp_path):
    """E-15 [M31] POST /api/layout/preview に inner_mark_mode="star" の全体: 422・detail が同じ設定を送る既定プリセットの更新 と完全に同じ。"""
    c = client(mkhome(tmp_path))
    body = _body(c, inner_mark_mode="star")
    r = post_preview(c, body)
    assert r.status_code == 422, r.text
    p = put_preset_data(client(mkhome(tmp_path)), body)
    assert p.status_code == 422
    assert r.json()["detail"] == p.json()["detail"]
    assert any("inner_mark_mode" in tuple(e["loc"]) for e in r.json()["detail"])


def test_E16_post_invalid_length_and_cps_same_as_put(tmp_path):
    """E-16 [M31] POST に L=11 と cards_per_sheet=11（容量 10 超）の全体（2 回）: 同じ本文の PUT とステータス・detail が同じ。L=11 は 422。
    （POST・PUT がともに 200 の場合は detail を比べない）"""
    for key, val in (("inner_mark_length_mm", 11), ("cards_per_sheet", 11)):
        c = client(mkhome(tmp_path))
        body = _body(c, **{key: val})
        r = post_preview(c, body)
        p = put_preset_data(client(mkhome(tmp_path)), body)
        assert r.status_code == p.status_code, (key, r.status_code, p.status_code)
        if key == "inner_mark_length_mm":
            assert r.status_code == 422
        if r.status_code == 422:
            assert r.json()["detail"] == p.json()["detail"], key


def test_E17_post_422_keeps_saved_and_get_preview(tmp_path):
    """E-17 [M31] config.json に L=3。E-15 の POST（422）のあと: config.json のバイト列が同じ。GET preview の inner_marks は 26 件のまま。"""
    root = mkhome(tmp_path, IM(3))
    c = client(root)
    before = (root / "config.json").read_bytes()
    body = _body(c, inner_mark_mode="star")
    assert post_preview(c, body).status_code == 422
    assert (root / "config.json").read_bytes() == before
    got = inner_marks_of(c.get("/api/layout/preview").json())
    assert len(got) == 26


# ---------------------------------------------------------------- 境界値
def test_B14_cross_scale_y_clipped(tmp_path):
    """B-14 [M30] cross・scale_y=1.05・L=3（n=10）: inner_marks は 46 件（y=11 と y=286 の横腕 8 本が域外で消える）。
    y=11 の縦腕の例: {x1:14,y1:4.2,x2:14,y2:7.275}（クリップ後の交点側）。"""
    got = inner_marks_of(preview(tmp_path, mg({"print": {"scale_y": 1.05}}, CR(3))))
    assert len(got) == 46
    assert_contains(got, [(14, 4.2, 14, 7.275)], directed=True, tol=1e-3)
    assert not [t for t in got if is_horizontal(t) and (t[1] < 4.2 - 1e-3 or t[1] > 292.8 + 1e-3)], "域外の横腕が残っている"
    assert not [t for t in got if is_horizontal(t) and (_near(t[1], 4.125, 1e-3) or _near(t[1], 292.875, 1e-3))]
    for t in got:
        assert 4.2 - 1e-3 <= t[1] <= 292.8 + 1e-3 and 4.2 - 1e-3 <= t[3] <= 292.8 + 1e-3, t


def test_B15_cross_cps1_corner_L_shapes(tmp_path, imgs):
    """B-15 [M30] cross・L=3・cards_per_sheet=1（容量は 10）・カード 1 枚の impose: inner_marks は 8 件で S1x と一致（4 隅×2・キーは出る）。
    PDF の内側は 8 本。（TC が「暫定」とする項目: n=1 の cross は 8 本）"""
    diff = mg(LY(cards_per_sheet=1), CR(3))
    pv = preview(tmp_path, diff)
    got = inner_marks_of(pv)
    assert pv["capacity"] == 10
    assert len(got) == 8
    assert_same(got, S1X, directed=True, tol=1e-6, what="S1x")
    pdfs, _, _ = impose(tmp_path, diff, imgs["white3"][:1])
    inner, _, _ = inner_segs(pdfs[0])
    assert len(inner) == 8
    assert_same(tuples(inner), got, what="PDF 内側 vs inner_marks")


def test_B16_cross_cps2(tmp_path, imgs):
    """B-16 [M30] cross・L=3・cards_per_sheet=2・2 枚の impose: inner_marks は 14 件（S2x）。PDF の内側 14 本と一致。（TC が「暫定」とする項目）"""
    diff = mg(LY(cards_per_sheet=2), CR(3))
    got = inner_marks_of(preview(tmp_path, diff))
    assert len(got) == 14
    assert_same(got, S2X, directed=True, tol=1e-6, what="S2x")
    pdfs, _, _ = impose(tmp_path, diff, imgs["white3"][:2])
    inner, _, _ = inner_segs(pdfs[0])
    assert len(inner) == 14
    assert_same(tuples(inner), got, what="PDF 内側 vs inner_marks")


def test_B17_cross_clipped_at_usage_range(tmp_path):
    """B-17 [M30] cross・カード 10×6・L=8・mark_length_mm=0・3 枚の impose（B-06 と同条件）: 内側 20 本（4ab−2a−2b）。縦腕は長さ 6 で止まる。
    使用範囲での打ち切りが cross にも効く。"""
    diff = mg({"detect": {"card_width_mm": 10, "card_height_mm": 6}}, LY(mark_length_mm=0), CR(8))
    pdfs, _, _ = impose(tmp_path, diff, small_pngs(tmp_path, 3))
    segs, _ = read_pdf(pdfs[0])
    assert len(segs) == 20
    assert_contains(tuples(segs), [(15, 4.5, 15, 10.5), (5, 4.5, 13, 4.5), (15, 4.5, 7, 4.5), (15, 4.5, 23, 4.5)],
                    directed=True, what="TC の例")
    assert_same(tuples(segs), cross_set((5, 15, 25, 35), (4.5, 10.5), 8.0), what="cross 20 本")


def test_B18_cross_L10_upper_limit(tmp_path):
    """B-18 [M30] cross・L=10（上限）・既定（n=10）: inner_marks は 54 件。長さ 10。すべて範囲内。"""
    got = inner_marks_of(preview(tmp_path, CR(10)))
    assert len(got) == 54
    assert_contains(got, [(105, 66, 105, 76), (105, 66, 95, 66), (14, 11, 14, 21), (14, 11, 24, 11)], directed=True, tol=1e-6)
    for t in got:
        assert 14 - TOL <= min(t[0], t[2]) and max(t[0], t[2]) <= 196 + TOL, t
        assert 11 - TOL <= min(t[1], t[3]) and max(t[1], t[3]) <= 286 + TOL, t


def test_B19_cross_capacity1_has_8_inner_marks(tmp_path):
    """B-19 [M30] cross・L=3・カード 200×150（容量 1）: capacity が 1。inner_marks は 8 件（キーあり）。（B-05 の cross 版。座標は TC に無いので件数のみ）"""
    pv = preview(tmp_path, mg({"detect": {"card_width_mm": 200, "card_height_mm": 150}}, CR(3)))
    assert pv["capacity"] == 1
    assert len(inner_marks_of(pv)) == 8


# ---------------------------------------------------------------- 自動実行不可（目視確認項目）
@pytest.mark.skip(reason="X-06: 設定画面右側のスロット図の常時表示は配置・見た目の判定が人の目になる（代替: POST 応答は N-75〜N-79）")
def test_X06_slot_diagram_always_visible_in_settings():
    """X-06 [M32] 設定画面の右側にスロット図が常時表示される。根拠: TC X-06"""


@pytest.mark.skip(reason="X-07: 入力の約 0.25 秒後の描き直し・保存しないは時間・見た目の確認（代替: N-76）")
def test_X07_redraw_after_250ms_without_saving():
    """X-07 [M32] 入力の約 0.25 秒後に、保存前の値で描き直す。保存しない。根拠: TC X-07"""


@pytest.mark.skip(reason="X-08: 不正値で図は直前のまま・赤字で理由が出るのは見た目の確認（代替: E-15〜E-17）")
def test_X08_invalid_input_keeps_diagram_and_shows_red_text():
    """X-08 [M32] 不正値で図は直前のまま、赤字で理由が出る。根拠: TC X-08"""


@pytest.mark.skip(reason="X-09: 青枠が無く市松の 2 色で区別される（色の仕様が未確定で見た目の判定。代替: N-27・N-49・N-67 の線幅は DOM で確認）")
def test_X09_no_blue_frame_checkerboard_two_colors():
    """X-09 [M33] 青枠が無く、市松の 2 色で区別される（設定画面右側とタブ「面付けプレビュー」の両方）。根拠: TC X-09"""


@pytest.mark.skip(reason="X-10: cross の見た目（端 T・隅 L・内側十字）は周 3 が目視未確認でユーザー判断（代替: N-63・N-64 の座標・本数）")
def test_X10_cross_look():
    """X-10 [M30] cross の見た目（端 T・隅 L・内側十字が分かりやすいか）。根拠: TC X-10"""
