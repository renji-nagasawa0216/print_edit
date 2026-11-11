from __future__ import annotations

import sys
import time
from pathlib import Path


class FolderSource:
    """inbox を走査し、stable_wait_s の間サイズ・mtime が変わらないファイルだけ返す。
    変わったファイルは同じ呼び出しの中で再確認し、待ちの合計が max_wait_s に達したら諦める（stderr に理由）。"""

    def __init__(self, inbox: Path, extensions: list[str], stable_wait_s: float, sleep=time.sleep, max_wait_s: float = 30.0):
        self.inbox = Path(inbox)
        self.exts = {"." + e.lower().lstrip(".") for e in extensions}
        self.wait = stable_wait_s
        self.max_wait = max_wait_s
        self._sleep = sleep

    def _candidates(self) -> dict[Path, tuple[int, int]]:
        out: dict[Path, tuple[int, int]] = {}
        if not self.inbox.is_dir():
            return out
        for p in sorted(self.inbox.iterdir()):
            if p.name.startswith(".") or not p.is_file() or p.suffix.lower() not in self.exts:
                continue
            try:
                st = p.stat()
                out[p] = (st.st_size, st.st_mtime_ns)
            except OSError:
                continue
        return out

    def poll(self) -> list[Path]:
        prev = self._candidates()
        if not prev:
            return []
        if self.wait <= 0:
            cur = self._candidates()
            return [p for p, sig in prev.items() if sig[0] > 0 and cur.get(p) == sig]
        ready: list[Path] = []
        waited = 0.0
        while prev:
            self._sleep(self.wait)
            waited += self.wait
            cur = self._candidates()
            ready += [p for p, sig in prev.items() if sig[0] > 0 and cur.get(p) == sig]
            changing = {p: cur[p] for p, sig in prev.items() if p in cur and cur[p] != sig}
            if waited >= self.max_wait:
                for p in changing:
                    print(f"skip: {p.name} は {self.max_wait:g} 秒待ってもサイズが安定しないため今回は処理しません", file=sys.stderr)
                break
            prev = changing
        return sorted(ready)
