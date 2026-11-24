"""FastAPI（仕様 9 節）。127.0.0.1 のみで起動する前提。認証なし。"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import sqlite3

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .text_fonts import font_router
from ..core.text_overlay import TextBox, render_overlay_svg, validate_fonts
from ..adapters.sources.folder import FolderSource
from ..adapters.sources.launchd import watch_status
from ..adapters.imageload import render_pdf_png
from ..adapters.printers.options import printer_options
from ..core.layout import compute_layout
from ..arrange import auto_slots
from ..core.settings import GlobalSettings, Preset, Settings, capacity_of, compose
from ..home import Home
from ..pipeline import Pipeline, sheet_capacity, snapshot_of
from ..store.db import NAME_MAX, PRESET_NAME_MAX, REG_DELETED, REG_DISCARDED, REG_MASTER, REG_PENDING, Store

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

ALLOWED_ORIGIN_HOSTS = ("127.0.0.1", "localhost")
FOREIGN_ORIGIN_DETAIL = "別サイトからの要求は受け付けません"
REG_LABEL = {REG_PENDING: "登録待ち", REG_MASTER: "登録済み", REG_DELETED: "マスタから削除済み", REG_DISCARDED: "破棄済み"}
NO_SEND_DETAIL = "送信なし（出力先 pdf）"


class _Item(BaseModel):
    model_config = ConfigDict(extra="forbid")
    card_id: int
    count: int = Field(ge=1)


class PdfBody(BaseModel):
    """PDF 作成画面の保存。items=名刺ごとの枚数、slots=スロット番号→名刺（省略なら並べ順で自動割当）、preset=補正・面付け・並べ方。"""

    model_config = ConfigDict(extra="forbid")
    items: list[_Item]
    slots: dict[int, int] | None = None
    preset: Preset | None = None


class TextMasterBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=NAME_MAX)
    boxes: list[TextBox] = Field(min_length=1, max_length=64)


class IdsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[int]


def _validation_detail(e: ValidationError) -> list:
    return json.loads(e.json(include_url=False, include_context=False))


def _bad(msg: str, loc: tuple = ()) -> HTTPException:
    return HTTPException(422, [{"loc": list(loc), "msg": msg}])


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
    app.include_router(font_router(home.root))
    home.prepare()  # 旧 config・旧 DB の移行と「既定」の用意（冪等）
    store = Store(home.db)
    store.recover_sending()  # 前回の API プロセスが送信中に落ちた分を印刷待ちへ戻す

    def pipe() -> Pipeline:
        kw = {"printer_factory": printer_factory} if printer_factory else {}
        return Pipeline(home, home.load_settings(), **kw)

    # ---- 全体設定 ----
    def _check_presets(g: GlobalSettings) -> None:
        """全体設定を変えても、既存の既定値すべてが容量などの検査を通ることを確かめる。"""
        for p in store.list_presets():
            try:
                compose(g, Preset.model_validate(p["data"]))
            except ValidationError as e:
                raise HTTPException(422, [{"loc": ["preset", p["name"]], "msg": d["msg"]} for d in _validation_detail(e)])
        ai = g.auto_ingest
        if ai.mode == "ingest_create" and ai.preset_id is not None and store.get_preset(ai.preset_id) is None:
            raise _bad("自動取り込みの既定値が存在しません", ("auto_ingest", "preset_id"))

    @app.get("/api/config")
    def get_config():
        return home.load_global().model_dump(mode="json")

    @app.get("/api/config/schema")
    def get_schema():
        return GlobalSettings.model_json_schema()

    @app.put("/api/config")
    def put_config(body: dict = Body(...)):
        try:
            g = GlobalSettings.model_validate({"last_preset_id": home.load_global().last_preset_id, **body})
        except ValidationError as e:
            return JSONResponse(status_code=422, content={"detail": _validation_detail(e)})
        _check_presets(g)
        home.save_global(g)
        return g.model_dump(mode="json")

    @app.get("/api/printer/options")
    def get_printer_options(name: str = ""):
        """プリンタが持つ印刷オプション（読み取りのみ。lp は呼ばない）。失敗は error に入れて 200 で返す。"""
        return printer_options(name, runner=lpoptions_runner or subprocess.run)

    @app.get("/api/info")
    def info():
        s = home.load_settings()
        inbox = home.inbox(s)
        source = FolderSource(inbox, s.intake.extensions, s.intake.stable_wait_s)
        try:
            count = source.pending_count()
        except OSError:
            count = None
        return {"home": str(home.root), "inbox_dir": str(inbox), "expected_dpi": s.intake.expected_dpi,
                "pending_count": count, "last_ingest_at": store.last_ingest_at(), "watch_status": watch_status(inbox)}

    @app.get("/api/capacity")
    def capacity():
        return capacity_of(home.load_settings()).to_dict()

    # ---- 既定値 ----
    @app.get("/api/presets")
    def presets():
        return store.list_presets()

    @app.get("/api/presets/schema")
    def presets_schema():
        return Preset.model_json_schema()

    def _preset_name(name, exclude_id: int | None = None) -> str:
        n = (name or "").strip()
        if not n:
            raise _bad("既定値の名前を入力してください", ("name",))
        if len(n) > PRESET_NAME_MAX:
            raise _bad(f"既定値の名前は{PRESET_NAME_MAX}字以内で入力してください", ("name",))
        if any(p["name"] == n and p["id"] != exclude_id for p in store.list_presets()):
            raise _bad("同じ名前の既定値があります", ("name",))
        return n

    def _preset_data(data) -> dict:
        try:
            p = Preset.model_validate(data)
            compose(home.load_global(), p)  # 容量超過などは保存時に拒否する
        except ValidationError as e:
            raise HTTPException(422, _validation_detail(e))
        return p.model_dump(mode="json")

    @app.post("/api/presets")
    def create_preset(body: dict = Body(...)):
        name = _preset_name(body.get("name"))
        data = _preset_data(body.get("data") or {})
        try:
            pid = store.add_preset(name, data)
        except sqlite3.IntegrityError:
            raise _bad("同じ名前の既定値があります", ("name",))
        return store.get_preset(pid)

    @app.put("/api/presets/{preset_id}")
    def update_preset(preset_id: int, body: dict = Body(...)):
        cur = store.get_preset(preset_id)
        if cur is None:
            raise HTTPException(404, "preset not found")
        name = None
        if body.get("name") is not None:
            name = _preset_name(body["name"], preset_id)
            if cur["builtin"] and name != cur["name"]:
                raise _bad("「既定」の名前は変更できません", ("name",))
        data = _preset_data(body["data"]) if body.get("data") is not None else None
        try:
            store.update_preset(preset_id, name, data)
        except sqlite3.IntegrityError:
            raise _bad("同じ名前の既定値があります", ("name",))
        return store.get_preset(preset_id)

    @app.delete("/api/presets/{preset_id}")
    def delete_preset(preset_id: int):
        cur = store.get_preset(preset_id)
        if cur is None:
            raise HTTPException(404, "preset not found")
        if cur["builtin"]:
            raise HTTPException(409, "「既定」は削除できません")
        ai = home.load_global().auto_ingest
        if ai.mode == "ingest_create" and ai.preset_id == preset_id:
            raise HTTPException(409, "全体設定の自動取り込みが使っている既定値なので削除できません")
        store.delete_preset(preset_id)
        return {"id": preset_id}

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
        """画面の未保存の既定値（補正・面付け・並べ方）でプレビューを返す（保存しない。検証は既定値の保存と同じ）。"""
        try:
            return _preview(compose(home.load_global(), Preset.model_validate(body)))
        except ValidationError as e:
            return JSONResponse(status_code=422, content={"detail": _validation_detail(e)})

    # ---- 履歴 ----
    @app.get("/api/jobs")
    def jobs():
        return store.list_jobs()

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str):
        j = store.get_job(job_id)
        if j is None:
            raise HTTPException(404, "job not found")
        return j

    @app.get("/api/history")
    def history():
        return store.history()

    # ---- 名刺（登録待ち・名刺マスタ）----
    @app.get("/api/cards")
    def cards(status: str | None = None, reg: str | None = None, q: str | None = None):
        return store.list_cards(status=status, reg=reg, q=q or None)

    def _card_or_404(card_id: int):
        c = store.get_card(card_id)
        if c is None:
            raise HTTPException(404, "card not found")
        return c

    @app.get("/api/cards/{card_id}/text-overlay.svg")
    def text_overlay(card_id: int):
        card = _card_or_404(card_id)
        dims = home.load_global().detect
        width, height = sorted((dims.card_width_mm, dims.card_height_mm), reverse=True)
        try:
            svg = render_overlay_svg(home.root, card["boxes"], width, height)
        except (ValueError, OSError) as exc:
            raise _bad(str(exc), ("boxes",)) from exc
        return Response(svg, media_type="image/svg+xml", headers={"Cache-Control": "no-cache"})

    def _text_values(body: TextMasterBody):
        name = body.name.strip()
        if not name:
            raise _bad("名前を入力してください", ("name",))
        try:
            validate_fonts(home.root, body.boxes)
        except (OSError, ValueError) as exc:
            raise _bad(str(exc), ("boxes",)) from exc
        return name, [box.model_dump(mode="json") for box in body.boxes]

    @app.post("/api/cards/{card_id}/text-masters")
    def create_text_master(card_id: int, body: TextMasterBody):
        _card_or_404(card_id)
        name, boxes = _text_values(body)
        try:
            child_id = store.create_text_master(card_id, name, boxes)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return store.get_card(child_id)

    @app.put("/api/cards/{card_id}/text-master")
    def update_text_master(card_id: int, body: TextMasterBody):
        _card_or_404(card_id)
        name, boxes = _text_values(body)
        try:
            store.update_text_master(card_id, name, boxes)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return store.get_card(card_id)

    def _change(card_id: int, from_reg: str, to_reg: str) -> dict:
        _card_or_404(card_id)
        try:
            changed = store.change_reg(card_id, from_reg, to_reg)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        if not changed:
            raise HTTPException(409, f"{REG_LABEL[from_reg]}の名刺ではありません（現在: {REG_LABEL.get(store.get_card(card_id)['reg'], '不明')}）")
        return store.get_card(card_id)

    @app.post("/api/cards/{card_id}/register")
    def register(card_id: int):
        return _change(card_id, REG_PENDING, REG_MASTER)

    @app.post("/api/cards/{card_id}/discard")
    def discard(card_id: int):
        return _change(card_id, REG_PENDING, REG_DISCARDED)

    @app.delete("/api/cards/{card_id}")
    def delete_card(card_id: int):
        """マスタから削除（論理削除。画像・sheet_cards は残す）。"""
        return _change(card_id, REG_MASTER, REG_DELETED)

    @app.post("/api/cards/{card_id}/rotate")
    def rotate(card_id: int):
        card = _card_or_404(card_id)
        if card["parent_id"] is not None:
            raise HTTPException(409, "テキスト入りマスタの元画像は回転できません")
        pipe().rotate(card_id)
        return store.get_card(card_id)

    @app.put("/api/cards/{card_id}/name")
    def card_name(card_id: int, body: dict = Body(...)):
        c = _card_or_404(card_id)
        if c["reg"] != REG_MASTER:
            raise HTTPException(409, "名前を付けられるのは名刺マスタの名刺だけです")
        name = str(body.get("name") or "").strip()
        if len(name) > NAME_MAX:
            raise _bad(f"名前は{NAME_MAX}字以内で入力してください", ("name",))
        if c["parent_id"] is not None and not name:
            raise _bad("名前を入力してください", ("name",))
        store.set_card_name(card_id, name or None)
        return store.get_card(card_id)

    def _summary(rows: list[dict], ok_key: str = "ok") -> dict:
        n = sum(1 for r in rows if r[ok_key])
        return {"success": n, "failed": len(rows) - n, "results": rows}

    def _bulk_cards(ids: list[int], from_reg: str, to_reg: str) -> dict:
        rows = []
        for cid in dict.fromkeys(ids):
            c = store.get_card(cid)
            if c is None:
                rows.append({"id": cid, "ok": False, "source_name": None, "idx": None, "detail": "名刺が見つかりません"})
            elif store.change_reg(cid, from_reg, to_reg):
                rows.append({"id": cid, "ok": True, "source_name": c["source_name"], "idx": c["idx"], "detail": ""})
            else:
                now_reg = store.get_card(cid)["reg"]
                rows.append({"id": cid, "ok": False, "source_name": c["source_name"], "idx": c["idx"], "detail": f"{REG_LABEL[from_reg]}ではありません（現在: {REG_LABEL.get(now_reg, '不明')}）"})
        return _summary(rows)

    @app.post("/api/bulk/cards/register")
    def bulk_register(body: IdsBody):
        return _bulk_cards(body.ids, REG_PENDING, REG_MASTER)

    @app.post("/api/bulk/cards/discard")
    def bulk_discard_cards(body: IdsBody):
        return _bulk_cards(body.ids, REG_PENDING, REG_DISCARDED)

    # ---- シート ----
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

    @app.get("/api/sheets/{sheet_id}/adjust")
    def sheet_adjust(sheet_id: int):
        """履歴の「調整する」: PDF 作成画面に復元する値。作成時設定が無い旧シートは名刺と配置だけ復元し、設定は「既定」で補う。"""
        sh = _sheet_or_404(sheet_id)
        slots = store.sheet_slots(sheet_id)
        snap = sh["snapshot"]
        if snap:
            settings, items = snap["settings"], snap["items"]
        else:
            counts: dict[int, int] = {}
            for _, cid in sorted(slots.items()):
                counts[cid] = counts.get(cid, 0) + 1
            settings, items = home.get_preset().model_dump(mode="json"), [{"card_id": k, "count": v} for k, v in counts.items()]
        ids = list(dict.fromkeys([i["card_id"] for i in items] + list(slots.values())))
        return {
            "sheet": {"id": sheet_id, "job_id": sh["job_id"], "status": sh["status"], "pdf_path": sh["pdf_path"]},
            "has_snapshot": bool(snap),
            "settings": settings,
            "items": items,
            "slots": {str(k): v for k, v in slots.items()},
            "cards": [store.get_card(i) for i in ids if store.get_card(i)],
        }

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

    @app.post("/api/sheets/{sheet_id}/reprint")
    def reprint_sheet(sheet_id: int):
        """履歴のシート単位の再印刷（sent・error のシートだけ）。出力先 pdf は送らず状態も変えない。"""
        _sheet_or_404(sheet_id)
        try:
            r = pipe().reprint_sheet(sheet_id)
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

    @app.post("/api/bulk/sheets/print")
    def bulk_print(body: IdsBody):
        """一括印刷。1 件失敗しても続行し、シートごとの結果を返す。失敗したシートは印刷待ちのまま。"""
        p, rows = pipe(), []
        for sid in dict.fromkeys(body.ids):
            row = {"sheet_id": sid, "ok": False, "status": "error", "detail": ""}
            try:
                r = p.print_sheet(sid)
                if r["sent"]:
                    row.update(ok=True, status="sent", detail="印刷しました")
                elif r["output"] == "pdf":
                    row.update(ok=True, status="no_send", detail=NO_SEND_DETAIL)
                else:
                    row["detail"] = f"印刷に失敗しました: {r['error']}"
            except KeyError:
                row["detail"] = "シートが見つかりません"
            except ValueError:
                row["detail"] = "このシートは既に処理されています"
            except Exception as e:
                row["detail"] = f"印刷に失敗しました: {e}"
            rows.append(row)
        return _summary(rows)

    @app.post("/api/bulk/sheets/discard")
    def bulk_discard_sheets(body: IdsBody):
        p, rows = pipe(), []
        for sid in dict.fromkeys(body.ids):
            row = {"sheet_id": sid, "ok": False, "status": "error", "detail": ""}
            try:
                p.discard_sheet(sid)
                row.update(ok=True, status="discarded", detail="破棄しました")
            except KeyError:
                row["detail"] = "シートが見つかりません"
            except ValueError:
                row["detail"] = "このシートは既に処理されています"
            rows.append(row)
        return _summary(rows)

    # ---- PDF 作成 ----
    def _plans(body: PdfBody) -> tuple[Pipeline, Settings, Preset, list[tuple[dict[int, int], list[dict]]]]:
        """保存内容を検証し、作るシートごとの (スロット→名刺, 名刺別枚数) にする。"""
        preset = body.preset or home.get_preset()
        p = pipe()
        try:
            s2 = p.preset_settings(preset)
        except ValidationError as e:
            raise HTTPException(422, _validation_detail(e))
        n, cols = sheet_capacity(s2), capacity_of(s2).columns
        if not body.items:
            raise _bad("名刺がありません", ("items",))

        def usable(cid: int) -> None:
            c = store.get_card(cid)
            if c is None:
                raise _bad(f"名刺 #{cid} が見つかりません", ("items",))
            if c["reg"] in (REG_DELETED, REG_DISCARDED):
                raise _bad(f"名刺 #{cid} は{REG_LABEL[c['reg']]}のため使えません", ("items",))

        for it in body.items:
            usable(it.card_id)
        if body.slots is not None:
            if not body.slots:
                raise _bad("名刺がありません", ("slots",))
            for slot, cid in body.slots.items():
                if not 1 <= slot <= n:
                    raise _bad(f"スロット {slot} は 1〜{n} の範囲外です", ("slots",))
                usable(cid)
        rows = [{"card_id": it.card_id, "count": it.count} for it in body.items]
        if preset.arrange.group == "single":
            plans = []
            for it in body.items:
                if it.count > n:
                    raise _bad(f"名刺 #{it.card_id} の枚数が容量 {n} 枚を超えています（{it.count - n}枚超過）", ("items",))
                slots = {sl: it.card_id for sl in body.slots} if body.slots is not None else auto_slots([it.card_id] * it.count, n, cols, preset.arrange.order)
                plans.append((slots, [{"card_id": it.card_id, "count": it.count}]))
            return p, s2, preset, plans
        total = sum(it.count for it in body.items)
        if total > n:
            raise _bad(f"合計 {total} 枚が容量 {n} 枚を超えています（{total - n}枚超過）", ("items",))
        slots = body.slots if body.slots is not None else auto_slots([it.card_id for it in body.items for _ in range(it.count)], n, cols, preset.arrange.order)
        return p, s2, preset, [(dict(slots), rows)]

    def _delivery(p: Pipeline, ids: list[int]) -> dict:
        errs = [r["error"] or "出口の送信に失敗しました" for r in (p.store.get_sheet(i) for i in ids) if r["status"] == "error"]
        return {"ok": not errs, "error": "; ".join(errs) or None}

    @app.post("/api/pdf")
    def pdf_new(body: PdfBody):
        """新規保存。まとめ方が複数名刺1PDF なら 1 つ、1名刺1PDF なら名刺の数だけシートを作る。"""
        p, s2, preset, plans = _plans(body)
        card_ids = {cid for slots, _ in plans for cid in slots.values()}
        boxes = [box for cid in card_ids for box in store.get_card(cid)["boxes"]]
        if boxes:
            try:
                validate_fonts(home.root, boxes)
            except (ValueError, OSError) as exc:
                raise _bad(str(exc), ("items",)) from exc
        made = []
        try:
            for slots, items in plans:
                made.append(p.create_sheet(s2, slots, snapshot_of(preset, items)))
        except Exception as e:
            raise HTTPException(500, f"PDF の作成に失敗しました: {e}")
        return {"sheets": [{"id": i, "status": p.store.get_sheet(i)["status"]} for i in made], "delivery": _delivery(p, made)}

    @app.put("/api/sheets/{sheet_id}/pdf")
    def pdf_overwrite(sheet_id: int, body: PdfBody):
        """上書き保存。作成結果が 1 つの PDF のときだけ。送信中のシートは 409。"""
        _sheet_or_404(sheet_id)
        p, s2, preset, plans = _plans(body)
        if len(plans) != 1:
            raise _bad("上書きできるのは作成結果が 1 つの PDF のときだけです", ("items",))
        try:
            p.overwrite_sheet(sheet_id, s2, plans[0][0], snapshot_of(preset, plans[0][1]))
        except ValueError as e:
            raise HTTPException(409, str(e))
        except Exception as e:
            raise HTTPException(500, f"PDF の作成に失敗しました: {e}")
        return {"sheets": [{"id": sheet_id, "status": p.store.get_sheet(sheet_id)["status"]}], "delivery": _delivery(p, [sheet_id])}

    # ---- 取り込み ----
    @app.post("/api/ingest")
    def ingest():
        """取り込みのみ（切り出して登録待ちへ。PDF は作らない）。"""
        res = pipe().try_ingest()
        if res is None:
            return JSONResponse(status_code=409, content={"detail": "別の取り込みが実行中です"})
        return res

    @app.post("/api/ingest/create")
    def ingest_create(body: dict = Body(...)):
        """取込&作成。選んだ既定値を全体設定に覚え、その回に取り込んだ名刺で PDF を作る。"""
        pid = body.get("preset_id")
        row = store.get_preset(pid) if pid is not None else store.default_preset()
        if row is None:
            raise _bad("既定値が見つかりません", ("preset_id",))
        g = home.load_global()
        g.last_preset_id = row["id"]
        home.save_global(g)
        try:
            res = pipe().ingest(Preset.model_validate(row["data"]))
        except Exception as e:
            raise HTTPException(500, f"PDF の作成に失敗しました: {e}")
        if res is None:
            return JSONResponse(status_code=409, content={"detail": "別の取り込みが実行中です"})
        return {"results": res["results"], "cards": res["cards"], "pdfs": len(res["sheets"]), "sheets": res["sheets"]}

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
