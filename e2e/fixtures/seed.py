"""正本 #1_main.md の前提データを、ケース専用の空の home に作る。"""
import json
import re
import shutil
import sqlite3
import sys
from pathlib import Path

from print_edit.core.settings import Preset
from print_edit.store.db import Store

FIXTURES = Path(__file__).resolve().parent
ROOT = FIXTURES.parents[1]
IMAGES = ROOT / "tests/acceptance/fixtures/images"
CARDS = ROOT / "tests/acceptance/fixtures/cards"
PDF = ROOT / "tests/acceptance/extra_fixtures/one.pdf"


def dataset(tc):
    # TC 表の4列目が前提データ。対応していないデータを空の home で代用しない。
    for line in (ROOT / "ai_docs/specs/#1_main.md").read_text().splitlines():
        if line.startswith(f"| {tc} |"):
            match = re.search(r"D[0-9][a-z]?", line.split("|")[4])
            if match and match[0] in {
                "D0", "D1", "D1s", "D1o", "D1i", "D2", "D2b", "D2l", "D2o", "D3",
                "D4", "D4a", "D4b", "D4c", "D4d", "D5", "D6", "D6n", "D7", "D7o",
            }:
                return match[0]
            raise ValueError(f"Unsupported fixture for {tc}: {line.split('|')[4]}")
    raise ValueError(f"Unknown case: {tc}")


def job(db, root, jid, source, day, status="ok"):
    folder = root / "jobs" / jid
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(IMAGES / "a1_deg_0.png", folder / "source.png")
    db.execute("INSERT INTO jobs(id,source_name,sha256,status,warnings,dpi,created_at) "
               "VALUES(?,?,?,?,?,600,?)", (jid, source, jid, status, "[]", f"2026-11-{day:02}T10:00:00"))


def card(db, root, cid, jid, idx, status, reg=None, name=None):
    path = Path("jobs") / jid / f"card_{cid}.png"
    shutil.copyfile(CARDS / f"card_{cid:02}.png", root / path)
    db.execute("INSERT INTO cards(id,job_id,idx,status,image_path) VALUES(?,?,?,?,?)",
               (cid, jid, idx, status, str(path)))
    if reg:
        db.execute("UPDATE cards SET reg=?,name=? WHERE id=?", (reg, name, cid))


def sheet(db, root, sid, jid, status, slots, day=3, snapshot=True):
    path = Path("jobs") / (jid or "_pdf") / "sheets" / f"{sid:02}.pdf"
    (root / path).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PDF, root / path)
    data = {"v": 1, "settings": Preset().model_dump(),
            "items": [{"card_id": c, "count": slots.count(c)} for c in dict.fromkeys(slots)]}
    db.execute("INSERT INTO sheets(id,job_id,pdf_path,status,created_at,snapshot) VALUES(?,?,?,?,?,?)",
               (sid, jid, str(path), status, f"2026-11-{day:02}T10:00:00", json.dumps(data) if snapshot else None))
    db.executemany("INSERT INTO sheet_cards(sheet_id,card_id,slot) VALUES(?,?,?)",
                   [(sid, c, i) for i, c in enumerate(slots, 1)])


def inbox(root, n, review):
    folder = root / "inbox"
    folder.mkdir()
    images = sorted(IMAGES.glob("a1_deg_*.png"))
    for i, source in enumerate(images[:n], 1):
        shutil.copyfile(source, folder / f"scan_{i:02}.png")
    if review:
        shutil.copyfile(IMAGES / "a5_wrong_size_0.png", folder / "notcard.png")


def seed(tc, root):
    data = dataset(tc)
    cfg = {
        "intake": {"stable_wait_s": 0},
        "print": {"output": "lp" if tc in ("N-69", "E-39") else "pdf", "auto_print": tc == "N-70"},
    }
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise ValueError(f"Test home must start empty: {root}")
    if data.startswith("D4"):
        cfg["print"].update(timing={"D4a": "duplicate", "D4d": "duplicate", "D4c": "fill"}.get(data, "per_scan"),
                            duplicate_count=3 if data == "D4a" else None)
        with sqlite3.connect(root / "db.sqlite3") as db:
            db.executescript((FIXTURES / "legacy.sql").read_text())
            for i, status in enumerate(("ok", "printed", "held", "pending", "review", "discarded"), 1):
                job(db, root, f"J{i}", f"scan_{i}.jpg", i)
                card(db, root, i, f"J{i}", 1, status)
    (root / "config.json").write_text(json.dumps(cfg))
    if data.startswith("D4"):
        return
    if data.startswith("D6") or data == "D1i":
        n = {"N-74": 12, "B-11": 10, "B-12": 11}.get(tc, 3)
        inbox(root, n, data == "D6" and tc != "N-74")
    store = Store(root / "db.sqlite3")
    preset = Preset()
    store.add_preset("既定", preset.model_dump(), builtin=True)
    if data == "D5":
        large = Preset()
        large.layout.cards_per_sheet = 4
        large.arrange.order = "col"
        store.add_preset("名刺大", large.model_dump())
        store.add_preset("枠だけ", preset.model_dump())
    if data[:2] not in ("D1", "D2", "D3", "D7"):
        return
    with sqlite3.connect(root / "db.sqlite3") as db:
        pending = data.startswith("D1")
        job(db, root, "JA", "scan_a.jpg", 1)
        job(db, root, "JB", "scan_b.jpg", 2, "review" if pending else "ok")
        if pending:
            cards = [(1, "JA", 0), (2, "JA", 1), (3, "JB", 0), (4, "JB", 1)]
            for cid, jid, idx in reversed(cards) if data == "D1o" else cards:
                card(db, root, cid, jid, idx, "review" if cid == 4 else "ok",
                     "discarded" if tc == "B-05" and cid > 1 else "pending")
            if data == "D1s":
                sheet(db, root, 1, "JA", "sent", [1])
            return
        rows = [(1, "JA", 0, "Alpha"), (2, "JB", 0, "鈴木太郎"), (3, "JA", 1, None)]
        if data == "D2o":
            rows = [rows[1], rows[2], rows[0]]
        if data.startswith("D7"):
            rows = rows[:1]
        for cid, jid, idx, name in rows:
            card(db, root, cid, jid, idx, "ok", "master", name)
        for cid in range(4, {"B-09": 11, "N-54": 12}.get(tc, 4)):
            card(db, root, cid, "JB", cid, "ok", "master", f"X{cid-3}")
        if data.startswith("D3"):
            for sid, status in enumerate(("held", "sent", "error", "discarded", "held", "sent", "sent"), 1):
                slots = {6: [1], 7: [1] * 5 + [2] * 5}.get(sid, [1, 2])
                sheet(db, root, sid, None if sid == 7 else "JA", status, slots,
                      day=10 if sid == 7 else 3, snapshot=sid != 6)
        if data.startswith("D7"):
            for sid in (range(5, 0, -1) if data == "D7o" else range(1, 6)):
                sheet(db, root, sid, "JA", "held", [1], day=4 + sid)


if __name__ == "__main__":
    seed(sys.argv[1], Path(sys.argv[2]))
