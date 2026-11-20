"""仕様 11.7（縁の白塗り correct.edge_white_mm）の受け入れテスト。

正本: docs/spec.md の 11.7（commit e8d5b29）・3 設定一覧の correct 行・4.8（グレー化と白飛ばしは PDF 生成時）。
各テストの docstring 先頭に、根拠にした 11.7 の箇条の先頭の語句を書く。期待値は仕様の値をそのまま使う。
仕様に書かれていない挙動（リング幅が画像より大きい場合・NaN・管理画面 JS の中身）は期待値にしない。

呼び方（仕様だけでは決まらないものを、公開 API の形から決めたもの）:
- 画素処理は `print_edit.core.pdf.prepare_image(img, settings, rotate90)` を直接呼ぶ（仕様 11.7「`prepare_image`」）。
- 設定は `Settings.model_validate` の dict。color は device.supports_color=true が要る（3 節の検査）。
- 設定の保存・422・スキーマは GET/PUT /api/config・GET /api/config/schema・CLI `config show|schema`。
- 新しく作るシートは CLI `impose`、保存済みの確認は ingest（Env は test_spec_11_3 のもの。実 lp は使わない）。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError

from print_edit.api.app import create_app
from print_edit.cli import main
from print_edit.core.pdf import prepare_image
from print_edit.core.settings import Settings
from print_edit.home import Home

from test_spec_11_3 import Env, fake_lp, lp  # noqa: F401  (fake_lp は autouse fixture)


# ================================================================ 部品
def S(edge, *, mode="mono", whiten=200, size_mode="fit", card=(91, 55)):
    return Settings.model_validate({
        "correct": {"edge_white_mm": edge, "whiten_level": whiten, "size_mode": size_mode},
        "detect": {"card_width_mm": card[0], "card_height_mm": card[1]},
        "print": {"color_mode": mode},
        "device": {"supports_color": mode == "color"},
    })


def dark(w, h, mode="mono", seed=0):
    """1〜200 だけの乱数画像（255 を含まない。whiten 0 のとき、出力の 255 は全て白塗りの画素）。"""
    rng = np.random.default_rng(seed)
    shape = (h, w) if mode == "mono" else (h, w, 3)
    arr = rng.integers(1, 201, shape, dtype=np.uint8)
    return arr, Image.fromarray(arr, "L" if mode == "mono" else "RGB")


def ring_mask(w, h, p):
    m = np.zeros((h, w), bool)
    m[:p, :] = True
    m[h - p:, :] = True
    m[:, :p] = True
    m[:, w - p:] = True
    return m


def run(img, s, rotate90=False):
    return np.array(prepare_image(img, s, rotate90))


def assert_ring_only(out, base, p):
    """外周 p px だけが 255（color は RGB 全部）。それ以外は base（0 のときの出力）と同じ。"""
    h, w = out.shape[:2]
    m = ring_mask(w, h, p)
    assert (out[m] == 255).all(), "外周に 255 でない画素がある"
    assert (out[~m] == base[~m]).all(), "外周より内側の画素が 0 のときと違う"


# ================================================================ 設定（検証・既定値）
def test_setting_default_is_zero():
    """設定 `correct.edge_white_mm`（既定 0）。"""
    assert Settings().correct.edge_white_mm == 0


@pytest.mark.parametrize("v", [0, 0.0, 0.5, 2.2, 5, 5.0])
def test_setting_accepts_0_to_5_inclusive(v):
    """設定 `correct.edge_white_mm`（float・0 以上 5 以下）。端の 0 と 5 を含む。"""
    assert Settings.model_validate({"correct": {"edge_white_mm": v}}).correct.edge_white_mm == v


@pytest.mark.parametrize("v", [-0.01, -1, 5.01, 6])
def test_setting_rejects_out_of_range(v):
    """範囲外は拒否する（0 未満・5 超）。"""
    Settings.model_validate({"correct": {"edge_white_mm": 0}})  # 前提: キー自体は有効（未知キーの拒否と取り違えない）
    with pytest.raises(ValidationError):
        Settings.model_validate({"correct": {"edge_white_mm": v}})


class Raw:
    """config.json を手書きの dict で置く home（raw=None なら config.json 無し）。"""

    def __init__(self, base, raw=None):
        self.home = Home(Path(base) / "h")
        self.home.ensure(Settings.model_validate({"intake": {"stable_wait_s": 0}}))
        if raw is not None:
            (self.home.root / "config.json").write_text(json.dumps(raw))
        self.c = TestClient(create_app(self.home))


def _cfg_json(e):
    p = e.home.root / "config.json"
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


@pytest.mark.parametrize("v", [-0.1, 5.1])
def test_put_config_out_of_range_is_422_and_unchanged(tmp_path, v):
    """範囲外は拒否する（PUT /api/config は 422）。拒否したら保存済みの値は変わらない。"""
    e = Raw(tmp_path)
    c = e.c.get("/api/config").json()
    assert c["correct"]["edge_white_mm"] == 0  # 前提: キーがある（キー無しの 422 と取り違えない）
    h0 = _cfg_json(e)
    c["correct"]["edge_white_mm"] = v
    r = e.c.put("/api/config", json=c)
    assert r.status_code == 422, (r.status_code, r.text)
    assert e.c.get("/api/config").json()["correct"]["edge_white_mm"] == 0
    assert _cfg_json(e) == h0


@pytest.mark.parametrize("v", [0, 0.5, 5])
def test_put_config_accepts_and_roundtrips(tmp_path, v):
    """設定 `correct.edge_white_mm`（0 以上 5 以下）。PUT で保存した値が GET で返る。"""
    e = Raw(tmp_path)
    c = e.c.get("/api/config").json()
    c["correct"]["edge_white_mm"] = v
    r = e.c.put("/api/config", json=c)
    assert r.status_code == 200, r.text
    assert e.c.get("/api/config").json()["correct"]["edge_white_mm"] == v


@pytest.mark.parametrize("raw", [None, {}, {"correct": {}}, {"correct": {"size_mode": "fit", "whiten_level": 200}}])
def test_missing_key_reads_as_zero(tmp_path, raw):
    """保存済みの設定ファイルにキーが無いときは 0 として読む。"""
    e = Raw(tmp_path, raw)
    assert e.c.get("/api/config").json()["correct"]["edge_white_mm"] == 0


def test_saved_value_is_read(tmp_path):
    """保存済みの設定ファイル（キーあり）はその値を読む。"""
    e = Raw(tmp_path, {"correct": {"edge_white_mm": 0.5}})
    assert e.c.get("/api/config").json()["correct"]["edge_white_mm"] == 0.5


def _node(schema, n):
    """$ref / allOf を辿り、兄弟キー（title 等）と合成した節点。"""
    out = dict(n)
    if "$ref" in out:
        ref = schema
        for k in out.pop("$ref").lstrip("#/").split("/"):
            ref = ref[k]
        out = {**_node(schema, ref), **out}
    for sub in out.pop("allOf", []):
        out = {**_node(schema, sub), **out}
    return out


def _schema_checks(schema):
    sec = _node(schema, schema["properties"]["correct"])
    assert sec.get("title") == "補正", sec.get("title")
    p = _node(schema, sec["properties"]["edge_white_mm"])
    assert p.get("type") == "number", p
    assert p.get("minimum") == 0 and p.get("maximum") == 5, p
    assert p.get("default") == 0, p
    assert p.get("title") == "縁の白塗り幅(mm)", p.get("title")


def test_schema_has_edge_white_mm_in_correct_section(tmp_path, capsys):
    """管理画面「設定」の「補正」に出る（スキーマから自動生成）。項目名は「縁の白塗り幅(mm)」。"""
    e = Raw(tmp_path)
    api = e.c.get("/api/config/schema")
    assert api.status_code == 200
    _schema_checks(api.json())
    capsys.readouterr()
    assert main(["config", "schema", "--home", str(e.home.root)]) == 0
    _schema_checks(json.loads(capsys.readouterr().out))


# ================================================================ 画素処理（prepare_image）
@pytest.mark.parametrize("n, w, h, px", [
    (2.2, 2275, 1375, 55),    # 積 55.00000000000001 を 6 桁に丸めて 55（1px 多く出ない）
    (0.5, 2150, 1299, 12),    # 600dpi（23.62 px/mm）。切り捨てなら 11px
    (0.5, 910, 550, 5),       # 10 px/mm・ちょうど整数
    (0.55, 910, 550, 6),      # 5.5 → 切り上げ 6
    (1.1, 910, 550, 11),
    (5.0, 910, 550, 50),      # 上限
    (0.05, 910, 550, 1),      # 0.5 → 切り上げ 1
    (2.2, 2275, 1000, 55),    # 密度は長い辺（2275 / 91）で 1 つ。短辺の寸法比（1000 / 55）ではない
])
def test_px_width_ceil_of_rounded_product_mono(n, w, h, px):
    """画像の外周 N mm を白（255）にする。px 幅 = ceil(round(N × 画素密度, 6))。四辺とも同じ幅。"""
    arr, img = dark(w, h)
    out = run(img, S(n, whiten=0))
    assert_ring_only(out, arr, px)
    assert (out == 255).sum() == ring_mask(w, h, px).sum()


@pytest.mark.parametrize("n, w, h, px", [
    (2.2, 2275, 1375, 55),
    (0.5, 2150, 1299, 12),
    (0.55, 910, 550, 6),
])
def test_px_width_color(n, w, h, px):
    """`color_mode` が mono でも color でも効く。color は RGB すべて 255。"""
    arr, img = dark(w, h, "color")
    out = run(img, S(n, mode="color"))
    assert out.shape == (h, w, 3)
    assert_ring_only(out, arr, px)
    assert (out[ring_mask(w, h, px)] == 255).all()


def test_four_sides_same_width():
    """四辺とも同じ幅（px）で塗る。辺ごとの最初の非白画素の位置が左右上下で同じ。"""
    arr, img = dark(910, 550)
    out = run(img, S(0.55, whiten=0))
    mid_r, mid_c = 275, 455
    assert (out[mid_r, :] == 255).argmin() == 6
    assert (out[mid_r, ::-1] == 255).argmin() == 6
    assert (out[:, mid_c] == 255).argmin() == 6
    assert (out[::-1, mid_c] == 255).argmin() == 6


@pytest.mark.parametrize("card, w, h, px", [
    ((55, 91), 2275, 1375, 55),   # card_width < card_height でも長い方（91）
    ((91, 55), 2275, 1375, 55),
    ((100, 60), 1000, 600, 20),   # N=2・10 px/mm
    ((60, 100), 1000, 600, 20),
    ((91, 55), 1375, 2275, 55),   # 画像が縦長でも長い辺（2275）÷ 91
])
def test_density_uses_long_side_over_larger_card_dimension(card, w, h, px):
    """画素密度（px/mm）は、画像の長い辺の px ÷ カードの長辺の寸法（detect の card_width_mm と card_height_mm の大きい方）。"""
    n = 2.2 if card[0] in (55, 91) else 2
    arr, img = dark(w, h)
    out = run(img, S(n, whiten=0, card=card))
    assert_ring_only(out, arr, px)


def test_outside_ring_same_as_zero_after_whiten_mono():
    """外周 N mm 以外の画素は、0 のとき（塗らないとき）と同じ。処理は白飛ばし（4.8）の後（既定の whiten_level=200）。"""
    w, h = 2150, 1299
    x = np.linspace(0, 1, w, dtype=np.float32)[None, :]
    arr = (205 + 40 * x + np.zeros((h, 1), np.float32)).astype(np.uint8)  # 照明むらのある紙
    arr[500:540, 300:1800] = 60                                            # 内側の暗い帯
    arr[:11, :] = 25
    arr[-11:, :] = 25
    arr[:, :11] = 25
    arr[:, -11:] = 25                                                      # 暗い縁取り（外周 11px）
    img = Image.fromarray(arr, "L")
    base = run(img, S(0))
    assert (base[:11, 100:-100] < 255).all()  # 前提: 0 のとき縁取りは残る
    out = run(img, S(0.5))
    assert_ring_only(out, base, 12)


def test_outside_ring_same_as_zero_color():
    """外周 N mm 以外の画素は、0 のとき（塗らないとき）と同じ。color でも同じ。"""
    arr, img = dark(2150, 1299, "color", seed=3)
    base = run(img, S(0, mode="color"))
    assert_ring_only(run(img, S(0.5, mode="color")), base, 12)


@pytest.mark.parametrize("mode", ["mono", "color"])
def test_size_mode_does_not_change_processing(mode):
    """`size_mode` で処理を分けない（actual でも常に外周を塗る）。"""
    arr, img = dark(2275, 1375, mode, seed=5)
    fit = run(img, S(2.2, mode=mode, whiten=0, size_mode="fit"))
    act = run(img, S(2.2, mode=mode, whiten=0, size_mode="actual"))
    assert (fit == act).all()
    assert_ring_only(act, arr, 55)


@pytest.mark.parametrize("mode, nd, pil", [("mono", 2, "L"), ("color", 3, "RGB")])
def test_image_size_unchanged(mode, nd, pil):
    """画像の寸法は変えない。"""
    arr, img = dark(2150, 1299, mode)
    out = prepare_image(img, S(0.5, mode=mode), False)
    assert out.size == (2150, 1299)
    assert out.mode == pil


def test_rotate90_ring_is_on_output_image():
    """処理は PDF 生成時（`prepare_image`）の最後。回転（rotate90）の後の画像の外周を塗る。"""
    arr, img = dark(910, 550, seed=7)
    base = run(img, S(0, whiten=0), rotate90=True)
    out = run(img, S(0.5, whiten=0), rotate90=True)
    assert out.shape == (910, 550)
    assert_ring_only(out, base, 5)


def test_zero_changes_nothing_mono():
    """0 のときは何も塗らず、`prepare_image` が返す画像の全画素は現行と同じ。（mono・whiten 0 は入力のまま）"""
    arr, img = dark(910, 550)
    assert (run(img, S(0, whiten=0)) == arr).all()
    assert (run(img, S(0.0, whiten=0)) == arr).all()


def test_zero_changes_nothing_color():
    """0 のときは何も塗らず、`prepare_image` が返す画像の全画素は現行と同じ。（color は入力のまま）"""
    arr, img = dark(910, 550, "color")
    assert (run(img, S(0, mode="color")) == arr).all()


def test_zero_with_whiten_matches_current_behavior():
    """0 のときは何も塗らず、全画素は現行と同じ。（白飛ばしだけ効く: 紙 210 は 255、暗部 50 はそのまま。外周も同じ）"""
    arr = np.full((100, 160), 210, np.uint8)
    arr[40:44, 10:150] = 50
    arr[:, :3] = 50
    img = Image.fromarray(arr, "L")
    for s in (S(0), Settings()):
        out = run(img, s)
        assert (out[arr == 210] == 255).all() and (out[arr == 50] == 50).all()


def test_key_absent_settings_same_as_explicit_zero():
    """保存済みの設定ファイルにキーが無いときは 0 として読む。（prepare_image の結果も明示の 0 と同じ）"""
    arr, img = dark(910, 550, seed=9)
    assert (run(img, Settings.model_validate({"correct": {"whiten_level": 0}}))
            == run(img, S(0, whiten=0))).all()


# ================================================================ 新しく作るシート・保存済みの不変
def _png_with_dark_frame(path):
    """910 x 550 px（10 px/mm・カード 91 x 55 mm）。中身は灰 120・外周 8px（0.8mm）は暗い 20。"""
    a = np.full((550, 910), 120, np.uint8)
    m = ring_mask(910, 550, 8)
    a[m] = 20
    Image.fromarray(a, "L").save(path, dpi=(254, 254))


def _render_gray(pdf, px_per_mm=10):
    doc = pdfium.PdfDocument(str(pdf))
    img = doc[0].render(scale=px_per_mm * 25.4 / 72).to_pil().convert("L")
    doc.close()
    return np.array(img, dtype=np.float64)


def _impose(tmp_path, monkeypatch, name, edge):
    monkeypatch.setenv("PRINT_EDIT_HOME", str(tmp_path / "home"))
    card = tmp_path / "01.png"
    _png_with_dark_frame(card)
    cfg = tmp_path / f"{name}.json"
    cfg.write_text(json.dumps({
        "correct": {"edge_white_mm": edge, "whiten_level": 0},
        "layout": {"mark_enabled": False},
        "print": {"output": "pdf", "timing": "per_scan"},
    }))
    pdf = tmp_path / f"{name}.pdf"
    assert main(["impose", str(card), "--out", str(pdf), "--config", str(cfg)]) == 0
    for cand in (pdf.with_name(pdf.name + ".layout.json"), pdf.with_name(pdf.stem + ".layout.json")):
        if cand.exists():
            return pdf, json.loads(cand.read_text())
    pytest.fail("layout.json が見つからない")


def _zone(img, slot, x0, x1, y0, y1):
    """スロット左上からの mm 範囲の画素（10 px/mm）。"""
    ox, oy = slot["x"] * 10, slot["y"] * 10
    return img[round(oy + y0 * 10):round(oy + y1 * 10), round(ox + x0 * 10):round(ox + x1 * 10)]


def test_new_sheet_pdf_has_white_edge(tmp_path, monkeypatch):
    """処理は PDF 生成時（`prepare_image`）の最後。設定を変えたあとに新しく作るシートから効く。四辺の外周 N mm が白。"""
    pdf0, lay0 = _impose(tmp_path, monkeypatch, "e0", 0)
    pdf2, lay2 = _impose(tmp_path, monkeypatch, "e2", 2.0)
    s0, s2 = lay0["slots"][0], lay2["slots"][0]
    g0, g2 = _render_gray(pdf0), _render_gray(pdf2)
    w, h = s2["w"], s2["h"]
    # 0 のとき: 暗い縁取り（外周 0.8mm）が刷られている（前提）
    assert _zone(g0, s0, 0.2, 0.6, 5, h - 5).mean() < 60
    # N=2: 四辺とも外周 2mm（縁の 0.2mm 内側から 1.8mm まで）が白
    for z in ((0.2, 1.8, 5, h - 5), (w - 1.8, w - 0.2, 5, h - 5), (5, w - 5, 0.2, 1.8), (5, w - 5, h - 1.8, h - 0.2)):
        assert _zone(g2, s2, *z).min() >= 250, z
    # 外周より内側（3mm 以上）は 0 のときと同じ灰
    for g, s in ((g0, s0), (g2, s2)):
        inner = _zone(g, s, 3, w - 3, 3, h - 3)
        assert abs(inner.mean() - 120) < 5


def _tree_hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(root).rglob("*")) if p.is_file()}


def test_saved_pdf_and_cards_unchanged_after_setting_change(tmp_path, lp):
    """保存済みのシート PDF も変わらない（`cards/NN.png`・`source.png` も変えない）。設定を変えたあとに新しく作るシートから効く。"""
    e = Env(tmp_path, {"correct": {"edge_white_mm": 0}})
    e.drop_scan(2)
    e.ingest()
    jobs = e.home.root / "jobs"
    before = _tree_hashes(jobs)
    assert any(k.endswith(".pdf") for k in before) and any("cards" in k and k.endswith(".png") for k in before)
    e.put(correct={"edge_white_mm": 0.5})
    assert _tree_hashes(jobs) == before
    e.drop_scan(1)
    e.ingest()
    after = _tree_hashes(jobs)
    assert all(after.get(k) == v for k, v in before.items())  # 既存ファイルは全て同一
    assert len(after) > len(before)                           # 新しいシートは新しく作られる


def test_cards_source_layout_capacity_same_as_zero(tmp_path):
    """画像の寸法・スロット・トンボ・容量・レイアウト・`layout.json` は変えない。`cards/NN.png`・`source.png` は変えない。"""
    res = {}
    for name, v in (("a", 0), ("b", 5)):
        base = tmp_path / name
        base.mkdir()
        e = Env(base, {"correct": {"edge_white_mm": v}})
        e.drop_scan(3)
        e.ingest()
        root = str(e.home.root)
        jobs_dir = e.home.root / "jobs"
        # ジョブ ID（日時 + 乱数）は home ごとに必ず異なるので、昇順の通し番号 job0.. に置き換えて比べる
        job_ids = sorted(d.name for d in jobs_dir.iterdir() if d.is_dir())
        norm = {jid: f"job{i}" for i, jid in enumerate(job_ids)}

        def _n(text):
            text = text.replace(root, "<HOME>")
            for jid, label in norm.items():
                text = text.replace(jid, label)
            return text

        files, lays = {}, {}
        for k, digest in _tree_hashes(jobs_dir).items():
            nk = _n(k)
            if k.endswith(".layout.json"):
                lays[nk] = _n((jobs_dir / k).read_text())
            elif k.endswith(".json"):  # detect.json 等: ID・パスを正規化した本文で比べる
                files[nk] = _n((jobs_dir / k).read_text())
            else:
                files[nk] = digest
        pdfs = {k for k in files if k.endswith(".pdf")}
        res[name] = {
            "files": {k: val for k, val in files.items() if k not in pdfs and not k.endswith(".layout.json")},
            "pdfs": sorted(pdfs),
            "lays": lays,
            "cap": e.c.get("/api/capacity").json(),
            "preview": e.c.get("/api/layout/preview").json(),
        }
    a, b = res["a"], res["b"]
    assert any("cards" in k and k.endswith(".png") for k in a["files"])
    assert a["lays"] and a["lays"] == b["lays"]
    assert a["files"] == b["files"]          # cards/NN.png・source.png ほか PDF 以外の保存物は同一
    assert a["pdfs"] == b["pdfs"]
    assert a["cap"] == b["cap"]
    assert a["preview"] == b["preview"]
