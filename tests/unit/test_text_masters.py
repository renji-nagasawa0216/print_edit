"""段階③の保存・親子関係・面付けを公開APIと生成PDFから確認する。"""

import ctypes
import xml.etree.ElementTree as ET

import pypdfium2 as pdfium
import pypdfium2.raw as pdfraw
import pytest
from fastapi.testclient import TestClient
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTCollection, TTFont
from synth import make_scan, save_png

from print_edit.api.app import create_app
from print_edit.core.settings import Settings
from print_edit.home import Home


def make_font(path, family="PrintEdit Test"):
    """ホストのフォントに依存せず、寸法が既知の非対称な輪郭を使う。"""
    cff = path.suffix == ".otf"
    font = FontBuilder(1000, isTTF=not cff)
    font.setupGlyphOrder([".notdef", "A"])
    font.setupCharacterMap({ord("A"): "A"})
    pen = T2CharStringPen(600, None) if cff else TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.lineTo((500, 0))
    pen.lineTo((100, 700))
    pen.closePath()
    if cff:
        font.setupCFF(family.replace(" ", ""), {"FullName": family, "FamilyName": family},
                      {".notdef": T2CharStringPen(600, None).getCharString(), "A": pen.getCharString()}, {})
    else:
        font.setupGlyf({".notdef": TTGlyphPen(None).glyph(), "A": pen.glyph()})
    font.setupHorizontalMetrics({".notdef": (600, 0), "A": (600, 0)})
    font.setupHorizontalHeader(ascent=800, descent=-200)
    font.setupNameTable({"familyName": family, "styleName": "Regular",
                         "uniqueFontIdentifier": family, "fullName": f"{family} Regular",
                         "psName": family.replace(" ", "") + "-Regular"})
    font.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
    font.setupPost()
    font.save(path)


@pytest.fixture
def master(tmp_path):
    home = Home(tmp_path / "data")
    settings = Settings.model_validate({"intake": {"expected_dpi": 150, "stable_wait_s": 0}})
    home.ensure(settings)
    home.save_settings(settings)
    fonts = home.root / "fonts"
    fonts.mkdir(exist_ok=True)
    make_font(fonts / "test.ttf")
    client = TestClient(create_app(home))
    font_list = client.get("/api/fonts")
    assert font_list.status_code == 200, font_list.text
    font_id = next(f["id"] for f in font_list.json() if "PrintEdit Test" in f["name"])
    scan = make_scan([(55, 35, 91, 55, 0)], dpi=150, size_mm=(110, 70), text=False)
    save_png(scan, home.root / "inbox" / "card.png", dpi=150)
    job, = client.post("/api/ingest").json()
    parent, = client.get(f"/api/jobs/{job['job_id']}").json()["cards"]
    response = client.post(f"/api/cards/{parent['id']}/register")
    assert response.status_code == 200, response.text
    box = dict(text="A", font_id=font_id, x_mm=5, y_mm=5, width_mm=35, size_pt=16,
               align="left", bold=False, gray=0)
    return client, home, parent, box


def create_child(client, parent, name, *boxes):
    result = client.post(f"/api/cards/{parent['id']}/text-masters",
                         json={"name": name, "boxes": boxes})
    assert result.is_success, result.text
    child = result.json()
    assert child["reg"] == "master" and child["parent_id"] == parent["id"]
    return child


def test_child_edits_survive_restart_and_parent_delete_names_all_children(master):
    c, home, parent, box = master
    image = c.get("/files/" + parent["image_path"]).content
    first = create_child(c, parent, "営業", box)
    second = create_child(c, parent, "総務", dict(box, align="right"))
    assert len({parent["id"], first["id"], second["id"]}) == 3
    renamed = "営業部"
    new_boxes = [dict(box, x_mm=10), dict(box, text="AA", y_mm=20, bold=True, gray=96)]
    updated = c.put(f"/api/cards/{first['id']}/text-master", json={"name": renamed, "boxes": new_boxes})
    assert updated.is_success, updated.text
    c = TestClient(create_app(home))
    records = {row["id"]: row for row in c.get("/api/cards", params={"reg": "master"}).json()}
    assert records[first["id"]]["name"] == renamed
    for actual, expected in zip(records[first["id"]]["boxes"], new_boxes, strict=True):
        assert expected.items() <= actual.items()
    assert records[second["id"]]["boxes"][0]["align"] == "right"
    assert c.get("/files/" + parent["image_path"]).content == image
    denied = c.delete(f"/api/cards/{parent['id']}")
    assert denied.status_code == 409
    assert renamed in denied.text and "総務" in denied.text
    assert c.delete(f"/api/cards/{first['id']}").is_success
    assert c.delete(f"/api/cards/{parent['id']}").status_code == 409
    assert c.delete(f"/api/cards/{second['id']}").is_success
    assert c.delete(f"/api/cards/{parent['id']}").is_success


def test_invalid_box_is_atomic(master):
    c, _, parent, box = master
    child = create_child(c, parent, "原稿", box)
    for invalid in [dict(box, width_mm=0), dict(box, font_id="missing-font"), dict(box, gray=256)]:
        response = c.put(f"/api/cards/{child['id']}/text-master",
                         json={"name": "未保存", "boxes": [invalid]})
        assert response.status_code == 422, response.text
    rename = c.put(f"/api/cards/{child['id']}/name", json={"name": " "})
    assert rename.status_code == 422, rename.text
    row, = c.get("/api/cards", params={"reg": "master", "q": "原稿"}).json()
    assert row["id"] == child["id"] and row["boxes"] == child["boxes"]


def path_centers_by_gray(data):
    document = pdfium.PdfDocument(data)
    page = document[0]
    by_gray = {}
    try:
        for obj in page.get_objects(filter=[pdfraw.FPDF_PAGEOBJ_PATH]):
            channels = [ctypes.c_uint() for _ in range(4)]
            assert pdfraw.FPDFPageObj_GetFillColor(obj, *(ctypes.byref(c) for c in channels))
            red, green, blue, alpha = (c.value for c in channels)
            assert red == green == blue and alpha == 255
            x0, _, x1, _ = obj.get_bounds()
            by_gray.setdefault(red, []).append((x0 + x1) * 25.4 / 144)
    finally:
        page.close()
        document.close()
    return by_gray


def test_pdf_places_each_outline_only_in_its_slot_and_keeps_saved_sheet(master):
    c, home, parent, box = master
    left = create_child(c, parent, "左", dict(box, gray=24))
    right = create_child(c, parent, "右", dict(box, align="right", gray=144))
    ids = [left["id"], right["id"], parent["id"]]
    preset = home.get_preset().model_dump(mode="json")
    preset["layout"].update(mark_enabled=False, inner_mark_enabled=False)
    request = {"preset": preset, "items": [{"card_id": cid, "count": 1} for cid in ids],
               "slots": {str(i): cid for i, cid in enumerate(ids, 1)}}
    made = c.post("/api/pdf", json=request)
    assert made.status_code == 200, made.text
    sheet, = made.json()["sheets"]
    adjust = c.get(f"/api/sheets/{sheet['id']}/adjust").json()
    assert adjust["slots"] == request["slots"]
    url = "/files/" + adjust["sheet"]["pdf_path"]
    before = c.get(url).content
    glyphs = path_centers_by_gray(before)
    assert set(glyphs) == {24, 144}
    assert all(19 <= x <= 23 for x in glyphs[24])
    assert all(140 <= x <= 145 for x in glyphs[144])
    edited = c.put(f"/api/cards/{left['id']}/text-master", json={"name": "左", "boxes": [dict(box, gray=77)]})
    assert edited.is_success, edited.text
    assert c.get(url).content == before
    overwritten = c.put(f"/api/sheets/{sheet['id']}/pdf", json=request)
    assert overwritten.status_code == 200, overwritten.text
    assert set(path_centers_by_gray(c.get(url).content)) == {77, 144}


def test_custom_opentype_and_collection_faces_render_in_preview(master, tmp_path):
    c, home, _, box = master
    fonts = home.root / "fonts"
    make_font(fonts / "print-edit.otf", "PrintEdit CFF")
    members = []
    for family in ["PrintEdit TTC One", "PrintEdit TTC Two"]:
        path = tmp_path / f"{family}.ttf"
        make_font(path, family)
        members.append(TTFont(path))
    collection = TTCollection()
    collection.fonts = members
    collection.save(fonts / "print-edit.ttc")
    collection.close()
    choices = c.get("/api/fonts").json()
    faces = [f for f in choices if "PrintEdit CFF" in f["name"] or "PrintEdit TTC" in f["name"]]
    assert len(faces) == 3 and len({f["id"] for f in faces}) == 3
    for face in faces:
        response = c.post("/api/text-preview", json={"boxes": [dict(box, font_id=face["id"], bold=True, gray=96)]})
        assert response.status_code == 200, response.text
        paths = ET.fromstring(response.content).findall("{http://www.w3.org/2000/svg}path")
        path, = paths
        assert path.get("d") and path.get("fill") == "#606060"
        assert float(path.attrib["stroke-width"]) > 0


def test_removed_font_does_not_leave_partial_pdf_batch(master):
    c, home, parent, box = master
    child = create_child(c, parent, "後段", box)
    (home.root / "fonts" / "test.ttf").unlink()
    preset = home.get_preset().model_dump(mode="json")
    preset["arrange"]["group"] = "single"
    response = c.post("/api/pdf", json={"preset": preset, "items": [
        {"card_id": parent["id"], "count": 1}, {"card_id": child["id"], "count": 1}
    ]})
    assert response.status_code == 422, response.text
    assert not list(home.jobs.rglob("*.pdf"))
    assert all(row.get("type") != "sheet" for row in c.get("/api/history").json())
