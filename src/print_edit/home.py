"""データ置き場と設定ファイルの入出力（仕様 2 節）。"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .core.settings import Arrange, AutoIngest, GlobalSettings, Preset, Settings, compose
from .store.db import Store


class Home:
    def __init__(self, root: str | Path | None = None, config: str | Path | None = None):
        if root is None:
            root = os.environ.get("PRINT_EDIT_HOME") or "~/PrintEdit"
        self.root = Path(root).expanduser().resolve()
        self.config_path = Path(config).expanduser() if config else self.root / "config.json"
        self.external_config = bool(config)  # 外部 --config は読み取り専用（旧形式でもファイル・.bak・DB を書かない）

    @property
    def processed(self) -> Path:
        return self.root / "processed"

    @property
    def jobs(self) -> Path:
        return self.root / "jobs"

    @property
    def db(self) -> Path:
        return self.root / "db.sqlite3"

    @property
    def lock(self) -> Path:
        return self.root / "ingest.lock"

    def inbox(self, s: Settings) -> Path:
        return Path(s.intake.inbox_dir).expanduser() if s.intake.inbox_dir else self.root / "inbox"

    def ensure(self, s: Settings) -> None:
        for d in (self.root, self.inbox(s), self.processed, self.jobs):
            d.mkdir(parents=True, exist_ok=True)

    # ---- 全体設定（config.json）----
    @staticmethod
    def _is_legacy(raw: dict) -> bool:
        """旧形式（補正・面付けが config.json にある／print.timing・duplicate_count がある）か。"""
        pr = raw.get("print") if isinstance(raw.get("print"), dict) else {}
        return "correct" in raw or "layout" in raw or "timing" in pr or "duplicate_count" in pr

    def load_global(self) -> GlobalSettings:
        return self._read_global()[0]

    def _read_global(self) -> tuple[GlobalSettings, Preset | None]:
        """全体設定と、外部 --config が旧形式のときにメモリ上で変換した既定値（それ以外は None）。"""
        if not self.config_path.exists():
            return GlobalSettings(), None
        text = self.config_path.read_text(encoding="utf-8")
        raw = json.loads(text)
        if not self._is_legacy(raw):
            return GlobalSettings.model_validate(raw), None
        if self.external_config:
            return self._convert_legacy(raw)
        return self._migrate_legacy(raw, text), None

    @staticmethod
    def _convert_legacy(raw: dict) -> tuple[GlobalSettings, Preset]:
        """旧形式を全体設定と既定値へ分ける（書き込みなし）。旧 timing・duplicate_count は
        複数名刺1PDF・枚数（duplicate は繰り返し面数、空は全部埋める／それ以外は 1）・行優先へ変換する。"""
        raw = json.loads(json.dumps(raw))
        pr = raw.get("print") or {}
        timing, dup = pr.pop("timing", "per_scan"), pr.pop("duplicate_count", None)
        arrange = Arrange(group="multi", per_card=dup if timing == "duplicate" else 1, order="row")
        preset = Preset(correct=raw.pop("correct", {}), layout=raw.pop("layout", {}), arrange=arrange)
        raw["print"] = pr
        g = GlobalSettings.model_validate({**raw, "auto_ingest": AutoIngest(mode="ingest_create").model_dump()})
        compose(g, preset)  # 容量などの検査（旧設定が不正なら移行せず例外）
        return g, preset

    def _migrate_legacy(self, raw: dict, text: str) -> GlobalSettings:
        """旧 config.json を、既定値「既定」（DB）と全体設定（config.json）へ分ける。
        先に検証し、config.json.bak へ退避してから、既定値テーブルが空のときだけ「既定」を作る。"""
        g, preset = self._convert_legacy(raw)
        bak = self.config_path.with_name(self.config_path.name + ".bak")
        if not bak.exists():
            bak.write_text(text, encoding="utf-8")
        store = Store(self.db)
        pid = store.add_preset("既定", preset.model_dump(mode="json"), builtin=True) if store.preset_count() == 0 else (store.default_preset() or {}).get("id")
        g.auto_ingest.preset_id = pid
        self.save_global(g)
        return g

    def save_global(self, g: GlobalSettings) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.config_path.with_name(self.config_path.name + ".tmp")
        tmp.write_text(json.dumps(g.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.config_path)

    # ---- 既定値 ----
    def get_preset(self, preset_id: int | None = None) -> Preset:
        """preset_id の既定値。None・存在しない id（削除済み）は「既定」。DB が無ければ初期値（home は作らない）。
        外部 --config が旧形式なら、「既定」の代わりにそこから変換した既定値を使う。"""
        legacy = self._read_global()[1] if self.external_config else None
        if legacy is not None and preset_id is None:
            return legacy
        if not self.db.exists():
            return legacy if legacy is not None else Preset()
        store = Store(self.db)
        row = store.get_preset(preset_id) if preset_id is not None else None
        if row is None and legacy is not None:
            return legacy
        row = row or store.default_preset()
        return Preset.model_validate(row["data"]) if row else Preset()

    def prepare(self) -> GlobalSettings:
        """起動時の準備（冪等）。旧 config の移行・DB の移行・「既定」の用意。"""
        g = self.load_global()
        store = Store(self.db)
        if store.default_preset() is None:
            store.add_preset("既定", Preset().model_dump(mode="json"), builtin=True)
        return g

    def load_settings(self) -> Settings:
        """全体設定＋既定値「既定」から、描画・容量計算が受け取る Settings を返す。"""
        g, legacy = self._read_global()
        return compose(g, legacy if legacy is not None else self.get_preset())

    def save_settings(self, s: Settings) -> None:
        """Settings を全体設定と既定値「既定」へ分けて保存する（Settings 単位で扱う呼び出し元・テスト用）。"""
        cur = self.load_global() if self.config_path.exists() else GlobalSettings(auto_ingest=AutoIngest(mode="ingest_create"))
        g = GlobalSettings(intake=s.intake, detect=s.detect, print=s.print, device=s.device, auto_ingest=cur.auto_ingest, last_preset_id=cur.last_preset_id)
        store = Store(self.db)
        base = self.get_preset()
        data = Preset(correct=s.correct, layout=s.layout, arrange=base.arrange).model_dump(mode="json")
        default = store.default_preset()
        if default is None:
            store.add_preset("既定", data, builtin=True)
        else:
            store.update_preset(default["id"], None, data)
        self.save_global(g)
