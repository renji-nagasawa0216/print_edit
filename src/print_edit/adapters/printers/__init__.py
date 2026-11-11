from ...core.settings import Settings
from ..base import Printer
from .lp import LpPrinter
from .pdf_file import PdfFilePrinter


def make_printer(settings: Settings) -> Printer:
    return LpPrinter(settings) if settings.print.output == "lp" else PdfFilePrinter()
