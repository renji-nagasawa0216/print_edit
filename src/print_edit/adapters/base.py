"""入口・出口の抽象（仕様 1 節）。"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol


class Source(Protocol):
    def poll(self) -> list[Path]:
        """今回処理してよい（書き込み完了した）元ファイルを返す。"""


class Printer(Protocol):
    def send(self, pdf: Path) -> None:
        """シート PDF を出口へ送る。失敗は PrinterError。"""


class PrinterError(RuntimeError):
    pass
