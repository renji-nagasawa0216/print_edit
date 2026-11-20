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
    inner_marks: list[dict] = field(default_factory=list)

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


def _clip_axis_segment(
    x1: float, y1: float, x2: float, y2: float, lo_x: float, hi_x: float, lo_y: float, hi_y: float
) -> tuple[float, float, float, float] | None:
    """軸平行の線分を矩形でクリップする。まるごと域外なら None（寄せて残さない）。境界ちょうどは残す。"""
    eps = 1e-9
    if x1 == x2:
        if x1 < lo_x - eps or x1 > hi_x + eps:
            return None
        x1 = x2 = _clip(x1, lo_x, hi_x)
        if max(y1, y2) < lo_y - eps or min(y1, y2) > hi_y + eps:
            return None
        return x1, _clip(y1, lo_y, hi_y), x2, _clip(y2, lo_y, hi_y)
    if y1 == y2:
        if y1 < lo_y - eps or y1 > hi_y + eps:
            return None
        y1 = y2 = _clip(y1, lo_y, hi_y)
        if max(x1, x2) < lo_x - eps or min(x1, x2) > hi_x + eps:
            return None
        return _clip(x1, lo_x, hi_x), y1, _clip(x2, lo_x, hi_x), y2
    return _clip(x1, lo_x, hi_x), _clip(y1, lo_y, hi_y), _clip(x2, lo_x, hi_x), _clip(y2, lo_y, hi_y)


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
    n = len(names)
    used_cols = min(n, cap.columns) if n > 0 else cap.columns
    used_rows = math.ceil(n / cap.columns) if n > 0 else cap.rows
    full_w = cap.columns * cw + (cap.columns - 1) * lay.gap_x_mm
    full_h = cap.rows * ch + (cap.rows - 1) * lay.gap_y_mm
    used_w = used_cols * cw + (used_cols - 1) * lay.gap_x_mm
    used_h = used_rows * ch + (used_rows - 1) * lay.gap_y_mm
    if lay.align_x == "left":
        x0, ref_x = px, px
    elif lay.align_x == "right":
        x0, ref_x = px + pw - used_w, px + pw
    else:
        x0, ref_x = px + (pw - full_w) / 2, lay.paper_width_mm / 2
    if lay.align_y == "top":
        y0, ref_y = py, py
    elif lay.align_y == "bottom":
        y0, ref_y = py + ph - used_h, py + ph
    else:
        y0, ref_y = py + (ph - full_h) / 2, lay.paper_height_mm / 2
    # 左・上の寄せ先の組み合わせだけ、名刺の左上の角を紙の角（0, 0）に置く（印字不可幅の内側へは寄せない）。
    # 印字できない分はプリンター側で切れる。容量の計算（列×行）は印字可能域のまま
    corner = lay.align_x == "left" and lay.align_y == "top"
    if corner:
        x0 = y0 = ref_x = ref_y = 0.0
    sx, sy = settings.print.scale_x, settings.print.scale_y

    def tx(x: float) -> float:
        return ref_x + (x - ref_x) * sx

    def ty(y: float) -> float:
        return ref_y + (y - ref_y) * sy

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
    inner_marks: list[dict] = []
    if n > 0:
        xs = sorted({round(x0 + c * (cw + lay.gap_x_mm) + off, 6) for c in range(used_cols) for off in (0.0, cw)})
        ys = sorted({round(y0 + r * (ch + lay.gap_y_mm) + off, 6) for r in range(used_rows) for off in (0.0, ch)})
        lo_x, hi_x = (0.0 if corner else px), px + pw
        lo_y, hi_y = (0.0 if corner else py), py + ph
        if lay.mark_enabled:
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
            for x1, y1, x2, y2 in segs:
                x1, x2 = _clip(tx(x1), lo_x, hi_x), _clip(tx(x2), lo_x, hi_x)
                y1, y2 = _clip(ty(y1), lo_y, hi_y), _clip(ty(y2), lo_y, hi_y)
                if abs(x2 - x1) + abs(y2 - y1) < 1e-9:
                    continue
                marks.append({"x1": round(x1, 6), "y1": round(y1, 6), "x2": round(x2, 6), "y2": round(y2, 6)})

        il = lay.inner_mark_length_mm
        if lay.inner_mark_enabled and il > 0:
            xmin, xmax, ymin, ymax = xs[0], xs[-1], ys[0], ys[-1]
            isegs = []
            if lay.inner_mark_mode == "cross":
                # すべての交点（端・隅を含む）に十字。名刺を並べた範囲の外へは出さない（外は名刺外トンボの役目）。
                # 紙の端へ寄せた側（align が left/right/top/bottom）は、その外周に沿う腕を描かない（内向きの腕は描く）
                drop_x = xmin if lay.align_x == "left" else xmax if lay.align_x == "right" else None
                drop_y = ymin if lay.align_y == "top" else ymax if lay.align_y == "bottom" else None
                for x in xs:
                    for y in ys:
                        if x != drop_x:
                            isegs += [(x, y, x, max(y - il, ymin)), (x, y, x, min(y + il, ymax))]
                        if y != drop_y:
                            isegs += [(x, y, max(x - il, xmin), y), (x, y, min(x + il, xmax), y)]
            else:
                for x in xs:
                    if x != xmin and x != xmax:
                        for y in ys:
                            if y > ymin:
                                isegs.append((x, y, x, max(y - il, ymin)))
                            if y < ymax:
                                isegs.append((x, y, x, min(y + il, ymax)))
                for y in ys:
                    if y != ymin and y != ymax:
                        for x in xs:
                            if x > xmin:
                                isegs.append((x, y, max(x - il, xmin), y))
                            if x < xmax:
                                isegs.append((x, y, min(x + il, xmax), y))
            for x1, y1, x2, y2 in isegs:
                clipped = _clip_axis_segment(tx(x1), ty(y1), tx(x2), ty(y2), lo_x, hi_x, lo_y, hi_y)
                if clipped is None:
                    continue
                x1, y1, x2, y2 = clipped
                if abs(x2 - x1) + abs(y2 - y1) < 1e-9:
                    continue
                inner_marks.append({"x1": round(x1, 6), "y1": round(y1, 6), "x2": round(x2, 6), "y2": round(y2, 6)})

    return Layout(
        paper_mm=(lay.paper_width_mm, lay.paper_height_mm),
        printable_mm=(px, py, pw, ph),
        capacity=cap.capacity,
        columns=cap.columns,
        rows=cap.rows,
        card_rotated=cap.card_rotated,
        slots=slots,
        marks=marks,
        inner_marks=inner_marks,
    )


def sheet_size(settings) -> int:
    """1 シートに載せる枚数（cards_per_sheet か容量）。"""
    from .settings import capacity_of

    cap = capacity_of(settings).capacity
    n = settings.layout.cards_per_sheet
    return n if n else cap
