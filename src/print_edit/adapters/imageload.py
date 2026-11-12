"""画像・PDF の読み込み（PDF のラスタライズに pypdfium2 を使うため adapters に置く）。"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = 400_000_000

# pypdfium2 はスレッド非安全（並列呼び出しでプロセスが落ちる）。PIL 変換が終わるまで保持して直列化する
_PDFIUM_LOCK = threading.Lock()


@dataclass
class Loaded:
    rgb: np.ndarray
    meta_dpi: float | None
    warnings: list[str] = field(default_factory=list)


def _to_rgb(im: Image.Image) -> np.ndarray:
    if im.mode.startswith("I;16") or im.mode == "I":
        a = np.array(im).astype(np.float64)
        a = a / 257 if a.max() > 255 else a
        g = np.clip(a, 0, 255).astype(np.uint8)
        return np.stack([g, g, g], axis=-1)
    return np.array(im.convert("RGB"))


def _meta_dpi(im: Image.Image) -> float | None:
    dpi = im.info.get("dpi")
    if not dpi:
        return None
    try:
        v = float(dpi[0])
    except (TypeError, ValueError, IndexError):
        return None
    return v if v > 1 else None


def load_image(path: Path, render_dpi: int) -> Loaded:
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        import pypdfium2 as pdfium

        with _PDFIUM_LOCK:
            doc = pdfium.PdfDocument(str(path))
            try:
                n = len(doc)
                if n < 1:
                    raise ValueError("PDF にページがありません")
                pil = doc[0].render(scale=render_dpi / 72).to_pil()
            finally:
                doc.close()
        return Loaded(_to_rgb(pil), None, ["pdf_multipage_ignored"] if n > 1 else [])
    with Image.open(path) as im:
        im.load()
        return Loaded(_to_rgb(im), _meta_dpi(im))


def render_pdf_png(path: Path, dpi: int) -> bytes:
    """PDF の 1 ページ目を PNG にして返す（シート画像用）。"""
    import io

    import pypdfium2 as pdfium

    with _PDFIUM_LOCK:
        doc = pdfium.PdfDocument(str(path))
        try:
            pil = doc[0].render(scale=dpi / 72).to_pil()
        finally:
            doc.close()
    buf = io.BytesIO()
    pil.convert("RGB").save(buf, format="PNG", dpi=(dpi, dpi))
    return buf.getvalue()
