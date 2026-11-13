"""設定モデル（仕様 3 節）。既定値・検査・JSON Schema・API・画面フォームの唯一の正。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .layout import Capacity, compute_capacity


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Intake(_Section):
    inbox_dir: str = Field("", title="監視フォルダ", description="空なら $PRINT_EDIT_HOME/inbox")
    extensions: list[str] = Field(
        default_factory=lambda: ["png", "jpg", "jpeg", "tif", "tiff", "pdf"],
        title="対象拡張子",
        description="大文字小文字を区別しない",
    )
    expected_dpi: int = Field(600, gt=0, title="想定解像度(dpi)", description="画像に解像度情報が無いときに使う値")
    stable_wait_s: float = Field(1.0, ge=0, title="書き込み完了待ち(秒)", description="この秒数サイズが変わらなければ完了とみなす")
    max_wait_s: float = Field(30.0, ge=0, title="書き込み完了待ちの上限(秒)", description="サイズが変わり続けるファイルをこの秒数まで待つ。超えたら今回は処理しない")


class Detect(_Section):
    card_width_mm: float = Field(91.0, gt=0, title="カード長辺(mm)")
    card_height_mm: float = Field(55.0, gt=0, title="カード短辺(mm)")
    size_tolerance_mm: float = Field(1.5, ge=0, title="寸法許容差(mm)", description="各辺")
    min_area_ratio: float = Field(0.25, ge=0, le=1, title="最小面積比", description="カード面積に対しこの比未満の明領域は無視")
    threshold: int | None = Field(None, ge=0, le=255, title="2値化閾値", description="空なら自動（大津）")


class Correct(_Section):
    size_mode: Literal["fit", "actual"] = Field("fit", title="寸法モード", description="fit: カード寸法へ伸縮 / actual: 実寸のまま白地中央")
    rotate_180: bool = Field(False, title="180度回転", description="全カードを 180 度回す")
    whiten_level: int = Field(200, ge=0, le=255, title="白飛ばし輝度", description="カードごとに紙の明るさ（なだらかな照明むら）を明るい画素から推定し、正規化した輝度がこの値以上の画素を白にする。ベタ・帯など局所の暗部は紙とみなさず元の濃さのまま保つ（0 で無効）")
    edge_white_mm: float = Field(0.0, ge=0, le=5, title="縁の白塗り幅(mm)", description="出力時、カード画像の外周この幅（mm）を白にする（0 で無効）")


class Layout(_Section):
    paper_width_mm: float = Field(210.0, gt=0, title="用紙幅(mm)")
    paper_height_mm: float = Field(297.0, gt=0, title="用紙高さ(mm)")
    cards_per_sheet: int | None = Field(None, ge=1, title="1枚あたり枚数", description="空なら上限")
    align_x: Literal["left", "center", "right"] = Field("center", title="横の寄せ先")
    align_y: Literal["top", "center", "bottom"] = Field("center", title="縦の寄せ先")
    gap_x_mm: float = Field(0.0, ge=0, title="横の隙間(mm)")
    gap_y_mm: float = Field(0.0, ge=0, title="縦の隙間(mm)")
    mark_enabled: bool = Field(True, title="トンボ")
    mark_length_mm: float = Field(3.0, ge=0, title="トンボ長さ(mm)")
    mark_width_mm: float = Field(0.1, gt=0, title="トンボ線幅(mm)")
    mark_gray: int = Field(0, ge=0, le=255, title="トンボ濃度", description="0=黒〜255=白")
    mark_style: Literal["solid", "dashed"] = Field("solid", title="トンボ線種", description="solid=実線 / dashed=破線")
    mark_dash_mm: float = Field(1.0, gt=0, title="トンボ破線の線長(mm)")
    mark_gap_mm: float = Field(1.0, gt=0, title="トンボ破線の間隔(mm)")
    mark_offset_mm: float = Field(1.0, ge=0, title="トンボ離し(mm)")


class Print(_Section):
    output: Literal["pdf", "lp"] = Field("pdf", title="出力先")
    timing: Literal["per_scan", "fill", "duplicate"] = Field(
        "per_scan", title="印刷タイミング", description="per_scan: スキャンごと / fill: 枚数がたまったら / duplicate: 繰り返して埋める"
    )
    auto_print: bool = Field(
        True,
        title="自動印刷",
        description="OFF にすると、出力先が lp でもすぐ印刷せず「印刷待ち」画面で確認してから印刷します。出力先が pdf のときは効きません",
    )
    printer_name: str = Field("", title="プリンタ名", description="lp のキュー名")
    lp_options: list[str] = Field(default_factory=list, title="lp オプション", description="-o に渡す文字列")
    duplicate_count: int | None = Field(None, ge=1, title="繰り返し面数", description="duplicate のときだけ有効。空なら 1 シートの枚数（cards_per_sheet か容量）まで埋める")
    copies: int = Field(1, ge=1, title="部数")
    color_mode: Literal["mono", "color"] = Field("mono", title="カラーモード")
    scale_x: float = Field(1.0, ge=0.95, le=1.05, title="横倍率補正")
    scale_y: float = Field(1.0, ge=0.95, le=1.05, title="縦倍率補正")


class Device(_Section):
    unprintable_mm: float = Field(4.2, ge=0, title="印字不可幅(mm)", description="四辺")
    supports_color: bool = Field(False, title="カラー対応")


class Settings(_Section):
    intake: Intake = Field(default_factory=Intake, title="取込")
    detect: Detect = Field(default_factory=Detect, title="検出")
    correct: Correct = Field(default_factory=Correct, title="補正")
    layout: Layout = Field(default_factory=Layout, title="面付け")
    print: Print = Field(default_factory=Print, title="印刷")
    device: Device = Field(default_factory=Device, title="機種")

    @model_validator(mode="after")
    def _cross_check(self) -> "Settings":
        cap = capacity_of(self)
        if cap.capacity < 1:
            raise ValueError("カードが印字可能域に収まりません（容量 0）")
        n = self.layout.cards_per_sheet
        if n is not None and n > cap.capacity:
            raise ValueError(f"cards_per_sheet ({n}) が容量 ({cap.capacity}) を超えています")
        d = self.print.duplicate_count
        per_sheet = n or cap.capacity
        if d is not None and d > per_sheet:
            raise ValueError(f"duplicate_count ({d}) が 1 シートの枚数 ({per_sheet}) を超えています")
        if self.print.color_mode == "color" and not self.device.supports_color:
            raise ValueError("color_mode=color は device.supports_color=true のときだけ指定できます")
        return self


def capacity_of(s: Settings) -> Capacity:
    d = s.detect
    return compute_capacity(
        s.layout.paper_width_mm,
        s.layout.paper_height_mm,
        s.device.unprintable_mm,
        max(d.card_width_mm, d.card_height_mm),
        min(d.card_width_mm, d.card_height_mm),
        s.layout.gap_x_mm,
        s.layout.gap_y_mm,
    )
