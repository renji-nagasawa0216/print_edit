"""FastAPI（仕様 9 節）。127.0.0.1 のみで起動する前提。認証なし。"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from ..adapters.imageload import render_pdf_png
from ..adapters.printers.options import printer_options
from ..core.layout import compute_layout
from ..core.settings import Settings, capacity_of
from ..home import Home
from ..pipeline import Pipeline, sheet_capacity
from ..store.db import Store

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

ALLOWED_ORIGIN_HOSTS = ("127.0.0.1", "localhost")
FOREIGN_ORIGIN_DETAIL = "別サイトからの要求は受け付けません"


def is_guarded_request(method: str, path: str) -> bool:
    """書き込み系メソッドで、復号後のパスが /api か /api/ 始まりなら対象（仕様 11.4）。"""
    return method not in ("GET", "HEAD") and (path == "/api" or path.startswith("/api/"))


def is_foreign_origin(origins: list[str]) -> bool:
    """Origin が 1 つだけで、hostname が 127.0.0.1・localhost（大小無視・完全一致）のとき以外は True。"""
    if not origins:
        return False
    if len(origins) > 1:
        return True
    try:
        host = urlsplit(origins[0]).hostname
    except ValueError:
        return True
    return host not in ALLOWED_ORIGIN_HOSTS


class ForeignOriginGuard:
    """全ルートより先に別サイトからの書き込み要求を 403 にする純 ASGI ミドルウェア。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and is_guarded_request(scope["method"], scope["path"]):
            origins = [v.decode("latin-1") for k, v in scope["headers"] if k == b"origin"]
            if is_foreign_origin(origins):
                await JSONResponse(status_code=403, content={"detail": FOREIGN_ORIGIN_DETAIL})(scope, receive, send)
                return
        await self.app(scope, receive, send)


def create_app(home: Home, printer_factory=None, lpoptions_runner=None) -> FastAPI:
    app = FastAPI(title="print-edit")
    app.add_middleware(ForeignOriginGuard)
    store = Store(home.db)
    store.recover_sending()  # 前回の API プロセスが送信中に落ちた分を印刷待ちへ戻す

    def pipe() -> Pipeline:
        kw = {"printer_factory": printer_factory} if printer_factory else {}
        return Pipeline(home, home.load_settings(), **kw)

    @app.get("/api/config")
    def get_config():
        return home.load_settings().model_dump(mode="json")

    @app.get("/api/config/schema")
    def get_schema():
        return Settings.model_json_schema()

    @app.put("/api/config")
    def put_config(body: dict = Body(...)):
        try:
            s = Settings.model_validate(body)
        except ValidationError as e:
            return JSONResponse(status_code=422, content={"detail": json.loads(e.json(include_url=False, include_context=False))})
        home.save_settings(s)
        return s.model_dump(mode="json")

    @app.get("/api/printer/options")
    def get_printer_options(name: str = ""):
        """プリンタが持つ印刷オプション（読み取りのみ。lp は呼ばない）。失敗は error に入れて 200 で返す。"""
        return printer_options(name, runner=lpoptions_runner or subprocess.run)

    @app.get("/api/info")
    def info():
        s = home.load_settings()
        return {"home": str(home.root), "inbox_dir": str(home.inbox(s)), "expected_dpi": s.intake.expected_dpi}

    @app.get("/api/capacity")
    def capacity():
        return capacity_of(home.load_settings()).to_dict()

    def _preview(s: Settings) -> dict:
        layout = compute_layout(s, [str(i + 1) for i in range(sheet_capacity(s))])
        d = layout.to_dict()
        if layout.inner_marks:
            d["inner_marks"] = layout.inner_marks
        d.update(mark_style=s.layout.mark_style, mark_dash_mm=s.layout.mark_dash_mm, mark_gap_mm=s.layout.mark_gap_mm)
        return d

    @app.get("/api/layout/preview")
    def preview():
        return _preview(home.load_settings())

    @app.post("/api/layout/preview")
    def preview_unsaved(body: dict = Body(...)):
        """画面の未保存の設定値でプレビューを返す（保存しない。検証は PUT /api/config と同じ）。"""
        try:
            s = Settings.model_validate(body)
        except ValidationError as e:
            return JSONResponse(status_code=422, content={"detail": json.loads(e.json(include_url=False, include_context=False))})
        return _preview(s)

    @app.get("/api/jobs")
    def jobs():
        return store.list_jobs()

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str):
        j = store.get_job(job_id)
        if j is None:
            raise HTTPException(404, "job not found")
        return j

    @app.get("/api/cards")
    def cards(status: str | None = None):
        return store.list_cards(status=status)

    def _card_or_404(card_id: int):
        c = store.get_card(card_id)
        if c is None:
            raise HTTPException(404, "card not found")
        return c

    @app.post("/api/cards/{card_id}/approve")
    def approve(card_id: int):
        c = _card_or_404(card_id)
        if c["status"] != "review":
            raise HTTPException(409, "review 状態のカードではありません")
        res = pipe().approve_with_result(card_id)
        return {"card": store.get_card(card_id), "sheets": res["sheets"], "delivery": res["delivery"]}

    @app.post("/api/cards/{card_id}/discard")
    def discard(card_id: int):
        _card_or_404(card_id)
        pipe().discard(card_id)
        return store.get_card(card_id)

    @app.post("/api/cards/{card_id}/rotate")
    def rotate(card_id: int):
        _card_or_404(card_id)
        pipe().rotate(card_id)
        return store.get_card(card_id)

    @app.post("/api/jobs/{job_id}/reprint")
    def reprint(job_id: str):
        if store.get_job(job_id) is None:
            raise HTTPException(404, "job not found")
        p = pipe()
        res = p.reprint(job_id)
        output = p.s.print.output
        if any(not r["sent"] for r in res):
            return JSONResponse(status_code=400, content={"detail": "送信に失敗したシートがあります", "sheets": res, "output": output})
        return {"sheets": res, "output": output}

    SHEET_STATUSES = ("created", "sent", "error", "held", "discarded")

    @app.get("/api/sheets")
    def sheets(status: str | None = None):
        if status and status not in SHEET_STATUSES:
            raise HTTPException(422, f"未知の status です: {status}")
        return store.all_sheets(status or None)

    def _sheet_or_404(sheet_id: int):
        sh = store.get_sheet(sheet_id)
        if sh is None:
            raise HTTPException(404, "sheet not found")
        return sh

    @app.get("/api/sheets/{sheet_id}/image.png")
    def sheet_image(sheet_id: int):
        sh = _sheet_or_404(sheet_id)
        pdf = (home.root / sh["pdf_path"]).resolve()
        if not pdf.is_relative_to((home.root / "jobs").resolve()) or not pdf.is_file():
            raise HTTPException(404, "sheet pdf not found")
        return Response(render_pdf_png(pdf, 300), media_type="image/png")

    @app.post("/api/sheets/{sheet_id}/print")
    def print_sheet(sheet_id: int):
        _sheet_or_404(sheet_id)
        try:
            r = pipe().print_sheet(sheet_id)
        except ValueError as e:
            raise HTTPException(409, str(e))
        if r["output"] == "lp" and not r["sent"]:
            return JSONResponse(status_code=400, content={"detail": f"送信に失敗しました: {r['error']}", "sheet_id": sheet_id, "sent": False, "output": "lp"})
        return r

    @app.post("/api/sheets/{sheet_id}/discard")
    def discard_sheet(sheet_id: int):
        _sheet_or_404(sheet_id)
        try:
            pipe().discard_sheet(sheet_id)
        except ValueError as e:
            raise HTTPException(409, str(e))
        return {"sheet_id": sheet_id, "status": "discarded"}

    @app.post("/api/ingest")
    def ingest():
        res = pipe().try_ingest()
        if res is None:
            return JSONResponse(status_code=409, content={"detail": "別の取り込みが実行中です"})
        return res

    @app.get("/files/{path:path}")
    def files(path: str):
        base = (home.root / "jobs").resolve()
        target = (home.root / path).resolve()
        if not target.is_relative_to(base) or not target.is_file():
            raise HTTPException(404, "not found")
        return FileResponse(target)

    @app.get("/")
    def index():
        return FileResponse(WEB_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app
