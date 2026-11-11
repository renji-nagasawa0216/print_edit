import math
import numpy as np
import pytest
from pydantic import ValidationError
from synth import make_scan, rect_corners, MM

from print_edit.core.settings import Settings, capacity_of
from print_edit.core.detect import detect_cards, resolve_dpi
from print_edit.core.layout import compute_capacity, compute_layout
from print_edit.core.pdf import render_pdf


def corner_err_mm(card, truth):
    got = np.array(card.corners_px) / 600 * MM
    t = np.array(truth)
    worst = 0
    for p in t:
        worst = max(worst, min(np.hypot(*(g - p)) for g in got))
    return worst


@pytest.mark.parametrize("ang", [-45, -20, 0, 7.5, 30, 45])
def test_single_card_angles(ang):
    s = Settings()
    img = make_scan([(105, 148, 91, 55, ang)])
    r = detect_cards(img, 600, s)
    assert r.status == "ok" and len(r.cards) == 1
    c = r.cards[0]
    assert corner_err_mm(c, rect_corners(105, 148, 91, 55, ang)) < 0.3
    assert abs(c.long_mm - 91) < 0.3 and abs(c.short_mm - 55) < 0.3
    assert c.image.shape[:2] == (1299, 2150)
    assert abs(c.angle_deg - ang) < 0.5


def test_three_cards_order_and_noise():
    s = Settings()
    spec = [(105, 200, 91, 55, 3), (52, 60, 91, 55, -5), (152, 62, 91, 55, 10)]
    img = make_scan(spec, noise=8, gradient=25)
    r = detect_cards(img, 600, s)
    assert len(r.cards) == 3
    cs = [c.center_mm for c in r.cards]
    assert cs[0][0] < cs[1][0] and abs(cs[0][1] - 60) < 5 and abs(cs[1][1] - 62) < 5
    assert cs[2][1] > 150
    for c, t in zip(r.cards, [spec[1], spec[2], spec[0]]):
        assert corner_err_mm(c, rect_corners(*t)) < 0.5


def test_anomalies_not_ok():
    s = Settings()
    assert detect_cards(make_scan([]), 600, s).reasons == ["no_cards"]
    r = detect_cards(make_scan([(105, 148, 89, 51, 0)]), 600, s)
    assert r.status == "review" and r.cards[0].reasons == ["size_out_of_tolerance"]
    r = detect_cards(make_scan([(60, 100, 91, 55, 0), (60 + 91, 100, 91, 55, 0)]), 600, s)
    assert r.status == "review"
    # 濃い縁取りで明領域が縮んだ状態（85x49 相当）
    assert detect_cards(make_scan([(105, 148, 85, 49, 0)]), 600, s).status == "review"


def test_actual_mode_and_rotate():
    s = Settings.model_validate({"correct": {"size_mode": "actual", "rotate_180": True}})
    r = detect_cards(make_scan([(105, 148, 91, 55, 12)]), 600, s)
    assert r.cards[0].image.shape[:2] == (1299, 2150)


def test_resolve_dpi():
    assert resolve_dpi(None, None, 600) == (600, "config", False)
    assert resolve_dpi(300, None, 600) == (300, "metadata", True)
    assert resolve_dpi(600, None, 600) == (600, "metadata", False)
    assert resolve_dpi(300, 400, 600) == (400, "option", True)


def test_dpi_mismatch_makes_review():
    r = detect_cards(make_scan([(105, 148, 91, 55, 0)]), 600, Settings(), dpi_mismatch=True)
    assert r.warnings == ["dpi_mismatch"] and r.cards[0].status == "review" and r.status == "review"


def test_capacity_default_and_variants():
    assert capacity_of(Settings()).to_dict() == {"capacity": 10, "columns": 2, "rows": 5, "card_rotated": False}
    c = compute_capacity(210, 297, 4.2, 91, 55, 5, 5)
    assert (c.capacity, c.card_rotated) == (9, True)
    # 回転が有利: 用紙 120x100 印字域 120x100 のカード 91x55 → 横置き1x1、縦置き 2x1
    c = compute_capacity(128.4, 108.4, 4.2, 91, 55, 0, 0)
    assert c.card_rotated and c.capacity == 2


def test_settings_validation():
    with pytest.raises(ValidationError):
        Settings.model_validate({"layout": {"cards_per_sheet": 11}})
    with pytest.raises(ValidationError):
        Settings.model_validate({"print": {"color_mode": "color"}})
    with pytest.raises(ValidationError):
        Settings.model_validate({"print": {"scale_x": 1.2}})
    Settings.model_validate({"print": {"color_mode": "color"}, "device": {"supports_color": True}})
    assert "intake" in Settings.model_json_schema()["properties"]


def test_layout_no_overlap_in_printable_and_scale():
    s = Settings.model_validate({"print": {"scale_x": 1.01, "scale_y": 0.99}})
    lay = compute_layout(s, [f"{i}.png" for i in range(10)])
    px, py, pw, ph = lay.printable_mm
    assert len(lay.slots) == 10
    for a in lay.slots:
        assert a["x"] >= px - 1e-6 and a["x"] + a["w"] <= px + pw + 1e-6
        assert a["y"] >= py - 1e-6 and a["y"] + a["h"] <= py + ph + 1e-6
        assert abs(a["w"] - 91 * 1.01) < 0.01 and abs(a["h"] - 55 * 0.99) < 0.01
    for i, a in enumerate(lay.slots):
        for b in lay.slots[i + 1:]:
            assert a["x"] + a["w"] <= b["x"] + 1e-6 or b["x"] + b["w"] <= a["x"] + 1e-6 or a["y"] + a["h"] <= b["y"] + 1e-6 or b["y"] + b["h"] <= a["y"] + 1e-6
    for m in lay.marks:
        for k in ("x1", "x2"):
            assert px - 1e-6 <= m[k] <= px + pw + 1e-6


def test_render_pdf_page_size():
    import io
    import pypdfium2 as pdfium
    from PIL import Image
    s = Settings()
    lay = compute_layout(s, ["a", "b"])
    img = Image.new("RGB", (2150, 1299), (240, 240, 240))
    pdf = render_pdf(lay, [img, img], s)
    doc = pdfium.PdfDocument(pdf)
    w, h = doc[0].get_size()
    assert abs(w * 25.4 / 72 - 210) < 0.1 and abs(h * 25.4 / 72 - 297) < 0.1


def test_whiten_normalizes_uneven_illumination_via_pdf():
    import cv2
    import numpy as np
    import pypdfium2 as pdfium
    from PIL import Image

    from print_edit.core.layout import compute_layout
    from print_edit.core.pdf import render_pdf

    s = Settings()
    w, h = 1076, 650
    paper = np.tile(np.linspace(175, 245, w, dtype=np.float32), (h, 1))
    img = np.round(paper).astype(np.uint8)
    cv2.putText(img, "NAME 123", (80, 250), cv2.FONT_HERSHEY_SIMPLEX, 4, 53, 8)
    cv2.line(img, (100, 450), (1000, 450), 53, 3)
    cv2.rectangle(img, (800, 80), (900, 160), 53, -1)
    orig = np.clip(img, 0, 255).astype(np.uint8)
    rgb = Image.fromarray(orig).convert("RGB")
    layout = compute_layout(s, ["01.png"])
    pdf = render_pdf(layout, [rgb], s)
    page = pdfium.PdfDocument(pdf)[0]
    scale = 300 / 72
    arr = np.array(page.render(scale=scale).to_pil().convert("L"))
    sl = layout.slots[0]
    mm = 300 / 25.4
    x0, y0, x1, y1 = (round(v * mm) for v in (sl["x"], sl["y"], sl["x"] + sl["w"], sl["y"] + sl["h"]))
    crop = cv2.resize(arr[y0:y1, x0:x1], (h, w) if layout.card_rotated else (w, h), interpolation=cv2.INTER_AREA)
    if layout.card_rotated:
        crop = np.rot90(crop, k=-1)
    crop = np.ascontiguousarray(crop)
    assert crop.shape == orig.shape
    far = cv2.dilate((orig < 150).astype(np.uint8), np.ones((15, 15), np.uint8)) == 0
    assert (crop[far] >= 250).mean() >= 0.99
    core = cv2.erode((orig < 100).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    assert core.sum() > 500
    assert np.abs(crop[core].astype(int) - orig[core].astype(int)).max() <= 20


def test_whiten_level_zero_disables_and_keeps_pattern():
    import numpy as np
    from PIL import Image

    from print_edit.core.pdf import prepare_image

    arr = np.full((100, 160), 210, np.uint8)
    arr[40:44, 10:150] = 50
    s0 = Settings.model_validate({"correct": {"whiten_level": 0}})
    assert (np.array(prepare_image(Image.fromarray(arr), s0, False)) == arr).all()
    out = np.array(prepare_image(Image.fromarray(arr), Settings(), False))
    assert (out[arr == 210] == 255).all() and (out[arr == 50] == 50).all()


def _pdf_roundtrip(orig):
    import cv2
    import numpy as np
    import pypdfium2 as pdfium
    from PIL import Image

    s = Settings()
    h, w = orig.shape
    layout = compute_layout(s, ["01.png"])
    pdf = render_pdf(layout, [Image.fromarray(orig).convert("RGB")], s)
    arr = np.array(pdfium.PdfDocument(pdf)[0].render(scale=300 / 72).to_pil().convert("L"))
    sl = layout.slots[0]
    mm = 300 / 25.4
    x0, y0, x1, y1 = (round(v * mm) for v in (sl["x"], sl["y"], sl["x"] + sl["w"], sl["y"] + sl["h"]))
    crop = cv2.resize(arr[y0:y1, x0:x1], (h, w) if layout.card_rotated else (w, h), interpolation=cv2.INTER_AREA)
    if layout.card_rotated:
        crop = np.rot90(crop, k=-1)
    return np.ascontiguousarray(crop)


def _blocks_card(paper_row):
    """2150x1299 px(600dpi) の紙に 20x20mm ベタ・全幅10mm帯・細い文字を置く。ベタ・帯は紙に対する比 (150/230, 170/230)。"""
    import cv2
    import numpy as np

    h, w = 1299, 2150
    paper = np.tile(paper_row.astype(np.float32), (h, 1))
    img = paper.copy()
    px = round(20 / 25.4 * 600)
    bh = round(10 / 25.4 * 600)
    solid = (slice(150, 150 + px), slice(200, 200 + px))
    band = (slice(850, 850 + bh), slice(0, w))
    img[solid] = paper[solid] * 150 / 230
    img[band] = paper[band] * 170 / 230
    orig = np.round(img).astype(np.uint8)
    cv2.putText(orig, "NAME", (1100, 400), cv2.FONT_HERSHEY_SIMPLEX, 4, 50, 8)
    return orig, paper, solid, band


def test_whiten_keeps_midtone_solid_and_band_on_flat_paper():
    import numpy as np

    orig, paper, solid, band = _blocks_card(np.full(2150, 230, np.float32))
    crop = _pdf_roundtrip(orig)
    inner = lambda sl, m=40: (slice(sl[0].start + m, sl[0].stop - m), slice(sl[1].start + m, sl[1].stop - m))
    assert abs(np.median(crop[inner(solid)]) - 150) <= 20
    assert abs(np.median(crop[inner(band, 30)][:, 100:-100]) - 170) <= 20
    far = np.zeros(orig.shape, bool)
    far[1150:1280, 100:2000] = True
    assert (crop[far] >= 250).mean() >= 0.99
    import cv2

    text = cv2.erode((orig < 100).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    assert text.sum() > 500 and abs(np.median(crop[text]) - 50) <= 20 and np.percentile(crop[text], 90) <= 70


def test_whiten_keeps_midtone_solid_and_band_on_gradient_paper():
    import numpy as np

    row = np.linspace(175, 245, 2150, dtype=np.float32)
    orig, paper, solid, band = _blocks_card(row)
    crop = _pdf_roundtrip(orig)
    for sl, m in ((solid, 40), (band, 30)):
        reg = (slice(sl[0].start + m, sl[0].stop - m), slice(sl[1].start + m, sl[1].stop - m))
        if sl is band:
            reg = (reg[0], slice(100, -100))
        out = np.median(crop[reg].astype(float))
        expected = np.median(orig[reg].astype(float))
        assert out < 250 and abs(out - expected) <= 25, (out, expected)
    far = np.zeros(orig.shape, bool)
    far[1150:1280, 100:2000] = True
    assert (crop[far] >= 250).mean() >= 0.99
