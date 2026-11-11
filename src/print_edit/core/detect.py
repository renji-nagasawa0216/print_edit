"""検出・補正（仕様 4 節）。入力は RGB の ndarray。"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

from .settings import Settings

MM = 25.4


def resolve_dpi(meta_dpi: float | None, option: int | None, expected: int) -> tuple[int, str, bool]:
    """(使う dpi, dpi_source, 不一致か)。option > 画像の値 > 設定。不一致は画像の値と基準(option か設定)の比較。"""
    ref = option if option else expected
    mismatch = meta_dpi is not None and abs(meta_dpi - ref) > 1
    if option:
        return int(option), "option", mismatch
    if meta_dpi is not None:
        return int(round(meta_dpi)), "metadata", mismatch
    return int(expected), "config", False


@dataclass
class Card:
    index: int
    corners_px: list[list[float]]
    center_mm: list[float]
    long_mm: float
    short_mm: float
    angle_deg: float
    status: str
    reasons: list[str]
    image: np.ndarray = field(repr=False)

    @property
    def image_name(self) -> str:
        return f"cards/{self.index:02d}.png"

    def to_dict(self) -> dict:
        h, w = self.image.shape[:2]
        return {
            "index": self.index,
            "corners_px": self.corners_px,
            "center_mm": self.center_mm,
            "long_mm": self.long_mm,
            "short_mm": self.short_mm,
            "angle_deg": self.angle_deg,
            "status": self.status,
            "reasons": self.reasons,
            "image": self.image_name,
            "image_width_px": w,
            "image_height_px": h,
        }


@dataclass
class DetectResult:
    status: str
    warnings: list[str]
    cards: list[Card]
    reasons: list[str] = field(default_factory=list)


def _odd(n: float) -> int:
    n = max(3, int(round(n)))
    return n if n % 2 else n + 1


def _binarize(rgb: np.ndarray, dpi: int, threshold: int | None) -> np.ndarray:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    k = _odd(dpi / 100)
    blur = cv2.GaussianBlur(gray, (k, k), 0)
    if threshold is None:
        if int(blur.max()) - int(blur.min()) < 30:  # コントラストが無い（空の原稿台）
            return np.zeros_like(blur)
        _, mask = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    else:
        _, mask = cv2.threshold(blur, threshold, 255, cv2.THRESH_BINARY)
    return mask


def _frame(box: np.ndarray):
    """minAreaRect の四隅から (中心, 長辺単位ベクトル u, 短辺方向 v, L, S, angle) を得る。"""
    e01, e12 = box[1] - box[0], box[2] - box[1]
    l01, l12 = float(np.hypot(*e01)), float(np.hypot(*e12))
    e, L, S = (e01, l01, l12) if l01 >= l12 else (e12, l12, l01)
    ang = math.degrees(math.atan2(e[1], e[0]))
    if ang <= -90:
        ang += 180
    elif ang > 90:
        ang -= 180
    r = math.radians(ang)
    u = np.array([math.cos(r), math.sin(r)])
    v = np.array([-u[1], u[0]])
    center = box.mean(axis=0)
    return center, u, v, L, S, ang


def _warp(rgb: np.ndarray, src: np.ndarray, w: int, h: int) -> np.ndarray:
    dst = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32)
    m = cv2.getPerspectiveTransform(src.astype(np.float32), dst)
    return cv2.warpPerspective(rgb, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def _extract(rgb, center, u, v, L, S, dpi, s: Settings) -> np.ndarray:
    d = s.detect
    long_mm, short_mm = max(d.card_width_mm, d.card_height_mm), min(d.card_width_mm, d.card_height_mm)
    cw, ch = round(long_mm / MM * dpi), round(short_mm / MM * dpi)
    src = np.array(
        [
            center - u * L / 2 - v * S / 2,
            center + u * L / 2 - v * S / 2,
            center + u * L / 2 + v * S / 2,
            center - u * L / 2 + v * S / 2,
        ]
    )
    if s.correct.size_mode == "fit":
        out = _warp(rgb, src, cw, ch)
    else:
        ow, oh = max(1, round(L)), max(1, round(S))
        piece = _warp(rgb, src, ow, oh)
        out = np.full((ch, cw, 3), 255, dtype=np.uint8)
        # 中央合わせ（はみ出す分は切る）
        sx0, dx0 = (0, (cw - ow) // 2) if ow <= cw else ((ow - cw) // 2, 0)
        sy0, dy0 = (0, (ch - oh) // 2) if oh <= ch else ((oh - ch) // 2, 0)
        wcopy, hcopy = min(ow, cw), min(oh, ch)
        out[dy0 : dy0 + hcopy, dx0 : dx0 + wcopy] = piece[sy0 : sy0 + hcopy, sx0 : sx0 + wcopy]
    if s.correct.rotate_180:
        out = cv2.rotate(out, cv2.ROTATE_180)
    return np.ascontiguousarray(out)


def detect_cards(rgb: np.ndarray, dpi: int, s: Settings, dpi_mismatch: bool = False) -> DetectResult:
    d = s.detect
    long_mm, short_mm = max(d.card_width_mm, d.card_height_mm), min(d.card_width_mm, d.card_height_mm)
    px_per_mm = dpi / MM
    min_area = d.min_area_ratio * long_mm * short_mm * px_per_mm**2
    mask = _binarize(rgb, dpi, d.threshold)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    found = []
    for c in contours:
        if len(c) < 5 or cv2.contourArea(c) < min_area:
            continue
        box = cv2.boxPoints(cv2.minAreaRect(c)).astype(np.float64)
        found.append(_frame(box))

    # 上→下、同じ行なら左→右
    found.sort(key=lambda f: f[0][1])
    rows: list[list] = []
    for f in found:
        if rows and f[0][1] - rows[-1][0][0][1] <= 0.5 * rows[-1][0][4]:
            rows[-1].append(f)
        else:
            rows.append([f])
    ordered = [f for row in rows for f in sorted(row, key=lambda f: f[0][0])]

    warnings = ["dpi_mismatch"] if dpi_mismatch else []
    reasons: list[str] = []
    cards: list[Card] = []
    for i, (center, u, v, L, S, ang) in enumerate(ordered, 1):
        lmm, smm = L / px_per_mm, S / px_per_mm
        reasons = []
        if abs(lmm - long_mm) > d.size_tolerance_mm or abs(smm - short_mm) > d.size_tolerance_mm:
            reasons.append("size_out_of_tolerance")
        if dpi_mismatch:
            reasons.append("dpi_mismatch")
        corners = [
            center - u * L / 2 - v * S / 2,
            center + u * L / 2 - v * S / 2,
            center + u * L / 2 + v * S / 2,
            center - u * L / 2 + v * S / 2,
        ]
        cards.append(
            Card(
                index=i,
                corners_px=[[round(float(x), 2), round(float(y), 2)] for x, y in corners],
                center_mm=[round(float(center[0]) / px_per_mm, 3), round(float(center[1]) / px_per_mm, 3)],
                long_mm=round(lmm, 3),
                short_mm=round(smm, 3),
                angle_deg=round(ang, 3),
                status="review" if reasons else "ok",
                reasons=reasons,
                image=_extract(rgb, center, u, v, L, S, dpi, s),
            )
        )
    if not cards:
        status = "review"
        reasons = ["no_cards"]
    else:
        status = "ok" if all(c.status == "ok" for c in cards) else "review"
    return DetectResult(status=status, warnings=warnings, cards=cards, reasons=reasons)
