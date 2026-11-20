"""取込 → 検出 → 保存 → 面付け → 出力 の進行（仕様 5.3・6・7・8）。"""
from __future__ import annotations

import fcntl
import hashlib
import json
import secrets
import shutil
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
from .core.settings import Settings, capacity_of
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
    layout = compute_layout(s, [f.name for f in files])
    images = []
    for f in files:
        with Image.open(f) as im:
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
        self.s = settings
        self.store = Store(home.db)
        self.printer_factory = printer_factory
        self._sleep = sleep

    # ---- ingest ----
    def ingest_once(self) -> list[dict]:
        r = self.try_ingest()
        return [] if r is None else r

    def try_ingest(self) -> list[dict] | None:
        """ロックが取れず取り込めなかったとき None を返す。"""
        self.home.ensure(self.s)
        with open(self.home.lock, "w") as lf:
            try:
                fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return None
            kw = {"sleep": self._sleep} if self._sleep else {}
            src = FolderSource(self.home.inbox(self.s), self.s.intake.extensions, self.s.intake.stable_wait_s, max_wait_s=self.s.intake.max_wait_s, **kw)
            results = []
            for path in src.poll():
                try:
                    r = self.process_file(path)
                except Exception as e:  # 1ファイルの失敗で止めない
                    r = {"job_id": None, "status": "error", "cards": 0, "sheets": 0, "error": str(e), "source": path.name}
                if r is not None:
                    results.append(r)
            return results

    def _archive(self, path: Path, job_id: str) -> None:
        dest = self.home.processed / f"{job_id}_{path.name}"
        i = 1
        while dest.exists():
            dest = self.home.processed / f"{job_id}_{i}_{path.name}"
            i += 1
        shutil.move(str(path), str(dest))

    def process_file(self, path: Path) -> dict | None:
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
            ok_ids = []
            for c in doc["cards"]:
                rel = f"jobs/{job_id}/{c['image']}"
                cid = self.store.add_card(job_id, c, c["status"], rel)
                if c["status"] == "ok":
                    ok_ids.append(cid)
            sheets = self.schedule(job_id, ok_ids)
            job = self.store.get_job(job_id)
            result = {"job_id": job_id, "status": job["status"], "cards": len(doc["cards"]), "sheets": len(sheets)}
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
    def schedule(self, owner_job: str, card_ids: list[int]) -> list[int]:
        """ok になったカードを印刷タイミングの規則でシートにする。作ったシート id を返す。"""
        if not card_ids:
            return []
        n = sheet_capacity(self.s)
        timing = self.s.print.timing
        made: list[int] = []
        if timing == "per_scan":
            for k in range(0, len(card_ids), n):
                made.append(self._make_sheet(owner_job, card_ids[k : k + n]))
        elif timing == "duplicate" and self.s.print.duplicate_count is not None:
            d = self.s.print.duplicate_count
            per = n // d
            for k in range(0, len(card_ids), per):
                chunk = card_ids[k : k + per]
                made.append(self._make_sheet(owner_job, [c for c in chunk for _ in range(d)]))
        elif timing == "duplicate":
            for k in range(0, len(card_ids), n):
                chunk = card_ids[k : k + n]
                filled = [chunk[i % len(chunk)] for i in range(n)]
                made.append(self._make_sheet(owner_job, filled))
        else:  # fill
            for cid in card_ids:
                self.store.set_card_status(cid, "pending")
            pend = self.store.pending_cards()
            while len(pend) >= n:
                chunk, pend = pend[:n], pend[n:]
                jobs = {c["job_id"] for c in chunk}
                made.append(self._make_sheet(owner_job, [c["id"] for c in chunk], job_id=jobs.pop() if len(jobs) == 1 else None))
        return made

    def _make_sheet(self, owner_job: str, card_ids: list[int], job_id: str | None | bool = True) -> int:
        sheet_job = owner_job if job_id is True else job_id
        files = []
        for cid in card_ids:
            c = self.store.get_card(cid)
            files.append(self.home.root / c["image_path"])
        sdir = self.home.jobs / owner_job / "sheets"
        sdir.mkdir(parents=True, exist_ok=True)
        no = len(list(sdir.glob("*.pdf"))) + 1
        pdf = sdir / f"{no:02d}.pdf"
        write_sheet(pdf, files, self.s, pdf.with_suffix(".layout.json"))
        hold = self.s.print.output == "lp" and not self.s.print.auto_print
        sid = self.store.add_sheet(sheet_job, str(pdf.relative_to(self.home.root)), "held" if hold else "created", card_ids)
        if hold:  # 印刷待ち: 送らない。カードは held（別シートへの再面付け・fill の保留戻しの対象外）
            for cid in set(card_ids):
                self.store.set_card_status(cid, "held")
            return sid
        err = self._send(sid, pdf)
        if err is None:
            for cid in set(card_ids):
                self.store.set_card_status(cid, "printed")
        else:
            # 失敗: カードは ok のまま残し（fill の pending も戻す）、関係するジョブを error にする
            jobs = set()
            for cid in set(card_ids):
                c = self.store.get_card(cid)
                jobs.add(c["job_id"])
                if c["status"] == "pending":
                    self.store.set_card_status(cid, "ok")
            if sheet_job:
                jobs.add(sheet_job)
            for jid in jobs:
                self.store.set_job_status(jid, "error", err)
        return sid

    def _send(self, sheet_id: int, pdf: Path) -> str | None:
        """成功なら None、失敗なら理由を返す。"""
        try:
            printer = self.printer_factory(self.s)
            printer.send(pdf)
        except PrinterError as e:
            self.store.set_sheet_status(sheet_id, "error", str(e))
            return str(e)
        if self.s.print.output == "lp":
            self.store.set_sheet_status(sheet_id, "sent")
        else:
            self.store.set_sheet_status(sheet_id, "created")
        return None

    # ---- 操作 ----
    def recompute_job(self, job_id: str) -> None:
        """ジョブ status の再計算（仕様 11.1）: 出口失敗の error > review カードあり > ok。discarded は除く。"""
        j = self.store.get_job(job_id)
        if j is None:
            return
        if self.store.error_sheet_count_touching_job(job_id) > 0:
            self.store.set_job_status(job_id, "error", j["error"] or "出口の送信に失敗しました")
        elif any(c["status"] == "review" for c in j["cards"]):
            self.store.set_job_status(job_id, "review", None)
        else:
            self.store.set_job_status(job_id, "ok", None)

    def _jobs_of_sheet(self, sheet: dict) -> set[str]:
        jobs = {self.store.get_card(cid)["job_id"] for cid in self.store.sheet_card_ids(sheet["id"])}
        if sheet["job_id"]:
            jobs.add(sheet["job_id"])
        return jobs

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
            err = self._send(sheet_id, self.home.root / sh["pdf_path"])
        except Exception:  # 想定外の例外で 'sending' のまま残さない
            self.store.set_sheet_status(sheet_id, "held")
            raise
        jobs = self._jobs_of_sheet(sh)
        if err is None:
            for cid in self.store.sheet_card_ids(sheet_id):
                if self.store.get_card(cid)["status"] == "held":
                    self.store.set_card_status(cid, "printed")
            for jid in jobs:
                self.recompute_job(jid)
            return {"sheet_id": sheet_id, "sent": True, "output": output}
        for jid in jobs:  # カードは held のまま
            self.store.set_job_status(jid, "error", err)
        return {"sheet_id": sheet_id, "sent": False, "output": output, "error": err}

    def discard_sheet(self, sheet_id: int) -> None:
        """held のシートを破棄（カードも discarded、PDF は残す）。held 以外は ValueError。"""
        sh = self.store.get_sheet(sheet_id)
        if sh is None:
            raise KeyError(sheet_id)
        if not self.store.claim_sheet(sheet_id, "held", "discarded"):
            raise ValueError("印刷待ちではないシートです")
        for cid in self.store.sheet_card_ids(sheet_id):
            self.store.set_card_status(cid, "discarded")
        for jid in self._jobs_of_sheet(sh):
            self.recompute_job(jid)

    def approve_with_result(self, card_id: int) -> dict:
        c = self.store.get_card(card_id)
        if c is None or c["status"] != "review":
            raise ValueError("review 状態のカードではありません")
        self.store.set_card_status(card_id, "ok")
        sheets = self.schedule(c["job_id"], [card_id])
        errors = [r["error"] or "出口の送信に失敗しました" for r in (self.store.get_sheet(sid) for sid in sheets) if r["status"] == "error"]
        self.recompute_job(c["job_id"])
        return {"sheets": sheets, "delivery": {"ok": not errors, "error": "; ".join(errors) or None}}

    def approve(self, card_id: int) -> list[int]:
        return self.approve_with_result(card_id)["sheets"]

    def discard(self, card_id: int) -> None:
        c = self.store.get_card(card_id)
        if c is None:
            raise KeyError(card_id)
        self.store.set_card_status(card_id, "discarded")
        self.recompute_job(c["job_id"])

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
        self.recompute_job(c["job_id"])

    def reprint(self, job_id: str) -> list[dict]:
        job = self.store.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        out = []
        touched = {job_id}
        for sh in self.store.sheets_touching_job(job_id):
            err = self._send(sh["id"], self.home.root / sh["pdf_path"])
            if err is None:
                for c in sh["cards"]:
                    card = self.store.get_card(c["card_id"])
                    touched.add(card["job_id"])
                    if card["status"] in ("ok", "held"):  # held: 元 held シートが送信失敗 → 再印刷で成功
                        self.store.set_card_status(card["id"], "printed")
            out.append({"sheet_id": sh["id"], "sent": err is None})
        for jid in touched:
            j = self.store.get_job(jid)
            if j["status"] == "error" and self.store.error_sheet_count_touching_job(jid) == 0:
                review = any(c["status"] == "review" for c in j["cards"])
                self.store.set_job_status(jid, "review" if review else "ok", None)
        return out
