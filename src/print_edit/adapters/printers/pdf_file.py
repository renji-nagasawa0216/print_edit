from __future__ import annotations

from pathlib import Path


class PdfFilePrinter:
    """PDF を jobs/<id>/sheets/ に置く時点で出力完了。送る処理は無い。"""

    def send(self, pdf: Path) -> None:
        return None
