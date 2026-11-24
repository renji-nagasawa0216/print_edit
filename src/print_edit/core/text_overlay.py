"""Editable name-card lettering. Coordinates are mm from the upright card's top left."""
from __future__ import annotations

import hashlib
import struct
import sys
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

import uharfbuzz as hb
from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont, TTLibError
from pydantic import BaseModel, ConfigDict, Field

PT_PER_MM = 72 / 25.4


class TextBox(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    text: str = Field(max_length=2000)
    font_id: str = Field(min_length=1, max_length=128)
    x_mm: float = Field(ge=0, le=1000)
    y_mm: float = Field(ge=0, le=1000)
    width_mm: float = Field(gt=0, le=1000)
    size_pt: float = Field(default=12, ge=1, le=300)
    align: Literal["left", "center", "right"] = "left"
    bold: bool = False
    gray: int = Field(default=0, ge=0, le=255)


@dataclass(frozen=True)
class Face:
    id: str
    name: str
    family: str
    weight: int
    italic: bool
    variable_bold: bool
    path: Path
    index: int
    stamp: tuple[int, int]


@lru_cache(maxsize=2048)
def _read_faces(path: Path, key: str, stamp: tuple[int, int]) -> tuple[Face, ...]:
    faces = []
    try:
        with path.open("rb") as stream:
            header = stream.read(12)
        count = struct.unpack(">I", header[8:12])[0] if header.startswith(b"ttcf") else 1
        for index in range(count):
            with TTFont(path, fontNumber=index, lazy=True) as font:
                if not any(table in font for table in ("glyf", "CFF ", "CFF2")):
                    continue
                names = font["name"]
                family = names.getBestFamilyName() or path.stem
                label = names.getBestFullName() or family
                os2 = font.get("OS/2")
                weight = os2.usWeightClass if os2 else 400
                variable_bold = "fvar" in font and any(
                    axis.axisTag == "wght" and axis.maxValue >= 700 for axis in font["fvar"].axes
                )
                face_id = hashlib.sha256(f"{key}#{index}".encode()).hexdigest()[:24]
                faces.append(Face(face_id, label, family, weight, bool(font["head"].macStyle & 2),
                                  variable_bold, path, index, stamp))
    except (OSError, TTLibError, KeyError, ValueError, struct.error):
        # An unreadable or non-outline font must not hide the rest of the catalog.
        pass
    return tuple(faces)


def _catalog(home_root: Path) -> dict[str, Face]:
    roots = [("custom", Path(home_root) / "fonts")]
    if sys.platform == "darwin":
        roots.extend((key, Path(path).expanduser()) for key, path in (
            ("user", "~/Library/Fonts"), ("local", "/Library/Fonts"), ("system", "/System/Library/Fonts"),
        ))
    else:
        roots.extend((key, Path(path).expanduser()) for key, path in (
            ("user", "~/.local/share/fonts"), ("system", "/usr/share/fonts"),
            ("local", "/usr/local/share/fonts"),
        ))
    faces = {}
    for prefix, root in roots:
        for path in sorted(root.rglob("*")):
            if path.name.startswith(".") or path.suffix.lower() not in (".ttf", ".otf", ".ttc"):
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            key = f"{prefix}/{path.relative_to(root).as_posix()}"
            for face in _read_faces(path, key, (stat.st_mtime_ns, stat.st_size)):
                faces[face.id] = face
    return faces


def list_fonts(home_root: Path) -> list[dict]:
    faces = sorted(_catalog(home_root).values(), key=lambda f: (f.name.casefold(), f.id))
    return [{"id": f.id, "name": f.name} for f in faces]


def _resolve(faces: dict[str, Face], box: TextBox) -> tuple[Face, bool]:
    face = faces.get(box.font_id)
    if face is None:
        raise ValueError("指定したフォントが見つかりません。フォントを選び直してください")
    if not box.bold or face.weight >= 600 or face.variable_bold:
        return face, False
    alternatives = [f for f in faces.values() if f.family == face.family and f.italic == face.italic and f.weight >= 600]
    if alternatives:
        return min(alternatives, key=lambda f: (abs(f.weight - 700), f.id)), False
    return face, True


class _Outline(BasePen):
    """Expand components and convert quadratic splines to PDF-compatible cubic paths."""
    def __init__(self, glyphs):
        super().__init__(glyphs)
        self.ops = []

    def _moveTo(self, p):
        self.ops.append(("M", *p))

    def _lineTo(self, p):
        self.ops.append(("L", *p))

    def _curveToOne(self, a, b, c):
        self.ops.append(("C", *a, *b, *c))

    def _closePath(self):
        self.ops.append(("Z",))


@lru_cache(maxsize=8)
def _load(face: Face, variable_bold: bool):
    font = TTFont(face.path, fontNumber=face.index)
    shaper = hb.Font(hb.Face(hb.Blob.from_file_path(str(face.path)), face.index))
    location = {"wght": 700} if variable_bold else {}
    shaper.set_variations(location)
    glyphs = font.getGlyphSet(location=location)
    return font, glyphs, shaper


@lru_cache(maxsize=4096)
def _outline(face: Face, variable_bold: bool, glyph_id: int):
    font, glyphs, _ = _load(face, variable_bold)
    pen = _Outline(glyphs)
    glyphs[font.getGlyphName(glyph_id)].draw(pen)
    return tuple(pen.ops)


def _shape(shaper, text):
    buf = hb.Buffer()
    buf.add_codepoints([ord(c) for c in text])
    buf.guess_segment_properties()
    hb.shape(shaper, buf)
    return list(zip(buf.glyph_infos, buf.glyph_positions))


def _lines(text, shaper, width):
    for paragraph in text.replace("\r\n", "\n").replace("\r", "\n").expandtabs(4).split("\n"):
        if not paragraph:
            yield []
            continue
        glyphs = _shape(shaper, paragraph)
        advances = defaultdict(int)
        for info, pos in glyphs:
            if info.codepoint == 0:
                raise ValueError(f"選択したフォントには「{paragraph[info.cluster]}」の字形がありません")
            advances[info.cluster] += pos.x_advance
        if sum(advances.values()) <= width:
            yield glyphs
            continue
        start, occupied = 0, 0
        for cluster, advance in sorted(advances.items()):
            if cluster > start and occupied + advance > width:
                yield _shape(shaper, paragraph[start:cluster])
                start, occupied = cluster, 0
            occupied += advance
        yield _shape(shaper, paragraph[start:])


def _glyphs(home_root, boxes):
    faces = _catalog(home_root)
    for raw in boxes:
        box = TextBox.model_validate(raw)
        face, synthetic = _resolve(faces, box)
        variable_bold = box.bold and face.variable_bold
        font, _, shaper = _load(face, variable_bold)
        units = font["head"].unitsPerEm
        scale = box.size_pt / units
        width = box.width_mm * PT_PER_MM
        top = box.y_mm * PT_PER_MM
        hhea = font["hhea"]
        baseline = top + hhea.ascent * scale
        leading = max(units, hhea.ascent - hhea.descent + hhea.lineGap) * scale
        for line in _lines(box.text, shaper, width / scale):
            advance = sum(pos.x_advance for _, pos in line) * scale
            align = {"left": 0, "center": 0.5, "right": 1}[box.align]
            x = box.x_mm * PT_PER_MM + align * (width - advance)
            for info, pos in line:
                outline = _outline(face, variable_bold, info.codepoint)
                if outline:
                    yield (outline, x + pos.x_offset * scale, baseline - pos.y_offset * scale,
                           scale, box.gray, units * 0.035 if synthetic else 0)
                x += pos.x_advance * scale
            baseline += leading


def validate_fonts(home_root, boxes):
    faces = _catalog(home_root)
    for raw in boxes:
        box = TextBox.model_validate(raw)
        face, _ = _resolve(faces, box)
        _, _, shaper = _load(face, box.bold and face.variable_bold)
        for _ in _lines(box.text, shaper, float("inf")):
            pass


def draw_overlay(canvas, home_root, boxes, width_mm, height_mm):
    height = height_mm * PT_PER_MM
    canvas.saveState()
    try:
        clip = canvas.beginPath()
        clip.rect(0, 0, width_mm * PT_PER_MM, height)
        canvas.clipPath(clip, stroke=0, fill=0)
        for outline, x, y, scale, gray, stroke in _glyphs(home_root, boxes):
            canvas.saveState()
            try:
                canvas.translate(x, height - y)
                canvas.scale(scale, scale)
                canvas.setFillGray(gray / 255)
                canvas.setStrokeGray(gray / 255)
                canvas.setLineWidth(stroke)
                canvas.setLineJoin(1)
                path = canvas.beginPath()
                ops = {"M": path.moveTo, "L": path.lineTo, "C": path.curveTo, "Z": path.close}
                for op, *coords in outline:
                    ops[op](*coords)
                canvas.drawPath(path, stroke=bool(stroke), fill=1, fillMode=1)
            finally:
                canvas.restoreState()
    finally:
        canvas.restoreState()


def render_overlay_svg(home_root, boxes, width_mm, height_mm):
    width, height = width_mm * PT_PER_MM, height_mm * PT_PER_MM
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:g} {height:g}" overflow="hidden">']
    for outline, x, y, scale, gray, stroke in _glyphs(home_root, boxes):
        path = "".join(op + " ".join(f"{v:.6g}" for v in coords) for op, *coords in outline)
        color = f"#{gray:02x}{gray:02x}{gray:02x}"
        parts.append(f'<path d="{path}" transform="translate({x:.7g} {y:.7g}) scale({scale:.7g} {-scale:.7g})" '
                     f'fill="{color}" stroke="{color}" stroke-width="{stroke:g}" stroke-linejoin="round"/>')
    parts.append("</svg>")
    return "".join(parts)
