"""データ置き場と設定ファイルの入出力（仕様 2 節）。"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .core.settings import Settings


class Home:
    def __init__(self, root: str | Path | None = None, config: str | Path | None = None):
        if root is None:
            root = os.environ.get("PRINT_EDIT_HOME") or "~/PrintEdit"
        self.root = Path(root).expanduser().resolve()
        self.config_path = Path(config).expanduser() if config else self.root / "config.json"

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

    def load_settings(self) -> Settings:
        if not self.config_path.exists():
            return Settings()
        return Settings.model_validate_json(self.config_path.read_text(encoding="utf-8"))

    def save_settings(self, s: Settings) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.config_path.with_name(self.config_path.name + ".tmp")
        tmp.write_text(json.dumps(s.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.config_path)
