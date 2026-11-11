"""コマンド print-edit（仕様 6 節）。出力形式は検証の接点なので変えない。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core.settings import Settings, capacity_of
from .home import Home
from .pipeline import Pipeline, detect_to_dir, impose_files


def _dump(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--home", default=argparse.SUPPRESS, help="PRINT_EDIT_HOME を上書き")
    common.add_argument("--config", default=argparse.SUPPRESS, help="設定 JSON のパス")
    p = argparse.ArgumentParser(prog="print-edit", parents=[common])
    p.set_defaults(home=None, config=None)
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("detect", parents=[common])
    d.add_argument("image")
    d.add_argument("--out", required=True)
    d.add_argument("--dpi", type=int, default=None)

    i = sub.add_parser("impose", parents=[common])
    i.add_argument("cards", nargs="+")
    i.add_argument("--out", required=True)

    sub.add_parser("capacity", parents=[common])
    sub.add_parser("ingest", parents=[common])

    sv = sub.add_parser("serve", parents=[common])
    sv.add_argument("--port", type=int, default=8765)

    c = sub.add_parser("config", parents=[common])
    c.add_argument("action", choices=["show", "schema", "path"])
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        return _run(args)
    except SystemExit:
        raise
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def _run(a) -> int:
    home = Home(a.home, a.config)
    if a.cmd == "config" and a.action == "schema":
        _dump(Settings.model_json_schema())
        return 0
    if a.cmd == "config" and a.action == "path":
        print(home.config_path)
        return 0
    s = home.load_settings()
    if a.cmd == "config":
        _dump(s.model_dump(mode="json"))
    elif a.cmd == "capacity":
        _dump(capacity_of(s).to_dict())
    elif a.cmd == "detect":
        _dump(detect_to_dir(Path(a.image), Path(a.out), s, a.dpi))
    elif a.cmd == "impose":
        files = [Path(f) for f in a.cards]
        missing = [str(f) for f in files if not f.is_file()]
        if missing:
            raise FileNotFoundError(f"カード画像が見つかりません: {', '.join(missing)}")
        impose_files(files, Path(a.out), s)
    elif a.cmd == "ingest":
        results = Pipeline(home, s).ingest_once()
        _dump(results)
        if any(r.get("status") == "error" for r in results):
            return 1
    elif a.cmd == "serve":
        import uvicorn

        from .api.app import create_app

        home.ensure(s)
        uvicorn.run(create_app(home), host="127.0.0.1", port=a.port)
    return 0
