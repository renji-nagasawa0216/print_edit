"""FastAPI（仕様 9 節）。127.0.0.1 のみで起動する前提。認証なし。"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from ..core.layout import compute_layout
from ..core.settings import Settings, capacity_of
from ..home import Home
from ..pipeline import Pipeline, sheet_capacity
from ..store.db import Store

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def create_app(home: Home, printer_factory=None) -> FastAPI:
    app = FastAPI(title="print-edit")
    store = Store(home.db)

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

    @app.get("/api/info")
    def info():
        s = home.load_settings()
        return {"home": str(home.root), "inbox_dir": str(home.inbox(s)), "expected_dpi": s.intake.expected_dpi}

    @app.get("/api/capacity")
    def capacity():
        return capacity_of(home.load_settings()).to_dict()

    @app.get("/api/layout/preview")
    def preview():
        s = home.load_settings()
        d = compute_layout(s, [str(i + 1) for i in range(sheet_capacity(s))]).to_dict()
        d.update(mark_style=s.layout.mark_style, mark_dash_mm=s.layout.mark_dash_mm, mark_gap_mm=s.layout.mark_gap_mm)
        return d

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
