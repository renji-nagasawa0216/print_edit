"""シート PDF 生成（仕様 5.2）。"""
from __future__ import annotations

import io
import math

import cv2
import numpy as np
from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from .layout import Layout, mark_from_card_side
from .settings import Settings

PT_PER_MM = 72 / 25.4


BG_FLOOR = 128.0


def _poly_terms(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return np.stack([np.ones_like(x), x, y, x * x, x * y, y * y], axis=-1)


def _background_map(gray: np.ndarray) -> np.ndarray:
    """紙の明るさ（なだらかな照明むら）の推定。縮小画像で、紙らしい明るい画素だけを使って
    2次元2次多項式面を繰り返しフィットする。局所の暗部（ベタ・帯・ロゴ）には追従しない。"""
    h, w = gray.shape
    f = min(1.0, 200.0 / max(h, w))
    small = cv2.resize(gray, (max(8, round(w * f)), max(8, round(h * f))), interpolation=cv2.INTER_AREA) if f < 1 else gray
    sh, sw = small.shape
    ys, xs = np.mgrid[0:sh, 0:sw].astype(np.float64)
    terms = _poly_terms(xs / max(sw - 1, 1) * 2 - 1, ys / max(sh - 1, 1) * 2 - 1).reshape(-1, 6)
    v = small.astype(np.float64).ravel()
    mask = v >= np.percentile(v, 60)
    coef = None
    for _ in range(8):
        if mask.sum() < 30:
            break
        coef = np.linalg.lstsq(terms[mask], v[mask], rcond=None)[0]
        fit = terms @ coef
        new_mask = v >= fit * 0.92
        if (new_mask == mask).all():
            break
        mask = new_mask
    if coef is None:
        return np.full(gray.shape, max(float(np.percentile(v, 95)), BG_FLOOR), np.float32)
    bg = (terms @ coef).reshape(sh, sw).astype(np.float32)
    if bg.shape != gray.shape:
        bg = cv2.resize(bg, (w, h), interpolation=cv2.INTER_LINEAR)
    return np.clip(bg, BG_FLOOR, 255.0)


def prepare_image(img: Image.Image, s: Settings, rotate90: bool) -> Image.Image:
    """グレー化と白飛ばしは PDF 生成時に行う（仕様 4.8）。最後に外周を白塗りする（仕様 11.7）。"""
    if rotate90:
        img = img.rotate(90, expand=True)
    if s.print.color_mode == "mono":
        img = img.convert("L")
        lv = s.correct.whiten_level
        if lv > 0:
            arr = np.array(img)
            norm = arr.astype(np.float32) / _background_map(arr) * 255.0
            arr[norm >= lv] = 255
            img = Image.fromarray(arr, "L")
    else:
        img = img.convert("RGB")
    n = s.correct.edge_white_mm
    if n > 0:
        w, h = img.size
        density = max(w, h) / max(s.detect.card_width_mm, s.detect.card_height_mm)
        p = math.ceil(round(n * density, 6))
        arr = np.array(img)
        arr[:p] = 255
        arr[max(h - p, 0):] = 255
        arr[:, :p] = 255
        arr[:, max(w - p, 0):] = 255
        img = Image.fromarray(arr)
    return img


def render_pdf(layout: Layout, images: list[Image.Image], s: Settings) -> bytes:
    """images は layout.slots と同順。"""
    if len(images) != len(layout.slots):
        raise ValueError("images と slots の数が一致しません")
    pw, ph = layout.paper_mm
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(pw * PT_PER_MM, ph * PT_PER_MM))
    for slot, img in zip(layout.slots, images):
        prepared = prepare_image(img, s, layout.card_rotated)
        x = slot["x"] * PT_PER_MM
        y = (ph - slot["y"] - slot["h"]) * PT_PER_MM
        c.drawImage(ImageReader(prepared), x, y, slot["w"] * PT_PER_MM, slot["h"] * PT_PER_MM)
    lay = s.layout
    if layout.marks:
        c.setStrokeGray(lay.mark_gray / 255)
        c.setLineWidth(lay.mark_width_mm * PT_PER_MM)
        dashed = lay.mark_style == "dashed"
        if dashed:
            c.setDash(lay.mark_dash_mm * PT_PER_MM, lay.mark_gap_mm * PT_PER_MM)
        for m in layout.marks:
            x1, y1, x2, y2 = mark_from_card_side(layout, m) if dashed else (m["x1"], m["y1"], m["x2"], m["y2"])
            c.line(x1 * PT_PER_MM, (ph - y1) * PT_PER_MM, x2 * PT_PER_MM, (ph - y2) * PT_PER_MM)
    c.showPage()
    c.save()
    return buf.getvalue()
