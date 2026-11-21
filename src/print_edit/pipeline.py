"""取込 → 検出 → 保存 → 面付け → 出力 の進行（仕様 5.3・6・7・8）。"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import secrets
import shutil
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Callable

from PIL import Image

from .adapters.base import Printer, PrinterError
from .adapters.imageload import load_image
from .adapters.printers import make_printer
from .adapters.sources.folder import FolderSource
from .core.detect import detect_cards, resolve_dpi
from .core.layout import compute_layout
from .core.pdf import render_pdf
from .arrange import auto_slots, fill_count
from .core.settings import Preset, Settings, capacity_of
from .home import Home
from .store.db import Store


def sheet_capacity(s: Settings) -> int:
    return s.layout.cards_per_sheet or capacity_of(s).capacity


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def new_job_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)


def detect_to_dir(image: Path, out: Path, s: Settings, dpi_option: int | None = None) -> dict:
    """detect コマンドの本体。cards/NN.png と detect.json を out に書き、辞書を返す。"""
    loaded = load_image(image, dpi_option or s.intake.expected_dpi)
    dpi, source, mismatch = resolve_dpi(loaded.meta_dpi, dpi_option, s.intake.expected_dpi)
    res = detect_cards(loaded.rgb, dpi, s, mismatch)
    h, w = loaded.rgb.shape[:2]
    out = Path(out)
    (out / "cards").mkdir(parents=True, exist_ok=True)
    for c in res.cards:
        Image.fromarray(c.image).save(out / c.image_name, dpi=(dpi, dpi))
    doc = {
        "source": {"path": str(Path(image).resolve()), "width_px": w, "height_px": h, "dpi": dpi, "dpi_source": source},
        "status": res.status,
        "warnings": res.warnings + loaded.warnings,
        "reasons": res.reasons,
        "cards": [c.to_dict() for c in res.cards],
    }
    (out / "detect.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return doc


def impose_files(card_files: list[Path], out_pdf: Path, s: Settings) -> list[Path]:
    """impose コマンドの本体。容量ごとに分割して PDF と .layout.json を書く。"""
    n = sheet_capacity(s)
    out_pdf = Path(out_pdf)
    written = []
    for k in range(0, len(card_files), n):
        chunk = card_files[k : k + n]
        pdf = out_pdf if k == 0 else out_pdf.with_name(f"{out_pdf.stem}-{k // n + 1}{out_pdf.suffix}")
        write_sheet(pdf, [Path(c) for c in chunk], s)
        written.append(pdf)
    return written


def write_sheet(pdf: Path, files: list[Path], s: Settings, layout_path: Path | None = None) -> dict:
    """files を 1 番のスロットから順に詰めて PDF を書く。"""
    return write_sheet_slots(pdf, {i + 1: f for i, f in enumerate(files)}, s, layout_path)


def write_sheet_slots(pdf: Path, slot_files: dict[int, Path], s: Settings, layout_path: Path | None = None) -> dict:
    """スロット番号→画像で PDF を書く（空きスロットは何も描かない）。描画は core の compute_layout・render_pdf をそのまま使い、
    最大のスロット番号までを並べた配置から、名刺のあるスロットだけを残す（空きが無ければ従来と同じ出力）。"""
    n = max(slot_files)
    layout = compute_layout(s, [slot_files[i].name if i in slot_files else "" for i in range(1, n + 1)])
    layout = replace(layout, slots=[sl for sl in layout.slots if sl["index"] in slot_files])
    images = []
    for sl in layout.slots:
        with Image.open(slot_files[sl["index"]]) as im:
            im.load()
            images.append(im.copy())
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(render_pdf(layout, images, s))
    lj = layout_path or pdf.with_name(pdf.name + ".layout.json")
    lj.write_text(json.dumps(layout.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return layout.to_dict()


class Pipeline:
    def __init__(self, home: Home, settings: Settings, printer_factory: Callable[[Settings], Printer] = make_printer, sleep=None):
        self.home = home
        self.s = settings  # 全体設定＋既定値「既定」を合わせたもの。既定値を指定する処理は preset_settings で差し替える
        self.store = Store(home.db)
        self.printer_factory = printer_factory
        self._sleep = sleep
        self._run_ok_ids: list[int] = []

    def preset_settings(self, preset: Preset) -> Settings:
        return Settings(intake=self.s.intake, detect=self.s.detect, correct=preset.correct, layout=preset.layout, print=self.s.print, device=self.s.device)

    # ---- ingest ----
    def ingest_once(self) -> list[dict]:
        """全体設定の「自動取り込みの方式」に従う（CLI の ingest・フォルダ監視）。"""
        g = self.home.load_global()
        if g.auto_ingest.mode == "ingest_create":
            r = self.ingest(self.home.get_preset(g.auto_ingest.preset_id))
        else:
            r = self.ingest(None)
        return [] if r is None else r["results"]

    def try_ingest(self) -> list[dict] | None:
        """取り込みのみ（登録待ちへ入れるまで。PDF は作らない）。ロックが取れず取り込めなかったとき None を返す。"""
        r = self.ingest(None)
        return None if r is None else r["results"]

    def ingest(self, preset: Preset | None) -> dict | None:
        """取り込み。preset があれば、その回に取り込んだ名刺（review を除く）でその既定値の PDF も作る。
        返り値: {"results": [...], "sheets": [作ったシート id], "cards": 登録待ちへ入った名刺の数}。ロックが取れなければ None。"""
        self.home.ensure(self.s)
        with open(self.home.lock, "w") as lf:
            try:
                fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return None
            kw = {"sleep": self._sleep} if self._sleep else {}
            src = FolderSource(self.home.inbox(self.s), self.s.intake.extensions, self.s.intake.stable_wait_s, max_wait_s=self.s.intake.max_wait_s, **kw)
            results = []
            self._run_ok_ids = []
            for path in src.poll():
                try:
                    r = self.process_file(path)
                except Exception as e:  # 1ファイルの失敗で止めない
                    r = {"job_id": None, "status": "error", "cards": 0, "sheets": 0, "error": str(e), "source": path.name}
                if r is not None:
                    results.append(r)
            sheets = self._create_from_ingest(self._run_ok_ids, preset, results) if preset else []
            return {"results": results, "sheets": sheets, "cards": sum(r["cards"] for r in results)}

    def _archive(self, path: Path, job_id: str) -> None:
        dest = self.home.processed / f"{job_id}_{path.name}"
        i = 1
        while dest.exists():
            dest = self.home.processed / f"{job_id}_{i}_{path.name}"
            i += 1
        shutil.move(str(path), str(dest))

    def process_file(self, path: Path) -> dict | None:
        """1 ファイルの切り出しと登録待ちへの追加まで（PDF は作らない）。ok のカード id は self._run_ok_ids に積む。"""
        sha = sha256_of(path)
        dup = self.store.find_done_job(sha)
        if dup:
            self._archive(path, dup["id"])
            return None
        job_id = new_job_id()
        job_dir = self.home.jobs / job_id
        try:
            job_dir.mkdir(parents=True)
            doc = self._detect_into_job(path, job_dir)
            warnings = doc["warnings"]
            self.store.add_job(job_id, path.name, sha, doc["status"], warnings, doc["source"]["dpi"])
            for c in doc["cards"]:
                rel = f"jobs/{job_id}/{c['image']}"
                cid = self.store.add_card(job_id, c, c["status"], rel)
                if c["status"] == "ok":
                    self._run_ok_ids.append(cid)
            job = self.store.get_job(job_id)
            result = {"job_id": job_id, "status": job["status"], "cards": len(doc["cards"]), "sheets": 0}
            if job["status"] == "error":
                result["error"] = job["error"]
        except Exception as e:
            if not self.store.get_job(job_id):
                self.store.add_job(job_id, path.name, sha, "error", [], None, error=str(e))
            self._archive(path, job_id)
            return {"job_id": job_id, "status": "error", "cards": 0, "sheets": 0, "error": str(e)}
        self._archive(path, job_id)
        return result

    def _detect_into_job(self, path: Path, job_dir: Path) -> dict:
        doc = detect_to_dir(path, job_dir, self.s)
        src_png = job_dir / "source.png"
        if path.suffix.lower() == ".png":
            shutil.copy2(path, src_png)
        else:
            loaded = load_image(path, doc["source"]["dpi"])
            Image.fromarray(loaded.rgb).save(src_png, dpi=(doc["source"]["dpi"],) * 2)
        doc["source"]["path"] = str(src_png)
        (job_dir / "detect.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        return doc

    # ---- 面付け・出力 ----
    def _create_from_ingest(self, card_ids: list[int], preset: Preset, results: list[dict]) -> list[int]:
        """取込&作成: その回の名刺を既定値の枚数・まとめ方・並べ順で PDF にする。超過分は順序を保って次の PDF へ。"""
        if not card_ids:
            return []
        s2 = self.preset_settings(preset)
        n, cols = sheet_capacity(s2), capacity_of(s2).columns
        a = preset.arrange
        chunks: list[list[int]] = []
        if a.group == "multi":
            seq = [cid for cid in card_ids for _ in range(a.per_card or fill_count(len(card_ids), n))]
            chunks = [seq[k : k + n] for k in range(0, len(seq), n)]
        else:
            for cid in card_ids:
                seq = [cid] * (a.per_card or n)
                chunks += [seq[k : k + n] for k in range(0, len(seq), n)]
        made = []
        by_job = {r["job_id"]: r for r in results}
        for chunk in chunks:
            items: dict[int, int] = {}
            for cid in chunk:
                items[cid] = items.get(cid, 0) + 1
            jobs = {self.store.get_card(cid)["job_id"] for cid in chunk}
            sid = self.create_sheet(s2, auto_slots(chunk, n, cols, a.order), snapshot_of(preset, items), job_id=next(iter(jobs)) if len(jobs) == 1 else None)
            made.append(sid)
            sheet = self.store.get_sheet(sid)
            for jid in jobs:
                if jid in by_job:
                    by_job[jid]["sheets"] += 1
                    if sheet["status"] == "error":
                        # Report delivery failure to the CLI without changing the stored detection result.
                        by_job[jid].update(status="error", error=sheet["error"])
        return made

    def _reserve_pdf_path(self, job_id: str | None) -> Path:
        """Reserve the next sheet number across imported jobs and standalone PDFs."""
        folder = self.home.jobs / (job_id or "_pdf") / "sheets"
        folder.mkdir(parents=True, exist_ok=True)
        with (self.home.root / "pdf.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            numbers = (int(f.stem) for f in self.home.jobs.glob("*/sheets/*.pdf") if f.stem.isdigit())
            path = folder / f"{max(numbers, default=0) + 1:02d}.pdf"
            path.touch(exist_ok=False)
            return path

    def _slot_files(self, slots: dict[int, int]) -> dict[int, Path]:
        return {slot: self.home.root / self.store.get_card(cid)["image_path"] for slot, cid in slots.items()}

    def create_sheet(self, s: Settings, slots: dict[int, int], snapshot: dict, job_id: str | None = None) -> int:
        """スロット配置から PDF とシートを作る。出力先 lp かつ auto_print=OFF は印刷待ち、ON は送信、出力先 pdf は保存のみ。
        送信に失敗したシートは error（例外にはしない）。PDF の生成に失敗したら例外（シートは作らない）。"""
        pdf = self._reserve_pdf_path(job_id)
        layout = pdf.with_suffix(".layout.json")
        hold = s.print.output == "lp" and not s.print.auto_print
        try:
            write_sheet_slots(pdf, self._slot_files(slots), s, layout)
            sid = self.store.add_sheet(job_id, str(pdf.relative_to(self.home.root)), "held" if hold else "created", [], slots, snapshot)
        except Exception:
            layout.unlink(missing_ok=True)
            pdf.unlink(missing_ok=True)
            raise
        if not hold:
            self._send(sid, pdf)
        return sid

    def overwrite_sheet(self, sheet_id: int, s: Settings, slots: dict[int, int], snapshot: dict) -> int:
        """同じシート（同 id・同 PDF パス）を差し替え、状態は auto_print に従ってやり直す。送信中は ValueError。存在しなければ KeyError。
        PDF は一時ファイルへ書いてから置き換える。"""
        sh = self.store.get_sheet(sheet_id)
        if sh is None:
            raise KeyError(sheet_id)
        prev = sh["status"]
        if prev == "sending" or not self.store.claim_sheet(sheet_id, prev, "sending"):
            raise ValueError("送信中のシートは上書きできません")
        pdf = self.home.root / sh["pdf_path"]
        tmp = pdf.with_name(pdf.name + ".tmp")
        try:
            write_sheet_slots(tmp, self._slot_files(slots), s, pdf.with_suffix(".layout.json"))
            os.replace(tmp, pdf)
            self.store.replace_sheet_content(sheet_id, slots, snapshot)
        except Exception:
            self.store.set_sheet_status(sheet_id, prev, sh["error"])
            if tmp.exists():
                tmp.unlink()
            raise
        if s.print.output == "lp" and not s.print.auto_print:
            self.store.set_sheet_status(sheet_id, "held")
        else:
            self._send(sheet_id, pdf)
        return sheet_id

    def _send(self, sheet_id: int, pdf: Path, failure_status: str = "error") -> str | None:
        """成功なら None、失敗なら理由を返す。"""
        try:
            printer = self.printer_factory(self.s)
            printer.send(pdf)
        except PrinterError as e:
            self.store.set_sheet_status(sheet_id, failure_status, str(e))
            return str(e)
        if self.s.print.output == "lp":
            self.store.set_sheet_status(sheet_id, "sent")
        else:
            self.store.set_sheet_status(sheet_id, "created")
        return None

    # ---- 操作 ----
    def print_sheet(self, sheet_id: int) -> dict:
        """held のシートを出口へ送る。held 以外は ValueError、存在しなければ KeyError。
        応答用に {"sheet_id","sent","output"[,"error"]} を返す。"""
        sh = self.store.get_sheet(sheet_id)
        if sh is None:
            raise KeyError(sheet_id)
        output = self.s.print.output
        if sh["status"] != "held":
            raise ValueError("印刷待ちではないシートです")
        if output == "pdf":
            return {"sheet_id": sheet_id, "sent": False, "output": "pdf"}
        # 二度押し対策: held → sending を原子的に取れた1リクエストだけが送る
        if not self.store.claim_sheet(sheet_id, "held", "sending"):
            raise ValueError("印刷待ちではないシートです")
        try:
            err = self._send(sheet_id, self.home.root / sh["pdf_path"], failure_status="held")
        except Exception:  # 想定外の例外で 'sending' のまま残さない
            self.store.set_sheet_status(sheet_id, "held")
            raise
        if err is None:
            return {"sheet_id": sheet_id, "sent": True, "output": output}
        return {"sheet_id": sheet_id, "sent": False, "output": output, "error": err}

    def reprint_sheet(self, sheet_id: int) -> dict:
        """sent・error のシート 1 枚だけを再送する。それ以外は ValueError、存在しなければ KeyError。
        出力先 pdf のときは送らず状態も変えない。"""
        sh = self.store.get_sheet(sheet_id)
        if sh is None:
            raise KeyError(sheet_id)
        if sh["status"] not in ("sent", "error"):
            raise ValueError("再印刷できるのは送信済み・エラーのシートだけです")
        output = self.s.print.output
        if output == "pdf":
            return {"sheet_id": sheet_id, "sent": False, "output": "pdf"}
        if not self.store.claim_sheet(sheet_id, sh["status"], "sending"):
            raise ValueError("このシートは既に処理されています")
        try:
            err = self._send(sheet_id, self.home.root / sh["pdf_path"])
        except Exception:  # 想定外の例外で 'sending' のまま残さない
            self.store.set_sheet_status(sheet_id, sh["status"], sh["error"])
            raise
        if err is None:
            return {"sheet_id": sheet_id, "sent": True, "output": output}
        return {"sheet_id": sheet_id, "sent": False, "output": output, "error": err}

    def discard_sheet(self, sheet_id: int) -> None:
        """held のシートを破棄（PDF は残す。名刺には触れない）。held 以外は ValueError。"""
        if self.store.get_sheet(sheet_id) is None:
            raise KeyError(sheet_id)
        if not self.store.claim_sheet(sheet_id, "held", "discarded"):
            raise ValueError("印刷待ちではないシートです")

    def rotate(self, card_id: int) -> None:
        c = self.store.get_card(card_id)
        if c is None:
            raise KeyError(card_id)
        p = self.home.root / c["image_path"]
        with Image.open(p) as im:
            im.load()
            dpi = im.info.get("dpi")
            rotated = im.rotate(180)
        rotated.save(p, dpi=dpi) if dpi else rotated.save(p)


def snapshot_of(preset: Preset, items: dict[int, int] | list[dict]) -> dict:
    """シートに持たせる作成時設定（「調整する」で復元する値）。名刺ごとの枚数は items、スロット配置は sheet_cards。"""
    rows = [{"card_id": k, "count": v} for k, v in items.items()] if isinstance(items, dict) else items
    return {"v": 1, "settings": preset.model_dump(mode="json"), "items": rows}
