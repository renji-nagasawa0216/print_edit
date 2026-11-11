import math
import numpy as np
import cv2
from PIL import Image

MM = 25.4


def rect_corners(cx, cy, w, h, angle_deg):
    """mm 座標。angle は長辺の傾き（画像座標で時計回り正）。順: tl,tr,br,bl。"""
    r = math.radians(angle_deg)
    u = np.array([math.cos(r), math.sin(r)])
    v = np.array([-u[1], u[0]])
    c = np.array([cx, cy])
    return [c - u * w / 2 - v * h / 2, c + u * w / 2 - v * h / 2, c + u * w / 2 + v * h / 2, c - u * w / 2 + v * h / 2]


def make_scan(cards, dpi=600, size_mm=(210, 297), bg=30, fg=235, noise=0.0, gradient=0, text=True, seed=0):
    W, H = round(size_mm[0] / MM * dpi), round(size_mm[1] / MM * dpi)
    img = np.full((H, W, 3), bg, np.float32)
    if gradient:
        img += np.linspace(0, gradient, W, dtype=np.float32)[None, :, None]
    shift = 4
    centers = []
    for (cx, cy, w, h, ang) in cards:
        pts = np.array([p / MM * dpi for p in rect_corners(cx, cy, w, h, ang)])
        poly = np.round(pts * (1 << shift)).astype(np.int32)
        layer = np.zeros((H, W), np.uint8)
        cv2.fillPoly(layer, [poly], 255, lineType=cv2.LINE_AA, shift=shift)
        col = np.array([fg, fg - 5, fg - 10], np.float32)
        img = img * (1 - layer[..., None] / 255.0) + col * (layer[..., None] / 255.0)
        centers.append(pts.mean(axis=0))
    if text and centers:
        img = np.clip(img, 0, 255).astype(np.uint8)
        for c in centers:
            cv2.putText(img, "NAME", (int(c[0] - 150), int(c[1])), cv2.FONT_HERSHEY_SIMPLEX, 4, (20, 20, 20), 8)
        img = img.astype(np.float32)
    if noise:
        rng = np.random.default_rng(seed)
        img += rng.normal(0, noise, img.shape).astype(np.float32)
    return np.clip(img, 0, 255).astype(np.uint8)


def save_png(arr, path, dpi=600):
    Image.fromarray(arr).save(path, dpi=(dpi, dpi) if dpi else None)


def save_png_nodpi(arr, path):
    Image.fromarray(arr).save(path)
