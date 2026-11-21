import fcntl
import json
import os
import shutil
import subprocess
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from synth import make_scan, save_png, save_png_nodpi

from print_edit.adapters.base import PrinterError
from print_edit.adapters.printers.lp import LpPrinter
from print_edit.adapters.sources.folder import FolderSource
from print_edit.cli import main
from print_edit.core.settings import Preset, Settings
from print_edit.home import Home
from print_edit.pipeline import Pipeline


def run(capsys, *argv):
    code = main(list(argv))
    cap = capsys.readouterr()
    return code, cap.out, cap.err


def scan(path, n=1, dpi=600):
    spec = [(52, 60, 91, 55, 4), (152, 62, 91, 55, -6), (105, 160, 91, 55, 20), (60, 230, 91, 55, 0)][:n]
    save_png(make_scan(spec), path, dpi)


def write_cfg(home, **over):
    cfg = Settings.model_validate(over).model_dump(mode="json")
    cfg["intake"]["stable_wait_s"] = 0
    Path(home).mkdir(parents=True, exist_ok=True)
    (Path(home) / "config.json").write_text(json.dumps(cfg))


def test_detect_cli(tmp_path, capsys):
    scan(tmp_path / "in.png", 2)
    code, out, _ = run(capsys, "detect", str(tmp_path / "in.png"), "--out", str(tmp_path / "o"), "--home", str(tmp_path / "h"))
    assert code == 0
    doc = json.loads(out)
    assert doc == json.loads((tmp_path / "o" / "detect.json").read_text())
    assert doc["source"]["dpi_source"] == "metadata" and doc["status"] == "ok" and len(doc["cards"]) == 2
    assert (tmp_path / "o" / "cards" / "02.png").exists()
    assert not (tmp_path / "h").exists()  # detect は home を作らない


def test_detect_dpi_cases(tmp_path, capsys):
    save_png_nodpi(__import__("synth").make_scan([(105, 148, 91, 55, 0)]), tmp_path / "n.png")
    _, out, _ = run(capsys, "detect", str(tmp_path / "n.png"), "--out", str(tmp_path / "a"), "--home", str(tmp_path))
    assert json.loads(out)["source"]["dpi_source"] == "config"
    _, out, _ = run(capsys, "detect", str(tmp_path / "n.png"), "--out", str(tmp_path / "b"), "--dpi", "600", "--home", str(tmp_path))
    assert json.loads(out)["source"]["dpi_source"] == "option"
    scan(tmp_path / "m.png", 1, dpi=300)
    _, out, _ = run(capsys, "detect", str(tmp_path / "m.png"), "--out", str(tmp_path / "c"), "--home", str(tmp_path))
    d = json.loads(out)
    assert d["warnings"] == ["dpi_mismatch"] and d["status"] == "review" and d["cards"][0]["status"] == "review"


def test_detect_missing_file_fails(tmp_path, capsys):
    code, _, err = run(capsys, "detect", str(tmp_path / "none.png"), "--out", str(tmp_path / "o"))
    assert code != 0 and err


def test_capacity_and_impose(tmp_path, capsys):
    code, out, _ = run(capsys, "capacity", "--home", str(tmp_path))
    assert json.loads(out) == {"capacity": 10, "columns": 2, "rows": 5, "card_rotated": False}
    scan(tmp_path / "in.png", 3)
    run(capsys, "detect", str(tmp_path / "in.png"), "--out", str(tmp_path / "d"), "--home", str(tmp_path))
    cards = [str(tmp_path / "d" / "cards" / f"0{i}.png") for i in (1, 2, 3)] * 4  # 12 枚 → 2 シート
    code, _, _ = run(capsys, "impose", *cards, "--out", str(tmp_path / "s.pdf"), "--home", str(tmp_path))
    assert code == 0
    assert (tmp_path / "s.pdf").exists() and (tmp_path / "s-2.pdf").exists()
    lay = json.loads((tmp_path / "s.pdf.layout.json").read_text())
    assert lay["capacity"] == 10 and len(lay["slots"]) == 10 and lay["slots"][0]["card"] == "01.png"
    assert len(json.loads((tmp_path / "s-2.pdf.layout.json").read_text())["slots"]) == 2
    w, h = pdfium.PdfDocument(str(tmp_path / "s.pdf"))[0].get_size()
    assert abs(w * 25.4 / 72 - 210) < 0.1


def test_config_commands(tmp_path, capsys):
    _, out, _ = run(capsys, "config", "path", "--home", str(tmp_path))
    assert out.strip() == str(tmp_path.resolve() / "config.json")
    _, out, _ = run(capsys, "config", "show", "--home", str(tmp_path))
    assert json.loads(out)["intake"]["expected_dpi"] == 600
    _, out, _ = run(capsys, "--home", str(tmp_path), "config", "schema")
    assert "properties" in json.loads(out)


def test_home_and_config_position(tmp_path, capsys, monkeypatch):
    a, b, env = tmp_path / "a", tmp_path / "b", tmp_path / "env"
    monkeypatch.setenv("PRINT_EDIT_HOME", str(env))
    # サブコマンドの前に置いても効く（以前は黙って PRINT_EDIT_HOME / ~/PrintEdit に落ちていた）
    _, out, _ = run(capsys, "--home", str(a), "config", "path")
    assert out.strip() == str(a.resolve() / "config.json")
    _, out, _ = run(capsys, "config", "path", "--home", str(a))
    assert out.strip() == str(a.resolve() / "config.json")
    # 前後両方なら後ろが勝つ
    _, out, _ = run(capsys, "--home", str(a), "config", "path", "--home", str(b))
    assert out.strip() == str(b.resolve() / "config.json")
    # 指定なしは PRINT_EDIT_HOME
    _, out, _ = run(capsys, "config", "path")
    assert out.strip() == str(env.resolve() / "config.json")
    # --config の前置き
    cfg = tmp_path / "c.json"
    _, out, _ = run(capsys, "--config", str(cfg), "config", "path")
    assert out.strip() == str(cfg)
    _, out, _ = run(capsys, "config", "path", "--config", str(cfg))
    assert out.strip() == str(cfg)
    cfg2 = tmp_path / "c2.json"
    _, out, _ = run(capsys, "--config", str(cfg), "config", "path", "--config", str(cfg2))
    assert out.strip() == str(cfg2)
    # ingest でも前置きの home に inbox ができ、PRINT_EDIT_HOME 側は作られない
    code, _, _ = run(capsys, "--home", str(a), "ingest")
    assert code == 0 and (a / "inbox").is_dir() and not env.exists()


def test_ingest_end_to_end(tmp_path, capsys):
    home = tmp_path / "h"
    write_cfg(home)
    (home / "inbox").mkdir()
    scan(home / "inbox" / "a.PNG", 3)
    (home / "inbox" / "note.txt").write_text("x")
    code, out, _ = run(capsys, "ingest", "--home", str(home))
    assert code == 0
    res = json.loads(out)
    assert len(res) == 1 and res[0]["status"] == "ok" and res[0]["cards"] == 3 and res[0]["sheets"] == 1
    jid = res[0]["job_id"]
    jd = home / "jobs" / jid
    assert (jd / "source.png").exists() and (jd / "cards" / "03.png").exists() and (jd / "sheets" / "01.pdf").exists()
    assert (jd / "sheets" / "01.layout.json").exists() and (jd / "detect.json").exists()
    assert (home / "processed" / f"{jid}_a.PNG").exists() and not (home / "inbox" / "a.PNG").exists()
    assert (home / "inbox" / "note.txt").exists()


def test_ingest_duplicate_and_lock(tmp_path, capsys):
    home = tmp_path / "h"
    write_cfg(home)
    (home / "inbox").mkdir()
    scan(home / "inbox" / "a.png", 1)
    shutil.copy(home / "inbox" / "a.png", tmp_path / "keep.png")
    run(capsys, "ingest", "--home", str(home))
    shutil.copy(tmp_path / "keep.png", home / "inbox" / "again.png")
    _, out, _ = run(capsys, "ingest", "--home", str(home))
    assert json.loads(out) == []
    assert len(list((home / "jobs").iterdir())) == 1
    assert len(list((home / "processed").iterdir())) == 2
    # ロック中は何もしない（終了コード 0）
    shutil.copy(tmp_path / "keep.png", home / "inbox" / "third.png")
    with open(home / "ingest.lock", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        code, out, _ = run(capsys, "ingest", "--home", str(home))
    assert code == 0 and json.loads(out) == [] and (home / "inbox" / "third.png").exists()


def test_ingest_failure_isolated(tmp_path, capsys):
    home = tmp_path / "h"
    write_cfg(home)
    (home / "inbox").mkdir()
    (home / "inbox" / "bad.png").write_bytes(b"not an image")
    scan(home / "inbox" / "good.png", 1)
    code, out, _ = run(capsys, "ingest", "--home", str(home))
    res = json.loads(out)
    assert code != 0 and sorted(r["status"] for r in res) == ["error", "ok"]


def test_stable_wait_skips_growing_file(tmp_path, capsys):
    inbox = tmp_path / "in"
    inbox.mkdir()
    f = inbox / "x.png"
    f.write_bytes(b"abc")
    waited = []

    def grow(t):
        waited.append(t)
        f.write_bytes(b"a" * (3 + len(waited)))

    assert FolderSource(inbox, ["png"], 1.0, sleep=grow, max_wait_s=5).poll() == []
    assert len(waited) == 5 and "x.png" in capsys.readouterr().err
    assert FolderSource(inbox, ["PNG"], 1.0, sleep=lambda _: None).poll() == [f]


def test_stable_wait_waits_until_writing_finishes_in_same_run(tmp_path, capsys):
    inbox = tmp_path / "in"
    inbox.mkdir()
    f = inbox / "x.png"
    f.write_bytes(b"abc")
    calls = []

    def grow(_):
        calls.append(1)
        if len(calls) <= 2:
            f.write_bytes(b"a" * (10 + len(calls)))

    assert FolderSource(inbox, ["png"], 1.0, sleep=grow, max_wait_s=30).poll() == [f]
    assert len(calls) == 3 and capsys.readouterr().err == ""


def test_ingest_timeout_exits_zero_without_error_job(tmp_path, capsys):
    write_cfg(tmp_path / "h")
    cfgp = tmp_path / "h" / "config.json"
    cfg = json.loads(cfgp.read_text())
    cfg["intake"].update(stable_wait_s=0.01, max_wait_s=0.01)
    cfgp.write_text(json.dumps(cfg))
    home = Home(tmp_path / "h")
    s = home.load_settings()
    home.ensure(s)
    f = home.inbox(s) / "a.png"
    scan(f, 1)
    import print_edit.adapters.sources.folder as fm

    real = fm.FolderSource._candidates

    def growing(self):
        out = real(self)
        with open(f, "ab") as fh:
            fh.write(b"\0")
        return out

    fm.FolderSource._candidates = growing
    try:
        code, out, err = run(capsys, "ingest", "--home", str(tmp_path / "h"))
    finally:
        fm.FolderSource._candidates = real
    assert code == 0 and json.loads(out) == [] and "a.png" in err
    assert f.exists() and Pipeline(home, s).store.list_jobs() == []


def test_multiple_jobs_share_pdf_and_overflow(tmp_path):
    home = Home(tmp_path / "h")
    s = Settings.model_validate({"intake": {"stable_wait_s": 0}})
    home.ensure(s)
    for i in range(2):
        path = home.inbox(s) / f"{i}.png"
        scan(path, 3)
        with path.open("ab") as f:
            f.write(bytes([i]))
    p = Pipeline(home, s)
    result = p.ingest(Preset.model_validate({"layout": {"cards_per_sheet": 4}}))
    sheets = [p.store.get_sheet(sid) for sid in result["sheets"]]
    assert [len(p.store.sheet_slots(sheet["id"])) for sheet in sheets] == [4, 2]
    assert sheets[0]["job_id"] is None and sheets[1]["job_id"] == result["results"][1]["job_id"]
    assert len(p.store.list_cards(reg="pending")) == 6


def test_fill_preset_distributes_copies_by_card(tmp_path):
    home = Home(tmp_path / "h")
    s = Settings.model_validate({"intake": {"stable_wait_s": 0}})
    home.ensure(s)
    scan(home.inbox(s) / "a.png", 2)
    p = Pipeline(home, s)
    result = p.ingest(Preset.model_validate({"layout": {"cards_per_sheet": 6}, "arrange": {"per_card": None}}))
    assert len(result["sheets"]) == 1
    sheet = p.store.get_sheet(result["sheets"][0])
    assert list(p.store.sheet_slots(sheet["id"]).values()) == [1, 1, 1, 2, 2, 2]
    assert len(json.loads((home.root / sheet["pdf_path"]).with_suffix(".layout.json").read_text())["slots"]) == 6


def test_review_card_excluded_from_automatic_pdf(tmp_path):
    home = Home(tmp_path / "h")
    s = Settings.model_validate({"intake": {"stable_wait_s": 0}})
    home.ensure(s)
    save_png(make_scan([(52, 60, 91, 55, 4), (152, 62, 89, 51, 0)]), home.inbox(s) / "a.png")
    p = Pipeline(home, s)
    result = p.ingest(Preset())
    job = p.store.get_job(result["results"][0]["job_id"])
    assert job["status"] == "review" and len(job["cards"]) == 2
    assert len(job["sheets"]) == 1
    ok, review = sorted(job["cards"], key=lambda c: c["status"])
    assert [c["card_id"] for c in job["sheets"][0]["cards"]] == [ok["id"]]
    p.rotate(review["id"])
    assert p.store.get_card(review["id"])["reg"] == "pending"


def test_lp_command_only(tmp_path):
    s = Settings.model_validate({"print": {"output": "lp", "printer_name": "Q1", "copies": 2, "lp_options": ["media=A4", "sides=one-sided"]}})
    called = []
    lp = LpPrinter(s, runner=lambda *a, **k: called.append(a))
    assert lp.build_command(Path("/x/a.pdf")) == ["lp", "-d", "Q1", "-n", "2", "-o", "media=A4", "-o", "sides=one-sided", "/x/a.pdf"]
    empty = LpPrinter(Settings.model_validate({"print": {"output": "lp"}}), runner=lambda *a, **k: called.append(a))
    with pytest.raises(PrinterError):
        empty.send(Path("/x/a.pdf"))
    assert called == []


def test_pipeline_lp_empty_name_records_sheet_error(tmp_path):
    home = Home(tmp_path / "h")
    s = Settings.model_validate({"print": {"output": "lp"}, "intake": {"stable_wait_s": 0}})
    home.ensure(s)
    scan(home.inbox(s) / "a.png", 1)
    p = Pipeline(home, s)
    r = p.ingest(Preset())["results"][0]
    assert r["status"] == "error" and r["error"]
    assert p.store.get_job(r["job_id"])["sheets"][0]["status"] == "error"


class FlakyPrinter:
    def __init__(self, fail=True):
        self.fail = fail
        self.sent = []

    def send(self, pdf):
        self.sent.append(pdf)
        if self.fail:
            raise PrinterError("lp 失敗 (code 1): offline")


def test_cli_reports_print_failure_and_keeps_detected_cards(tmp_path, capsys):
    write_cfg(tmp_path / "h", print={"output": "lp", "printer_name": ""})
    home = Home(tmp_path / "h")
    s = home.load_settings()
    home.ensure(s)
    scan(home.inbox(s) / "a.png", 2)
    code, out, _ = run(capsys, "ingest", "--home", str(tmp_path / "h"))
    res = json.loads(out)
    assert code != 0 and res[0]["status"] == "error" and "printer_name" in res[0]["error"]
    p = Pipeline(home, s)
    job = p.store.get_job(res[0]["job_id"])
    assert job["status"] == "ok" and job["error"] is None
    assert [c["status"] for c in job["cards"]] == ["ok", "ok"]
    assert all((home.root / c["image_path"]).exists() for c in job["cards"])
    assert all((home.root / sh["pdf_path"]).exists() for sh in job["sheets"])


def test_reprint_success_updates_only_the_failed_sheet(tmp_path):
    home = Home(tmp_path / "h")
    s = Settings.model_validate({"print": {"output": "lp", "printer_name": "Q"}, "intake": {"stable_wait_s": 0}})
    home.ensure(s)
    scan(home.inbox(s) / "a.png", 1)
    bad = FlakyPrinter(True)
    p = Pipeline(home, s, printer_factory=lambda _s: bad)
    r = p.ingest(Preset())["results"][0]
    assert r["status"] == "error"
    p.printer_factory = lambda _s: FlakyPrinter(False)
    sheet_id = p.store.get_job(r["job_id"])["sheets"][0]["id"]
    assert p.reprint_sheet(sheet_id)["sent"] is True
    job = p.store.get_job(r["job_id"])
    assert job["status"] == "ok" and job["error"] is None
    assert [c["status"] for c in job["cards"]] == ["ok"]
    assert job["sheets"][0]["status"] == "sent"


def test_mixed_job_pdf_delivery_failure_keeps_cards_pending(tmp_path):
    home = Home(tmp_path / "h")
    s = Settings.model_validate({"print": {"output": "lp", "printer_name": "Q"}, "intake": {"stable_wait_s": 0}})
    home.ensure(s)
    scan(home.inbox(s) / "a.png", 2)
    scan(home.inbox(s) / "b.png", 3)
    p = Pipeline(home, s, printer_factory=lambda _: FlakyPrinter())
    result = p.ingest(Preset())
    assert len(result["sheets"]) == 1
    sheet = p.store.get_sheet(result["sheets"][0])
    assert sheet["job_id"] is None and sheet["status"] == "error"
    assert len(p.store.sheet_slots(sheet["id"])) == 5
    p.printer_factory = lambda _: FlakyPrinter(False)
    assert p.reprint_sheet(sheet["id"])["sent"]
    assert len(p.store.list_cards(reg="pending")) == 5
    assert {j["status"] for j in p.store.list_jobs()} == {"ok"}
