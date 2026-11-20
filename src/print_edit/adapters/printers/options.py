"""プリンタが持つ印刷オプションの一覧を読み取る（lpstat -e / lpoptions -p <名前> -l。どちらも印刷はしない）。"""
from __future__ import annotations

import subprocess
from urllib.parse import quote


def parse_lpoptions(text: str) -> list[dict]:
    """`lpoptions -l` の出力を [{key, label, default, choices}] にする。`*` が既定値。Custom.* は選択肢に含めない。"""
    out = []
    for line in text.splitlines():
        head, sep, rest = line.partition(": ")
        if not sep or "/" not in head:
            continue
        key, _, label = head.partition("/")
        choices, default = [], None
        for tok in rest.split():
            star = tok.startswith("*")
            v = tok[1:] if star else tok
            if not v or v.startswith("Custom."):
                continue
            choices.append(v)
            if star:
                default = v
        if key and choices:
            out.append({"key": key, "label": label, "default": default, "choices": choices})
    return out


_QUALITY_NAMES = {"3": "draft（3）", "4": "normal（4）", "5": "high（5）"}
_ENUM = {"draft": "3", "normal": "4", "high": "5"}
_CUPSD_SOCKET = "ipp://%2Fprivate%2Fvar%2Frun%2Fcupsd/printers/"
_IPP_TEST = "/usr/share/cups/ipptool/get-printer-attributes.test"


def parse_ipp_quality(text: str) -> dict | None:
    """ipptool の出力から print-quality-supported / default を読み、lp -o print-quality=3/4/5 の選択肢にする。無ければ None。"""
    sup, dflt = [], None
    for line in text.splitlines():
        head, sep, val = line.strip().partition(" = ")
        if not sep:
            continue
        name = head.split(" ")[0]
        if name == "print-quality-supported":
            sup = [_ENUM[v.strip()] for v in val.split(",") if v.strip() in _ENUM]
        elif name == "print-quality-default":
            dflt = _ENUM.get(val.strip())
    if not sup:
        return None
    return {"key": "print-quality", "label": "画質（AirPrint）", "default": dflt, "choices": sup, "choice_labels": {c: _QUALITY_NAMES[c] for c in sup}}


def printer_options(name: str, runner=subprocess.run) -> dict:
    """{printer, options, error}。失敗しても例外にせず error に理由を入れる（画面を壊さない）。名前は lpstat -e の一覧にあるものだけ。"""
    name = (name or "").strip()
    if not name:
        return {"printer": name, "options": [], "error": "プリンタ名が空です"}
    try:
        names = runner(["lpstat", "-e"], capture_output=True, text=True, timeout=10)
        if names.returncode != 0 or name not in names.stdout.split():
            return {"printer": name, "options": [], "error": f"プリンタ「{name}」が見つかりません"}
        r = runner(["lpoptions", "-p", name, "-l"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as e:
        return {"printer": name, "options": [], "error": f"取得に失敗しました: {e}"}
    if r.returncode != 0:
        return {"printer": name, "options": [], "error": f"取得に失敗しました (code {r.returncode}): {r.stderr.strip()}"}
    options = parse_lpoptions(r.stdout)
    # AirPrint のキューは画質を IPP の print-quality で受ける（PPD の cupsPrintQuality とは別。取れなければ付けない）
    try:
        q = runner(["ipptool", "-tv", _CUPSD_SOCKET + quote(name, safe=""), _IPP_TEST], capture_output=True, text=True, timeout=10)
        iq = parse_ipp_quality(q.stdout) if q.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        iq = None
    if iq:
        options.insert(0, iq)
    return {"printer": name, "options": options, "error": ""}
