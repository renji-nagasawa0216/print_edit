"""追加の受け入れテスト。根拠は docs/spec.md のみ。"""
import glob
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import time
from pathlib import Path

import cv2
import httpx
import numpy as np
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).resolve().parent / "extra_fixtures"
DPI = 600
BG, WHITE = 20, 255


def px(mm):
    return int(round(mm / 25.4 * DPI))


def make_scan(w, h, cards, mark_first=False):
    """cards: [(x_px, y_px, w_mm, h_mm)] 暗背景に白カード。"""
    img = np.full((h, w, 3), BG, np.uint8)
    for i, (x, y, wm, hm) in enumerate(cards):
        cw, ch = px(wm), px(hm)
        img[y:y + ch, x:x + cw] = WHITE
        if mark_first and i == 0:  # 非対称マーカー（左上に濃い矩形）
            img[y + 100:y + 300, x + 100:x + 500] = 60
    return img


def save(img, path, fmt):
    im = Image.fromarray(img)
    if fmt == "PDF":
        im.save(path, "PDF", resolution=DPI)
    else:
        im.save(path, fmt, dpi=(DPI, DPI))


def build_fixtures():
    FIX.mkdir(exist_ok=True)
    one = make_scan(2600, 1800, [(200, 200, 91, 55)])
    for name, fmt in [("one.png", "PNG"), ("one.jpg", "JPEG"), ("one.tif", "TIFF"),
                      ("one.pdf", "PDF"), ("ONE.PNG", "PNG")]:
        save(one, FIX / name, fmt)
    (FIX / "note.txt").write_text("not an image")
    three = make_scan(4800, 3400, [(200, 200, 91, 55), (2600, 200, 91, 55), (200, 1800, 91, 55)])
    save(three, FIX / "three.png", "PNG")
    two = make_scan(4800, 1800, [(200, 200, 91, 55), (2600, 200, 91, 55)])
    save(two, FIX / "two.png", "PNG")
    other = make_scan(2600, 1800, [(400, 300, 91, 55)])
    save(other, FIX / "other_one.png", "PNG")
    eleven = [(200 + 2400 * c, 200 + 1500 * r, 91, 55) for r in range(4) for c in range(3)][:11]
    save(make_scan(7400, 6200, eleven), FIX / "eleven.png", "PNG")
    save(make_scan(4800, 1800, [(200, 200, 91, 55), (2600, 200, 85, 51)]),
         FIX / "good_bad.png", "PNG")
    save(make_scan(2600, 1800, [(200, 200, 91, 55)], mark_first=True), FIX / "marked.png", "PNG")


build_fixtures()


def write_cfg(home, **sections):
    cfg = {"intake": {"stable_wait_s": 0.1}, "print": {"output": "pdf"}}
    for k, v in sections.items():
        cfg.setdefault(k, {}).update(v)
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.json").write_text(json.dumps(cfg))


def put_inbox(home, name, as_name=None):
    d = home / "inbox"
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIX / name, d / (as_name or name))


def cli(home, *args):
    return subprocess.run(["uv", "run", "print-edit", *args, "--home", str(home)],
                          cwd=ROOT, capture_output=True, text=True, timeout=300)


def ingest(home):
    r = cli(home, "ingest")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def db(home, sql):
    con = sqlite3.connect(home / "db.sqlite3")
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def sheets_of(home):
    return sorted(glob.glob(str(home / "jobs" / "*" / "sheets" / "*.pdf")))


def layouts_of(home):
    return [json.load(open(p)) for p in sorted(glob.glob(str(home / "jobs" / "*" / "sheets" / "*.layout.json")))]


# ---------------- 1. 印刷タイミング ----------------
def test_t1_per_scan_over_capacity_by_cards_per_sheet(tmp_path):
    write_cfg(tmp_path, layout={"cards_per_sheet": 2}, print={"timing": "per_scan"})
    put_inbox(tmp_path, "three.png")
    ingest(tmp_path)
    assert len(sheets_of(tmp_path)) == 2
    assert sorted(len(l["slots"]) for l in layouts_of(tmp_path)) == [1, 2]
    assert db(tmp_path, "select count(*) from cards where status='printed'")[0][0] == 3


def test_t1_per_scan_over_default_capacity_11_cards(tmp_path):
    write_cfg(tmp_path, print={"timing": "per_scan"})
    put_inbox(tmp_path, "eleven.png")
    ingest(tmp_path)
    assert len(sheets_of(tmp_path)) == 2
    assert sorted(len(l["slots"]) for l in layouts_of(tmp_path)) == [1, 10]


def test_t1_fill_keeps_remainder_pending_then_sheets(tmp_path):
    write_cfg(tmp_path, layout={"cards_per_sheet": 2}, print={"timing": "fill"})
    put_inbox(tmp_path, "three.png")
    ingest(tmp_path)
    assert len(sheets_of(tmp_path)) == 1
    assert db(tmp_path, "select count(*) from cards where status='pending'")[0][0] == 1
    assert db(tmp_path, "select count(*) from cards where status='printed'")[0][0] == 2
    put_inbox(tmp_path, "other_one.png")
    ingest(tmp_path)
    assert len(sheets_of(tmp_path)) == 2
    assert db(tmp_path, "select count(*) from cards where status='pending'")[0][0] == 0
    assert db(tmp_path, "select count(*) from cards where status='printed'")[0][0] == 4


def test_t1_duplicate_fills_slots_with_one_card(tmp_path):
    write_cfg(tmp_path, layout={"cards_per_sheet": 3}, print={"timing": "duplicate"})
    put_inbox(tmp_path, "one.png")
    ingest(tmp_path)
    ls = layouts_of(tmp_path)
    assert len(sheets_of(tmp_path)) == 1
    assert len(ls[0]["slots"]) == 3
    assert {os.path.basename(s["card"]) for s in ls[0]["slots"]} == {"01.png"}


def test_t1_duplicate_repeats_two_cards_in_order(tmp_path):
    write_cfg(tmp_path, layout={"cards_per_sheet": 5}, print={"timing": "duplicate"})
    put_inbox(tmp_path, "two.png")
    ingest(tmp_path)
    ls = layouts_of(tmp_path)
    assert len(sheets_of(tmp_path)) == 1
    assert [os.path.basename(s["card"]) for s in ls[0]["slots"]] == \
        ["01.png", "02.png", "01.png", "02.png", "01.png"]


# ---------------- 2. 取込形式 ----------------
@pytest.mark.parametrize("name", ["one.png", "one.jpg", "one.tif", "one.pdf", "ONE.PNG"])
def test_t2_extensions_ingested(tmp_path, name):
    write_cfg(tmp_path)
    put_inbox(tmp_path, name)
    out = ingest(tmp_path)
    assert len(out) == 1
    assert out[0]["status"] != "error"
    assert len(db(tmp_path, "select id from jobs")) == 1
    assert db(tmp_path, "select count(*) from cards")[0][0] >= 1
    assert glob.glob(str(tmp_path / "processed" / "*" )) 
    assert not (tmp_path / "inbox" / name).exists()


def test_t2_txt_not_ingested(tmp_path):
    write_cfg(tmp_path)
    put_inbox(tmp_path, "note.txt")
    r = cli(tmp_path, "ingest")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == []
    assert db(tmp_path, "select count(*) from jobs")[0][0] == 0
    assert (tmp_path / "inbox" / "note.txt").exists()


# ---------------- 3. API ----------------
def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture
def server(tmp_path):
    def start(**sections):
        write_cfg(tmp_path, **sections)
        port = free_port()
        proc = subprocess.Popen(["uv", "run", "print-edit", "serve", "--port", str(port),
                                 "--home", str(tmp_path)], cwd=ROOT,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        procs.append(proc)
        base = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                if httpx.get(base + "/api/config", timeout=2).status_code == 200:
                    return base, port
            except httpx.HTTPError:
                time.sleep(0.2)
        raise RuntimeError("server did not start")
    procs = []
    yield start
    for p in procs:
        p.terminate()
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()


def as_list(resp, key):
    j = resp.json()
    return j if isinstance(j, list) else j[key]


def api_ingest(base, home, name):
    put_inbox(home, name)
    r = httpx.post(base + "/api/ingest", timeout=300)
    assert r.status_code == 200, r.text


def test_t3_put_config_over_capacity_422(server):
    base, _ = server()
    cfg = httpx.get(base + "/api/config").json()
    cap = httpx.get(base + "/api/capacity").json()["capacity"]
    assert cap == 10
    cfg["layout"]["cards_per_sheet"] = cap + 1
    assert httpx.put(base + "/api/config", json=cfg).status_code == 422


def _raw_get(port, path):
    with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
        s.sendall(f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n".encode())
        data = b""
        while True:
            c = s.recv(65536)
            if not c:
                break
            data += c
    return int(data.split(b" ", 2)[1])


@pytest.mark.parametrize("path", ["/files/../config.json", "/files/jobs/../../config.json",
                                  "/files/..%2fconfig.json", "/files/%2e%2e/config.json"])
def test_t3_files_outside_home_404(server, tmp_path, path):
    base, port = server()
    assert (tmp_path / "config.json").exists()
    assert _raw_get(port, path) == 404


def test_t3_discard_recomputes_job_status(server, tmp_path):
    base, _ = server(print={"timing": "per_scan"})
    api_ingest(base, tmp_path, "good_bad.png")
    jobs = as_list(httpx.get(base + "/api/jobs"), "jobs")
    assert len(jobs) == 1 and jobs[0]["status"] == "review"
    jid = jobs[0]["id"]
    review = as_list(httpx.get(base + "/api/cards", params={"status": "review"}), "cards")
    assert len(review) == 1
    r = httpx.post(f"{base}/api/cards/{review[0]['id']}/discard")
    assert r.status_code == 200
    disc = as_list(httpx.get(base + "/api/cards", params={"status": "discarded"}), "cards")
    assert [c["id"] for c in disc] == [review[0]["id"]]
    assert httpx.get(f"{base}/api/jobs/{jid}").json()["status"] == "ok"


def test_t3_rotate_turns_card_180(server, tmp_path):
    base, _ = server(print={"timing": "fill"}, layout={"cards_per_sheet": 10})
    api_ingest(base, tmp_path, "marked.png")
    files = glob.glob(str(tmp_path / "jobs" / "*" / "cards" / "01.png"))
    assert len(files) == 1
    before = cv2.imread(files[0]).astype(int)
    cards = as_list(httpx.get(base + "/api/cards"), "cards")
    assert len(cards) == 1
    assert httpx.post(f"{base}/api/cards/{cards[0]['id']}/rotate").status_code == 200
    after = cv2.imread(files[0]).astype(int)
    assert after.shape == before.shape
    expect = np.rot90(before, 2)
    assert np.abs(after - expect).mean() < 2.0
    assert after[:300, :600].mean() > 250 and before[:300, :600].mean() < 200  # マーカー(濃)が左上から移動


def test_t3_reprint_ok(server, tmp_path):
    base, _ = server(print={"timing": "per_scan"})
    api_ingest(base, tmp_path, "one.png")
    jid = as_list(httpx.get(base + "/api/jobs"), "jobs")[0]["id"]
    n = len(sheets_of(tmp_path))
    assert n >= 1
    r = httpx.post(f"{base}/api/jobs/{jid}/reprint", timeout=60)
    assert r.status_code == 200, r.text
    assert len(sheets_of(tmp_path)) >= n
    assert httpx.get(f"{base}/api/jobs/{jid}").json()["status"] == "ok"
    assert all(Path(p).stat().st_size > 0 for p in sheets_of(tmp_path))


# ---------------- 4. 部分 config ----------------
def test_t4_partial_config_defaults(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"layout": {"cards_per_sheet": 4}}))
    r = cli(tmp_path, "config", "show")
    assert r.returncode == 0, r.stderr
    c = json.loads(r.stdout)
    assert c["layout"]["cards_per_sheet"] == 4
    assert c["layout"]["paper_width_mm"] == 210 and c["layout"]["paper_height_mm"] == 297
    assert c["layout"]["gap_x_mm"] == 0 and c["layout"]["mark_enabled"] is True
    assert c["print"]["timing"] == "per_scan" and c["print"]["output"] == "pdf"
    assert c["detect"]["card_width_mm"] == 91 and c["detect"]["size_tolerance_mm"] == 1.5
    assert c["intake"]["expected_dpi"] == 600
    assert c["intake"]["extensions"] == ["png", "jpg", "jpeg", "tif", "tiff", "pdf"]
    assert c["device"]["unprintable_mm"] == 4.2 and c["correct"]["whiten_level"] == 200


def test_t4_partial_within_section(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"print": {"timing": "fill"}, "layout": {"gap_x_mm": 2}}))
    c = json.loads(cli(tmp_path, "config", "show").stdout)
    assert c["print"]["timing"] == "fill" and c["print"]["copies"] == 1
    assert c["layout"]["gap_x_mm"] == 2 and c["layout"]["gap_y_mm"] == 0
    assert c["layout"]["cards_per_sheet"] is None
