from __future__ import annotations

import subprocess
from pathlib import Path

from ...core.settings import Settings
from ..base import PrinterError


class LpPrinter:
    def __init__(self, settings: Settings, runner=subprocess.run):
        self.p = settings.print
        self._run = runner

    def build_command(self, pdf: Path) -> list[str]:
        if not self.p.printer_name.strip():
            # -d 無しの lp は既定プリンタへ実際に印刷されるため、実行前に止める
            raise PrinterError("print.printer_name が空です（lp を実行しません）")
        cmd = ["lp", "-d", self.p.printer_name, "-n", str(self.p.copies)]
        for opt in self.p.lp_options:
            cmd += ["-o", opt]
        cmd.append(str(pdf))
        return cmd

    def send(self, pdf: Path) -> None:
        cmd = self.build_command(pdf)
        try:
            r = self._run(cmd, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as e:
            raise PrinterError(f"lp 実行失敗: {e}") from e
        if r.returncode != 0:
            raise PrinterError(f"lp 失敗 (code {r.returncode}): {r.stderr.strip()}")
