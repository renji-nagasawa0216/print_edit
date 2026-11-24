"""Font catalog and upright text-overlay preview used by the card editor."""
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from ..core.text_overlay import TextBox, list_fonts, render_overlay_svg


class OverlayPreview(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")
    boxes: list[TextBox] = Field(max_length=64)
    width_mm: float = Field(default=91, gt=0, le=1000)
    height_mm: float = Field(default=55, gt=0, le=1000)


def font_router(home_root: Path) -> APIRouter:
    router = APIRouter()

    @router.get("/api/fonts")
    def fonts():
        return list_fonts(home_root)

    @router.post("/api/text-preview")
    def preview(body: OverlayPreview):
        try:
            svg = render_overlay_svg(home_root, body.boxes, body.width_mm, body.height_mm)
        except (ValueError, OSError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return Response(svg, media_type="image/svg+xml")

    return router
