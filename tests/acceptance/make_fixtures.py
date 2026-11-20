"""受け入れ試験用の合成画像・設定・期待値を生成する（docs/spec.md のみを根拠にする）。

実装側のコードは import しない。乱数は固定シード。
生成物: tests/acceptance/fixtures/{images,cards,configs}/ と fixtures/expected.json
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
FX = HERE / "fixtures"
DPI = 600
PX_PER_MM = DPI / 25.4
CARD_L, CARD_S = 91.0, 55.0
BG, CARD_V, PAT_V = 30, 235, 60


def mm2px(v: float) -> float:
    return v * PX_PER_MM


# ---------------------------------------------------------------- 描画
def local_to_image(cx, cy, theta_deg, lx, ly):
    """画像座標(y下向き)で時計回りを正とする回転。"""
    t = math.radians(theta_deg)
    c, s = math.cos(t), math.sin(t)
    return (cx + c * lx - s * ly, cy + s * lx + c * ly)


def card_corners(cx, cy, w_mm, h_mm, theta):
    hw, hh = mm2px(w_mm) / 2, mm2px(h_mm) / 2
    return [local_to_image(cx, cy, theta, lx, ly)
            for lx, ly in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))]


def fill_poly(img, pts, val):
    p = np.round(np.array(pts, dtype=np.float64) * 16).astype(np.int32)
    cv2.fillConvexPoly(img, p, val, cv2.LINE_AA, 4)


def draw_card(lum, mask, rng, c, with_pattern=True):
    cx, cy, w, h, th = c["cx"], c["cy"], c["w_mm"], c["h_mm"], c["angle"]
    b = c.get("border_mm", 0.0)
    if b:
        fill_poly(lum, card_corners(cx, cy, w, h, th), 15)
        fill_poly(mask, card_corners(cx, cy, w, h, th), 255)
        w, h = w - 2 * b, h - 2 * b
    corners = card_corners(cx, cy, w, h, th)
    fill_poly(lum, corners, CARD_V)
    fill_poly(mask, corners, 255)
    if not with_pattern:
        return
    # 文字に見立てた暗い模様（縁から 8mm 以上内側）
    hw, hh = mm2px(w) / 2, mm2px(h) / 2
    inset, bar_h, pitch = mm2px(8), mm2px(3), mm2px(8)
    y = -hh + inset
    while y + bar_h <= hh - inset:
        x = -hw + inset
        while x < hw - inset:
            seg = mm2px(rng.uniform(3, 10))
            x2 = min(x + seg, hw - inset)
            poly = [local_to_image(cx, cy, th, x, y), local_to_image(cx, cy, th, x2, y),
                    local_to_image(cx, cy, th, x2, y + bar_h), local_to_image(cx, cy, th, x, y + bar_h)]
            fill_poly(lum, poly, PAT_V)
            x = x2 + mm2px(1.5)
        y += pitch


def render(w, h, cards, *, seed, bg=BG, noise=0.0, illum=False, shadow=False, specks=()):
    rng = np.random.default_rng(seed)
    base = np.full((h, w), float(bg), dtype=np.float32)
    if shadow:
        sh = np.zeros((h, w), np.uint8)
        for c in cards:
            fill_poly(sh, [(x + 90, y + 110) for x, y in card_corners(c["cx"], c["cy"], c["w_mm"], c["h_mm"], c["angle"])], 255)
        sh = cv2.GaussianBlur(sh, (0, 0), 45)
        base *= (1.0 - 0.55 * sh.astype(np.float32) / 255.0)
        del sh
    lum = np.zeros((h, w), np.uint8)
    mask = np.zeros((h, w), np.uint8)
    for c in cards:
        draw_card(lum, mask, rng, c)
    for (sx, sy, size_mm) in specks:
        half = mm2px(size_mm) / 2
        pts = [(sx - half, sy - half), (sx + half, sy - half), (sx + half, sy + half), (sx - half, sy + half)]
        fill_poly(lum, pts, CARD_V)
        fill_poly(mask, pts, 255)
    m = mask.astype(np.float32) / 255.0
    out = base * (1 - m) + lum.astype(np.float32) * m
    del base, m, lum, mask
    if illum:
        gx = np.linspace(0.75, 1.15, w, dtype=np.float32)
        gy = np.linspace(0.85, 1.05, h, dtype=np.float32)
        out *= gx[None, :] * gy[:, None]
    if noise:
        out += rng.normal(0, noise, size=out.shape).astype(np.float32)
    return np.clip(out, 0, 255).astype(np.uint8)


def save_gray(arr, path, dpi=DPI):
    im = Image.fromarray(arr, "L")
    if dpi is None:
        im.save(path, compress_level=3)
    else:
        im.save(path, dpi=(dpi, dpi), compress_level=3)


def truth(c):
    cx, cy = c["cx"], c["cy"]
    corners = card_corners(cx, cy, c["w_mm"], c["h_mm"], c["angle"])
    long_, short_ = max(c["w_mm"], c["h_mm"]), min(c["w_mm"], c["h_mm"])
    return {
        "corners_px": [[round(x, 3), round(y, 3)] for x, y in corners],
        "center_mm": [round(cx / PX_PER_MM, 4), round(cy / PX_PER_MM, 4)],
        "long_mm": long_, "short_mm": short_, "angle_deg": c["angle"],
    }


def tag(a):
    return "0" if a == 0 else (f"p{a}" if a > 0 else f"m{abs(a)}")


def card(cx, cy, angle, w=CARD_L, h=CARD_S, **kw):
    return dict(cx=cx, cy=cy, w_mm=w, h_mm=h, angle=angle, **kw)


# ---------------------------------------------------------------- main
def main():
    rng = np.random.default_rng(20261111)
    for d in ("images", "cards", "configs"):
        (FX / d).mkdir(parents=True, exist_ok=True)
    detect = {}

    def add(name, w, h, cards, *, expected_status, group, dpi=DPI, reasons_card=None, **render_kw):
        arr = render(w, h, cards, seed=int(rng.integers(1 << 30)), **render_kw)
        save_gray(arr, FX / "images" / f"{name}.png", dpi)
        detect[name] = {
            "file": f"images/{name}.png", "group": group, "canvas": [w, h], "dpi_meta": dpi,
            "cards": [truth(c) for c in cards], "expected_status": expected_status,
        }

    def jitter(a):
        return 1500 + float(rng.uniform(-200, 200)), 1500 + float(rng.uniform(-200, 200))

    # A1/A2: 傾き × 600dpi
    for a in (0, 3, -3, 5, -5, 15, -15, 30, -30, 44, -44, 45, -45):
        cx, cy = jitter(a)
        add(f"a1_deg_{tag(a)}", 3000, 3000, [card(cx, cy, a)], expected_status="ok", group="a1")

    # A4: 影・照明むら・ノイズ
    for a in (0, 12, -12, 38, -38):
        cx, cy = jitter(a)
        add(f"a4_robust_{tag(a)}", 3000, 3000, [card(cx, cy, a)], expected_status="ok", group="a4",
            bg=55, noise=6.0, illum=True, shadow=True)

    # A3: 3 枚（行・列の順序）。期待順は中心座標の上→下、同じ行なら左→右
    c3 = [card(1400, 1000, 3), card(3800, 1000, -3), card(2600, 2700, 10)]
    add("a3_three_row", 5200, 3800, c3, expected_status="ok", group="a3")
    detect["a3_three_row"]["expected_order"] = [0, 1, 2]
    cv = [card(1300, 900, -4), card(1500, 2500, 0), card(1400, 4100, 7)]
    add("a3_three_col", 2900, 4900, cv, expected_status="ok", group="a3")
    detect["a3_three_col"]["expected_order"] = [0, 1, 2]
    # 描く順と出力順を無関係にするため、順序を入れ替えて描いた版
    c3b = [card(2600, 2700, -8), card(3800, 1000, 5), card(1400, 1000, -20)]
    add("a3_three_shuffled", 5200, 3800, c3b, expected_status="ok", group="a3")
    detect["a3_three_shuffled"]["expected_order"] = [2, 1, 0]

    # A5: 異常
    lp = mm2px(CARD_L)
    sp = mm2px(CARD_S)
    add("a5_touch_h", 4800, 2400, [card(1325, 1200, 0), card(1325 + lp, 1200, 0)],
        expected_status="review", group="a5")
    add("a5_touch_v", 2800, 3100, [card(1400, 900, 0), card(1400, 900 + sp, 0)],
        expected_status="review", group="a5")
    add("a5_dark_border", 3000, 2000, [card(1500, 1000, 0, border_mm=3.0)], expected_status="review", group="a5")
    add("a5_wrong_size_0", 3000, 2000, [card(1500, 1000, 0, w=89, h=51)], expected_status="review", group="a5")
    add("a5_wrong_size_15", 3000, 3000, [card(1500, 1500, 15, w=89, h=51)], expected_status="review", group="a5")
    add("a5_zero_noise", 3000, 2000, [], expected_status="review", group="a5", noise=6.0, illum=True)
    add("a5_zero_speck", 3000, 2000, [], expected_status="review", group="a5", noise=3.0,
        specks=[(1500, 1000, 20.0)])
    # 寸法違いは card の期待 long/short が実寸(89/51)であることを明示
    # 期待 reasons（仕様 4.5）
    for n in ("a5_wrong_size_0", "a5_wrong_size_15"):
        detect[n]["expected_reasons"] = ["size_out_of_tolerance"]

    # A6: 解像度（同一内容で解像度情報だけ変える）
    for name, dpi in (("a6_meta600", 600), ("a6_nometa", None), ("a6_meta300", 300)):
        rng_state = 777
        arr = render(3000, 3000, [card(1500, 1500, 3)], seed=rng_state)
        save_gray(arr, FX / "images" / f"{name}.png", dpi)
        detect[name] = {"file": f"images/{name}.png", "group": "a6", "canvas": [3000, 3000], "dpi_meta": dpi,
                        "cards": [truth(card(1500, 1500, 3))], "expected_status": "ok"}

    # A11: A4 全面 600dpi
    add("a11_a4_full", 4960, 7016, [card(2480, 3508, 7)], expected_status="ok", group="a11",
        noise=3.0, illum=True)

    # 面付け用カード画像（25 枚、RGB、2150x1299）
    n_cards = 25
    for i in range(1, n_cards + 1):
        w, h = round(mm2px(CARD_L)), round(mm2px(CARD_S))
        a = np.full((h, w, 3), 245, np.uint8)
        col = (int(rng.integers(0, 200)), int(rng.integers(0, 200)), int(rng.integers(0, 200)))
        cv2.rectangle(a, (60, 60), (w - 60, h - 60), col, 12)
        cv2.putText(a, f"{i:02d}", (w // 2 - 350, h // 2 + 250), cv2.FONT_HERSHEY_SIMPLEX, 12, col, 30, cv2.LINE_AA)
        Image.fromarray(a, "RGB").save(FX / "cards" / f"card_{i:02d}.png", dpi=(DPI, DPI))

    # A7/A8: 面付け設定
    def capacity(paper_w, paper_h, u, cw, ch, gx, gy):
        pw, ph = paper_w - 2 * u, paper_h - 2 * u
        e = 1e-9
        land = (math.floor((pw + gx) / (cw + gx) + e), math.floor((ph + gy) / (ch + gy) + e))
        port = (math.floor((pw + gx) / (ch + gx) + e), math.floor((ph + gy) / (cw + gy) + e))
        if port[0] * port[1] > land[0] * land[1]:
            return port, True
        return land, False

    cases = {
        "default": {},
        "gap_10_5": {"layout": {"gap_x_mm": 10, "gap_y_mm": 5}},
        "paper_a5": {"layout": {"paper_width_mm": 148, "paper_height_mm": 210}},
        "paper_letter": {"layout": {"paper_width_mm": 215.9, "paper_height_mm": 279.4}},
        "card_100x60": {"detect": {"card_width_mm": 100, "card_height_mm": 60}},
        "tie_square200": {"layout": {"paper_width_mm": 200, "paper_height_mm": 200}, "device": {"unprintable_mm": 0}},
        "unprintable_15": {"device": {"unprintable_mm": 15}},
    }
    impose = {}
    for name, cfg in cases.items():
        L, D, V = cfg.get("layout", {}), cfg.get("detect", {}), cfg.get("device", {})
        pwid, phei = L.get("paper_width_mm", 210.0), L.get("paper_height_mm", 297.0)
        u = V.get("unprintable_mm", 4.2)
        cw, ch = D.get("card_width_mm", 91.0), D.get("card_height_mm", 55.0)
        gx, gy = L.get("gap_x_mm", 0.0), L.get("gap_y_mm", 0.0)
        (cols, rows), rot = capacity(pwid, phei, u, cw, ch, gx, gy)
        sw, sh = (ch, cw) if rot else (cw, ch)
        gw, gh = cols * sw + (cols - 1) * gx, rows * sh + (rows - 1) * gy
        x0, y0 = u + (pwid - 2 * u - gw) / 2, u + (phei - 2 * u - gh) / 2
        slots = [{"index": i + 1, "x": x0 + (i % cols) * (sw + gx), "y": y0 + (i // cols) * (sh + gy), "w": sw, "h": sh}
                 for i in range(cols * rows)]
        (FX / "configs" / f"{name}.json").write_text(json.dumps(cfg, indent=1))
        impose[name] = {
            "config": f"configs/{name}.json", "capacity": cols * rows, "columns": cols, "rows": rows,
            "card_rotated": rot, "paper_mm": [pwid, phei], "printable_mm": [u, u, pwid - 2 * u, phei - 2 * u],
            "slots": slots,
        }
    # 枚数の組（設定名 → 枚数）
    counts = {"default": [1, 3, 10, 11, 25], "gap_10_5": [9, 11], "paper_a5": [5], "paper_letter": [9],
              "card_100x60": [9], "tie_square200": [7], "unprintable_15": [7]}
    for k, v in counts.items():
        impose[k]["counts"] = v
    assert impose["default"]["capacity"] == 10 and impose["gap_10_5"]["card_rotated"] is True
    assert impose["paper_a5"]["capacity"] == 4 and impose["tie_square200"]["card_rotated"] is False

    (FX / "expected.json").write_text(json.dumps({"dpi": DPI, "detect": detect, "impose": impose}, indent=1))
    print(f"fixtures: detect={len(detect)} impose_cases={len(impose)} cards={n_cards}")


if __name__ == "__main__":
    main()
