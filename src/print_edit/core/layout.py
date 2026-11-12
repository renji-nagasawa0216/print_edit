"""面付け計算（仕様 5.1・5.2）。純粋な幾何計算のみ。"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

_EPS = 1e-9


@dataclass(frozen=True)
class Capacity:
    capacity: int
    columns: int
    rows: int
    card_rotated: bool

    def to_dict(self) -> dict:
        return {
            "capacity": self.capacity,
            "columns": self.columns,
            "rows": self.rows,
            "card_rotated": self.card_rotated,
        }


def printable_area(paper_w: float, paper_h: float, unprintable: float) -> tuple[float, float, float, float]:
    return (unprintable, unprintable, paper_w - 2 * unprintable, paper_h - 2 * unprintable)


def _count(avail: float, size: float, gap: float) -> int:
    if avail <= 0 or size <= 0:
        return 0
    return max(0, math.floor((avail + gap) / (size + gap) + _EPS))


def compute_capacity(
    paper_w: float,
    paper_h: float,
    unprintable: float,
    card_long: float,
    card_short: float,
    gap_x: float,
    gap_y: float,
) -> Capacity:
    _, _, pw, ph = printable_area(paper_w, paper_h, unprintable)
    cols = _count(pw, card_long, gap_x)
    rows = _count(ph, card_short, gap_y)
    rcols = _count(pw, card_short, gap_x)
    rrows = _count(ph, card_long, gap_y)
    if rcols * rrows > cols * rows:
        return Capacity(rcols * rrows, rcols, rrows, True)
    return Capacity(cols * rows, cols, rows, False)


def mark_from_card_side(layout: "Layout", m: dict) -> tuple[float, float, float, float]:
    """トンボを (カード側の端 → 外側の端) の向きに揃えた座標を返す。"""
    px, py, pw, ph = layout.printable_mm
    cx, cy = px + pw / 2, py + ph / 2
    d1 = (m["x1"] - cx) ** 2 + (m["y1"] - cy) ** 2
    d2 = (m["x2"] - cx) ** 2 + (m["y2"] - cy) ** 2
    if d1 <= d2:
        return m["x1"], m["y1"], m["x2"], m["y2"]
    return m["x2"], m["y2"], m["x1"], m["y1"]


@dataclass
class Layout:
    paper_mm: tuple[float, float]
    printable_mm: tuple[float, float, float, float]
    capacity: int
    columns: int
    rows: int
    card_rotated: bool
    slots: list[dict] = field(default_factory=list)
    marks: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "paper_mm": list(self.paper_mm),
            "printable_mm": [round(v, 6) for v in self.printable_mm],
            "capacity": self.capacity,
            "columns": self.columns,
            "rows": self.rows,
            "card_rotated": self.card_rotated,
            "slots": self.slots,
            "marks": self.marks,
        }


def _clip(v: float, lo: float, hi: float) -> float:
    return min(max(v, lo), hi)


def compute_layout(settings, names: list[str]) -> Layout:
    """names の各要素を上の行から・行内は左から割り当てる。len(names) は capacity 以下。"""
    d, lay, dev = settings.detect, settings.layout, settings.device
    long_mm = max(d.card_width_mm, d.card_height_mm)
    short_mm = min(d.card_width_mm, d.card_height_mm)
    cap = compute_capacity(
        lay.paper_width_mm, lay.paper_height_mm, dev.unprintable_mm, long_mm, short_mm, lay.gap_x_mm, lay.gap_y_mm
    )
    if len(names) > cap.capacity:
        raise ValueError(f"cards ({len(names)}) exceed capacity ({cap.capacity})")
    cw, ch = (short_mm, long_mm) if cap.card_rotated else (long_mm, short_mm)
    px, py, pw, ph = printable_area(lay.paper_width_mm, lay.paper_height_mm, dev.unprintable_mm)
    grid_w = cap.columns * cw + (cap.columns - 1) * lay.gap_x_mm
    grid_h = cap.rows * ch + (cap.rows - 1) * lay.gap_y_mm
    x0 = px + (pw - grid_w) / 2
    y0 = py + (ph - grid_h) / 2
    pcx, pcy = lay.paper_width_mm / 2, lay.paper_height_mm / 2
    sx, sy = settings.print.scale_x, settings.print.scale_y

    def tx(x: float) -> float:
        return pcx + (x - pcx) * sx

    def ty(y: float) -> float:
        return pcy + (y - pcy) * sy

    n = len(names)
    slots = []
    for i, name in enumerate(names):
        r, c = divmod(i, cap.columns)
        x = x0 + c * (cw + lay.gap_x_mm)
        y = y0 + r * (ch + lay.gap_y_mm)
        slots.append(
            {
                "index": i + 1,
                "x": round(tx(x), 6),
                "y": round(ty(y), 6),
                "w": round(cw * sx, 6),
                "h": round(ch * sy, 6),
                "card": name,
            }
        )

    marks: list[dict] = []
    if lay.mark_enabled and n > 0:
        used_cols = min(n, cap.columns)
        used_rows = math.ceil(n / cap.columns)
        xs = sorted({round(x0 + c * (cw + lay.gap_x_mm) + off, 6) for c in range(used_cols) for off in (0.0, cw)})
        ys = sorted({round(y0 + r * (ch + lay.gap_y_mm) + off, 6) for r in range(used_rows) for off in (0.0, ch)})
        left, top = x0, y0
        right = x0 + (used_cols - 1) * (cw + lay.gap_x_mm) + cw
        bottom = y0 + (used_rows - 1) * (ch + lay.gap_y_mm) + ch
        o, ln = lay.mark_offset_mm, lay.mark_length_mm
        segs = []
        for x in xs:
            segs.append((x, top - o - ln, x, top - o))
            segs.append((x, bottom + o, x, bottom + o + ln))
        for y in ys:
            segs.append((left - o - ln, y, left - o, y))
            segs.append((right + o, y, right + o + ln, y))
        lo_x, hi_x = px, px + pw
        lo_y, hi_y = py, py + ph
        for x1, y1, x2, y2 in segs:
            x1, x2 = _clip(tx(x1), lo_x, hi_x), _clip(tx(x2), lo_x, hi_x)
            y1, y2 = _clip(ty(y1), lo_y, hi_y), _clip(ty(y2), lo_y, hi_y)
            if abs(x2 - x1) + abs(y2 - y1) < 1e-9:
                continue
            marks.append({"x1": round(x1, 6), "y1": round(y1, 6), "x2": round(x2, 6), "y2": round(y2, 6)})

    return Layout(
        paper_mm=(lay.paper_width_mm, lay.paper_height_mm),
        printable_mm=(px, py, pw, ph),
        capacity=cap.capacity,
        columns=cap.columns,
        rows=cap.rows,
        card_rotated=cap.card_rotated,
        slots=slots,
        marks=marks,
    )


def sheet_size(settings) -> int:
    """1 シートに載せる枚数（cards_per_sheet か容量）。"""
    from .settings import capacity_of

    cap = capacity_of(settings).capacity
    n = settings.layout.cards_per_sheet
    return n if n else cap
