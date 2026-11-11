"""受け入れ試験 A1〜A11（docs/spec.md 11 節）。CLI 越しにのみ照合する。実装は import しない。

期待値は make_fixtures.py が仕様の式・定義から作る fixtures/expected.json を使う。
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
FX = HERE / "fixtures"
MM_PER_PX = 25.4 / 600


# ---------------------------------------------------------------- 共通
@pytest.fixture(scope="session")
def expected():
    if not (FX / "expected.json").exists():
        subprocess.run([sys.executable, str(HERE / "make_fixtures.py")], check=True, cwd=REPO)
    return json.loads((FX / "expected.json").read_text())


@pytest.fixture(scope="session")
def safe_env():
    env = dict(os.environ)
    env.pop("PRINT_EDIT_HOME", None)
    return env


def build_cmd(sub, home, cfg=None, home_before=False):
    common = ["--home", str(home)] + (["--config", str(cfg)] if cfg else [])
    if home_before:
        return ["uv", "run", "print-edit", *common, *sub]
    return ["uv", "run", "print-edit", sub[0], *sub[1:], *common]


@pytest.fixture(scope="session")
def home_before(tmp_path_factory, safe_env):
    """共通オプション --home の位置が仕様から決まらないため、サブコマンドの後ろで通るかを調べる。"""
    h = tmp_path_factory.mktemp("probe")
    r = subprocess.run(build_cmd(["capacity"], h), cwd=REPO, env={**safe_env, "PRINT_EDIT_HOME": str(h)},
                       capture_output=True, text=True, timeout=300)
    err = r.stderr.lower()
    return r.returncode == 2 and ("unrecognized" in err or "no such option" in err)


@pytest.fixture(scope="session")
def cli(safe_env, home_before):
    def run(sub, home, cfg=None, timeout=300):
        env = {**safe_env, "PRINT_EDIT_HOME": str(home)}
        return subprocess.run(build_cmd(sub, home, cfg, home_before), cwd=REPO, env=env,
                              capture_output=True, text=True, timeout=timeout)
    return run


@pytest.fixture(scope="session")
def detect(cli, tmp_path_factory):
    cache = {}

    def run(name, dpi=None):
        key = (name, dpi)
        if key not in cache:
            work = tmp_path_factory.mktemp(f"det_{name}")
            out = work / "out"
            sub = ["detect", str(FX / "images" / f"{name}.png"), "--out", str(out)]
            if dpi is not None:
                sub += ["--dpi", str(dpi)]
            r = cli(sub, work / "home")
            assert r.returncode == 0, f"detect 失敗 rc={r.returncode} stderr={r.stderr[-500:]}"
            data = json.loads(r.stdout)
            cache[key] = (data, out)
        return cache[key]
    return run


def corner_errors_mm(actual, expect):
    """順不同の四隅を最も良く対応づけ、各隅の誤差(mm)を返す。"""
    assert len(actual) == 4
    best = None
    for perm in itertools.permutations(range(4)):
        errs = [math.dist(actual[i], expect[j]) * MM_PER_PX for j, i in enumerate(perm)]
        if best is None or max(errs) < max(best):
            best = errs
    return best


def names(group, expected_):
    return [n for n, v in expected_["detect"].items() if v["group"] == group]


A1_NAMES = [f"a1_deg_{t}" for t in ("0", "p3", "m3", "p5", "m5", "p15", "m15", "p30", "m30", "p44", "m44", "p45", "m45")]
A4_NAMES = [f"a4_robust_{t}" for t in ("0", "p12", "m12", "p38", "m38")]
A3_NAMES = ["a3_three_row", "a3_three_col", "a3_three_shuffled"]
A5_NAMES = ["a5_touch_h", "a5_touch_v", "a5_dark_border", "a5_wrong_size_0", "a5_wrong_size_15",
            "a5_zero_noise", "a5_zero_speck"]


# ---------------------------------------------------------------- A1
@pytest.mark.parametrize("name", A1_NAMES)
def test_A1_corners_within_0_3mm(name, detect, expected):
    data, _ = detect(name)
    assert len(data["cards"]) == 1
    errs = corner_errors_mm(data["cards"][0]["corners_px"], expected["detect"][name]["cards"][0]["corners_px"])
    assert max(errs) <= 0.3, f"四隅誤差 mm={errs}"


# ---------------------------------------------------------------- A2
@pytest.mark.parametrize("name", A1_NAMES)
def test_A2_size_and_output_px(name, detect, expected):
    from PIL import Image
    data, out = detect(name)
    assert len(data["cards"]) == 1
    c = data["cards"][0]
    assert abs(c["long_mm"] - 91.0) <= 0.3, c["long_mm"]
    assert abs(c["short_mm"] - 55.0) <= 0.3, c["short_mm"]
    assert (c["image_width_px"], c["image_height_px"]) == (2150, 1299)
    with Image.open(out / c["image"]) as im:
        assert im.size == (2150, 1299)


# ---------------------------------------------------------------- A3
@pytest.mark.parametrize("name", A3_NAMES)
def test_A3_three_cards_and_order(name, detect, expected):
    data, _ = detect(name)
    exp = expected["detect"][name]
    assert len(data["cards"]) == 3
    assert [c["index"] for c in data["cards"]] == [1, 2, 3]
    for pos, ti in enumerate(exp["expected_order"]):
        want = exp["cards"][ti]["center_mm"]
        got = data["cards"][pos]["center_mm"]
        # 順序の識別が目的。中心の精度基準は仕様に無いので 1mm を識別用の許容にする
        assert math.dist(got, want) <= 1.0, f"{pos + 1}番目の中心 {got} は期待 {want}（カード{ti}）と異なる"


# ---------------------------------------------------------------- A4
@pytest.mark.parametrize("name", A4_NAMES)
def test_A4_robust_corners_within_0_5mm(name, detect, expected):
    data, _ = detect(name)
    assert len(data["cards"]) == 1
    errs = corner_errors_mm(data["cards"][0]["corners_px"], expected["detect"][name]["cards"][0]["corners_px"])
    assert max(errs) <= 0.5, f"四隅誤差 mm={errs}"


# ---------------------------------------------------------------- A5
@pytest.mark.parametrize("name", A5_NAMES)
def test_A5_abnormal_is_not_ok(name, detect, expected):
    data, _ = detect(name)
    assert data["status"] != "ok"
    assert data["status"] == "review"
    assert all(c["status"] != "ok" for c in data["cards"]), [c["status"] for c in data["cards"]]
    exp = expected["detect"][name]
    if name.startswith("a5_zero"):
        assert data["cards"] == []


@pytest.mark.parametrize("name", ["a5_wrong_size_0", "a5_wrong_size_15"])
def test_A5_wrong_size_reason(name, detect):
    data, _ = detect(name)
    assert len(data["cards"]) == 1
    c = data["cards"][0]
    assert c["status"] == "review" and "size_out_of_tolerance" in c["reasons"]


# ---------------------------------------------------------------- A6
def test_A6_metadata_600(detect):
    data, _ = detect("a6_meta600")
    assert data["source"]["dpi"] == 600
    assert data["source"]["dpi_source"] == "metadata"
    assert "dpi_mismatch" not in data["warnings"]
    assert data["status"] == "ok"


def test_A6_no_metadata_uses_config(detect):
    data, _ = detect("a6_nometa")
    assert data["source"]["dpi"] == 600
    assert data["source"]["dpi_source"] == "config"
    assert "dpi_mismatch" not in data["warnings"]
    assert data["status"] == "ok"


def test_A6_metadata_300_mismatch(detect):
    data, _ = detect("a6_meta300")
    assert data["source"]["dpi"] == 300  # あるときは画像の値を使う
    assert data["source"]["dpi_source"] == "metadata"
    assert "dpi_mismatch" in data["warnings"]
    assert len(data["cards"]) >= 1 and all(c["status"] == "review" for c in data["cards"])


def test_A6_dpi_option(detect):
    data, _ = detect("a6_nometa", dpi=600)
    assert data["source"]["dpi"] == 600
    assert data["source"]["dpi_source"] == "option"
    data300, _ = detect("a6_nometa", dpi=300)
    assert data300["source"]["dpi"] == 300
    assert data300["source"]["dpi_source"] == "option"


# ---------------------------------------------------------------- A7
IMPOSE_CASES = ["default", "gap_10_5", "paper_a5", "paper_letter", "card_100x60", "tie_square200", "unprintable_15"]


@pytest.mark.parametrize("case", IMPOSE_CASES)
def test_A7_capacity(case, cli, expected, tmp_path):
    exp = expected["impose"][case]
    cfg = FX / exp["config"]
    r = cli(["capacity"], tmp_path / "home", cfg=None if case == "default" else cfg)
    assert r.returncode == 0, r.stderr[-500:]
    got = json.loads(r.stdout)
    assert got == {k: exp[k] for k in ("capacity", "columns", "rows", "card_rotated")}


def test_A7_default_is_10_2x5(cli, tmp_path):
    r = cli(["capacity"], tmp_path / "home")
    assert r.returncode == 0, r.stderr[-500:]
    got = json.loads(r.stdout)
    assert (got["capacity"], got["columns"], got["rows"], got["card_rotated"]) == (10, 2, 5, False)


# ---------------------------------------------------------------- A8
IMPOSE_PARAMS = [(c, n) for c in IMPOSE_CASES for n in {
    "default": [1, 3, 10, 11, 25], "gap_10_5": [9, 11], "paper_a5": [5], "paper_letter": [9],
    "card_100x60": [9], "tie_square200": [7], "unprintable_15": [7]}[c]]


@pytest.fixture(scope="session")
def imposed(cli, expected, tmp_path_factory):
    cache = {}

    def run(case, n):
        if (case, n) not in cache:
            work = tmp_path_factory.mktemp(f"imp_{case}_{n}")
            out = work / "sheet.pdf"
            cards = [str(FX / "cards" / f"card_{i:02d}.png") for i in range(1, n + 1)]
            cfg = None if case == "default" else FX / expected["impose"][case]["config"]
            r = cli(["impose", *cards, "--out", str(out)], work / "home", cfg=cfg)
            assert r.returncode == 0, f"impose 失敗: {r.stderr[-500:]}"
            layout = json.loads(Path(str(out) + ".layout.json").read_text())
            pdfs = [out] + sorted(work.glob("sheet-*.pdf"), key=lambda p: int(p.stem.split("-")[-1]))
            cache[(case, n)] = (layout, pdfs)
        return cache[(case, n)]
    return run


def rects_overlap(a, b, eps=1e-6):
    return (a["x"] < b["x"] + b["w"] - eps and b["x"] < a["x"] + a["w"] - eps
            and a["y"] < b["y"] + b["h"] - eps and b["y"] < a["y"] + a["h"] - eps)


@pytest.mark.parametrize("case,n", IMPOSE_PARAMS)
def test_A8_slots_no_overlap_inside_printable(case, n, imposed, expected):
    layout, _ = imposed(case, n)
    exp = expected["impose"][case]
    px, py, pw, ph = layout["printable_mm"]
    assert [px, py, pw, ph] == pytest.approx(exp["printable_mm"], abs=0.01)
    slots = layout["slots"]
    assert 1 <= len(slots) <= exp["capacity"]
    for s in slots:
        assert s["x"] >= px - 0.01 and s["y"] >= py - 0.01
        assert s["x"] + s["w"] <= px + pw + 0.01 and s["y"] + s["h"] <= py + ph + 0.01
    for a, b in itertools.combinations(slots, 2):
        assert not rects_overlap(a, b), (a, b)


@pytest.mark.parametrize("case,n", IMPOSE_PARAMS)
def test_A8_slot_size_within_0_01mm(case, n, imposed, expected):
    layout, _ = imposed(case, n)
    exp = expected["impose"][case]
    assert layout["card_rotated"] == exp["card_rotated"]
    for s in layout["slots"]:
        want = exp["slots"][s["index"] - 1]
        assert abs(s["w"] - want["w"]) <= 0.01 and abs(s["h"] - want["h"]) <= 0.01, (s, want)


@pytest.mark.parametrize("case,n", IMPOSE_PARAMS)
def test_A8_slot_position_grid_centered(case, n, imposed, expected):
    layout, _ = imposed(case, n)
    exp = expected["impose"][case]
    for s in layout["slots"]:
        want = exp["slots"][s["index"] - 1]
        assert abs(s["x"] - want["x"]) <= 0.01 and abs(s["y"] - want["y"]) <= 0.01, (s, want)


@pytest.mark.parametrize("case,n", IMPOSE_PARAMS)
def test_A8_pdf_page_size_and_sheet_count(case, n, imposed, expected):
    import pypdfium2 as pdfium
    layout, pdfs = imposed(case, n)
    exp = expected["impose"][case]
    assert len(pdfs) == math.ceil(n / exp["capacity"])
    for p in pdfs:
        assert p.exists(), p
        doc = pdfium.PdfDocument(str(p))
        w_pt, h_pt = doc[0].get_size()
        doc.close()
        assert abs(w_pt * 25.4 / 72 - exp["paper_mm"][0]) <= 0.1
        assert abs(h_pt * 25.4 / 72 - exp["paper_mm"][1]) <= 0.1


# ---------------------------------------------------------------- A9
def _write_home(home, stable=0.2):
    (home / "inbox").mkdir(parents=True, exist_ok=True)
    (home / "config.json").write_text(json.dumps({"intake": {"stable_wait_s": stable}}))


def _jobs_count(home):
    con = sqlite3.connect(home / "db.sqlite3")
    try:
        return con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    finally:
        con.close()


def test_A9_same_file_twice_is_one_job(cli, tmp_path):
    home = tmp_path / "home"
    _write_home(home)
    src = FX / "images" / "a1_deg_p5.png"
    shutil.copy(src, home / "inbox" / "scan1.png")
    r1 = cli(["ingest"], home)
    assert r1.returncode == 0, r1.stderr[-500:]
    shutil.copy(src, home / "inbox" / "scan2.png")
    r2 = cli(["ingest"], home)
    assert r2.returncode == 0, r2.stderr[-500:]
    assert _jobs_count(home) == 1
    assert len([p for p in (home / "jobs").iterdir() if p.is_dir()]) == 1
    assert list((home / "inbox").iterdir()) == []
    assert len(list((home / "processed").iterdir())) == 2  # 重複も processed/ へ移す


def test_A9_original_kept_in_processed(cli, tmp_path):
    home = tmp_path / "home"
    _write_home(home)
    src = FX / "images" / "a1_deg_p5.png"
    shutil.copy(src, home / "inbox" / "scan1.png")
    r = cli(["ingest"], home)
    assert r.returncode == 0, r.stderr[-500:]
    result = json.loads(r.stdout)
    assert len(result) == 1
    job_id = result[0]["job_id"]
    moved = home / "processed" / f"{job_id}_scan1.png"
    assert moved.exists(), list((home / "processed").iterdir())
    assert hashlib.sha256(moved.read_bytes()).hexdigest() == hashlib.sha256(src.read_bytes()).hexdigest()
    assert not (home / "inbox" / "scan1.png").exists()


def test_A9_two_processes_concurrently(tmp_path, safe_env, home_before):
    home = tmp_path / "home"
    _write_home(home)
    files = ["a1_deg_p5", "a1_deg_m5", "a1_deg_p15"]
    for f in files:
        shutil.copy(FX / "images" / f"{f}.png", home / "inbox" / f"{f}.png")
    shutil.copy(FX / "images" / "a1_deg_p5.png", home / "inbox" / "dup_of_p5.png")
    env = {**safe_env, "PRINT_EDIT_HOME": str(home)}
    procs = [subprocess.Popen(build_cmd(["ingest"], home, None, home_before), cwd=REPO, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
    results = [p.communicate(timeout=600) + (p.returncode,) for p in procs]
    for out, err, rc in results:
        assert rc == 0, err[-500:]
    assert _jobs_count(home) == 3
    con = sqlite3.connect(home / "db.sqlite3")
    try:
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        con.close()
    assert list((home / "inbox").iterdir()) == []
    assert len(list((home / "processed").iterdir())) == 4
    assert len([p for p in (home / "jobs").iterdir() if p.is_dir()]) == 3


# ---------------------------------------------------------------- A10
def _printers_exist():
    if shutil.which("lpstat") is None:
        return False
    r = subprocess.run(["lpstat", "-p"], capture_output=True, text=True)
    return r.returncode == 0 and bool(r.stdout.strip())


def test_A10_lp_empty_printer_name_is_error(tmp_path, safe_env, home_before):
    if _printers_exist():
        pytest.skip("実在のプリンタが登録されているため、誤印刷を避けて実行しない")
    home = tmp_path / "home"
    _write_home(home)
    shutil.copy(FX / "images" / "a1_deg_p5.png", home / "inbox" / "scan1.png")
    cfg = tmp_path / "lp_empty.json"
    cfg.write_text(json.dumps({"intake": {"stable_wait_s": 0.2}, "print": {"output": "lp", "printer_name": ""}}))
    # PATH 上の lp を偽物に差し替える（呼ばれたら記録して成功終了）。実機の lp は PATH の先頭に来ない
    fake = tmp_path / "fakebin"
    fake.mkdir()
    marker = tmp_path / "lp_called.txt"
    (fake / "lp").write_text(f'#!/bin/sh\necho "$@" >> "{marker}"\nexit 0\n')
    (fake / "lp").chmod(0o755)
    env = {**safe_env, "PRINT_EDIT_HOME": str(home), "PATH": f"{fake}{os.pathsep}{safe_env.get('PATH', '')}"}
    r = subprocess.run(build_cmd(["ingest"], home, cfg, home_before), cwd=REPO, env=env,
                       capture_output=True, text=True, timeout=300)
    assert not marker.exists(), f"lp が実行された: {marker.read_text()}"
    errored = r.returncode != 0
    if not errored:
        try:
            errored = any(j.get("status") == "error" for j in json.loads(r.stdout))
        except (json.JSONDecodeError, AttributeError):
            errored = False
    assert errored, f"エラーにならなかった rc={r.returncode} stdout={r.stdout[-300:]}"


# ---------------------------------------------------------------- A11
def test_A11_a4_full_detect_within_5s(cli, tmp_path):
    out = tmp_path / "out"
    t0 = time.perf_counter()
    r = cli(["detect", str(FX / "images" / "a11_a4_full.png"), "--out", str(out)], tmp_path / "home")
    elapsed = time.perf_counter() - t0
    assert r.returncode == 0, r.stderr[-500:]
    assert json.loads(r.stdout)["source"]["width_px"] == 4960
    assert elapsed <= 5.0, f"{elapsed:.2f}s（uv run 起動を含む）"
