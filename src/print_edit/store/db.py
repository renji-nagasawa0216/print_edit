"""SQLite 保存（仕様 8 節）。"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs(
  id TEXT PRIMARY KEY, source_name TEXT, sha256 TEXT, status TEXT, warnings TEXT, dpi INTEGER,
  created_at TEXT, error TEXT);
CREATE INDEX IF NOT EXISTS jobs_sha ON jobs(sha256);
CREATE TABLE IF NOT EXISTS cards(
  id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, idx INTEGER, status TEXT, reasons TEXT,
  corners TEXT, center_x_mm REAL, center_y_mm REAL, long_mm REAL, short_mm REAL, angle_deg REAL,
  image_path TEXT, width_px INTEGER, height_px INTEGER);
CREATE INDEX IF NOT EXISTS cards_job ON cards(job_id);
CREATE TABLE IF NOT EXISTS sheets(
  id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, pdf_path TEXT, status TEXT, created_at TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS sheet_cards(
  sheet_id INTEGER, card_id INTEGER, slot INTEGER, PRIMARY KEY(sheet_id, slot));
"""


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def _q(self, sql: str, args=()) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute(sql, args).fetchall()]

    def _x(self, sql: str, args=()) -> int:
        with self._conn() as c:
            return c.execute(sql, args).lastrowid

    # jobs
    def find_done_job(self, sha256: str) -> dict | None:
        r = self._q("SELECT * FROM jobs WHERE sha256=? AND status!='error' ORDER BY created_at LIMIT 1", (sha256,))
        return self._job(r[0]) if r else None

    def add_job(self, id, source_name, sha256, status, warnings, dpi, error=None) -> None:
        self._x(
            "INSERT INTO jobs(id,source_name,sha256,status,warnings,dpi,created_at,error) VALUES(?,?,?,?,?,?,?,?)",
            (id, source_name, sha256, status, json.dumps(warnings), dpi, now(), error),
        )

    @staticmethod
    def _job(r: dict) -> dict:
        r["warnings"] = json.loads(r["warnings"] or "[]")
        return r

    def list_jobs(self) -> list[dict]:
        rows = self._q(
            "SELECT j.*, (SELECT COUNT(*) FROM cards c WHERE c.job_id=j.id) AS card_count,"
            " (SELECT COUNT(*) FROM sheets s WHERE s.job_id=j.id) AS sheet_count"
            " FROM jobs j ORDER BY created_at DESC, rowid DESC"
        )
        return [self._job(r) for r in rows]

    def get_job(self, id: str) -> dict | None:
        r = self._q("SELECT * FROM jobs WHERE id=?", (id,))
        if not r:
            return None
        job = self._job(r[0])
        job["cards"] = self.list_cards(job_id=id)
        job["sheets"] = self.list_sheets(job_id=id)
        return job

    def set_job_status(self, id: str, status: str, error: str | None = None) -> None:
        self._x("UPDATE jobs SET status=?, error=? WHERE id=?", (status, error, id))

    # cards
    def add_card(self, job_id: str, c: dict, status: str, image_path: str) -> int:
        return self._x(
            "INSERT INTO cards(job_id,idx,status,reasons,corners,center_x_mm,center_y_mm,long_mm,short_mm,angle_deg,"
            "image_path,width_px,height_px) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                job_id, c["index"], status, json.dumps(c["reasons"]), json.dumps(c["corners_px"]),
                c["center_mm"][0], c["center_mm"][1], c["long_mm"], c["short_mm"], c["angle_deg"],
                image_path, c["image_width_px"], c["image_height_px"],
            ),
        )

    @staticmethod
    def _card(r: dict) -> dict:
        r["reasons"] = json.loads(r["reasons"] or "[]")
        r["corners"] = json.loads(r["corners"] or "[]")
        return r

    def list_cards(self, job_id: str | None = None, status: str | None = None) -> list[dict]:
        sql, args, where = "SELECT * FROM cards", [], []
        if job_id:
            where.append("job_id=?")
            args.append(job_id)
        if status:
            where.append("status=?")
            args.append(status)
        if where:
            sql += " WHERE " + " AND ".join(where)
        return [self._card(r) for r in self._q(sql + " ORDER BY job_id, idx, id", args)]

    def get_card(self, id: int) -> dict | None:
        r = self._q("SELECT * FROM cards WHERE id=?", (id,))
        return self._card(r[0]) if r else None

    def set_card_status(self, id: int, status: str) -> None:
        self._x("UPDATE cards SET status=? WHERE id=?", (status, id))

    def pending_cards(self) -> list[dict]:
        rows = self._q(
            "SELECT c.* FROM cards c JOIN jobs j ON j.id=c.job_id WHERE c.status='pending'"
            " ORDER BY j.created_at, j.rowid, c.idx, c.id"
        )
        return [self._card(r) for r in rows]

    # sheets
    def add_sheet(self, job_id: str | None, pdf_path: str, status: str, card_ids: list[int]) -> int:
        with self._conn() as c:
            sid = c.execute(
                "INSERT INTO sheets(job_id,pdf_path,status,created_at) VALUES(?,?,?,?)", (job_id, pdf_path, status, now())
            ).lastrowid
            c.executemany(
                "INSERT INTO sheet_cards(sheet_id,card_id,slot) VALUES(?,?,?)",
                [(sid, cid, i + 1) for i, cid in enumerate(card_ids)],
            )
            return sid

    def set_sheet_status(self, id: int, status: str, error: str | None = None) -> None:
        self._x("UPDATE sheets SET status=?, error=? WHERE id=?", (status, error, id))

    def claim_sheet(self, id: int, from_status: str, to_status: str) -> bool:
        """status が from_status のときだけ to_status へ変える（原子的）。取れたら True。"""
        with self._conn() as c:
            return c.execute("UPDATE sheets SET status=? WHERE id=? AND status=?", (to_status, id, from_status)).rowcount == 1

    def recover_sending(self) -> int:
        """送信中に落ちて残った 'sending' を 'held' に戻す（API 起動時だけ呼ぶ）。"""
        with self._conn() as c:
            return c.execute("UPDATE sheets SET status='held' WHERE status='sending'").rowcount

    def all_sheets(self, status: str | None = None) -> list[dict]:
        sql = "SELECT s.id, s.job_id, s.status, s.created_at, s.pdf_path, (SELECT COUNT(*) FROM sheet_cards sc WHERE sc.sheet_id=s.id) AS card_count FROM sheets s"
        args: tuple = ()
        if status:
            sql += " WHERE s.status=?"
            args = (status,)
        return self._q(sql + " ORDER BY s.created_at, s.id", args)

    def sheet_card_ids(self, sheet_id: int) -> list[int]:
        return [r["card_id"] for r in self._q("SELECT DISTINCT card_id FROM sheet_cards WHERE sheet_id=? ORDER BY card_id", (sheet_id,))]

    def get_sheet(self, id: int) -> dict | None:
        r = self._q("SELECT * FROM sheets WHERE id=?", (id,))
        return r[0] if r else None

    def list_sheets(self, job_id: str) -> list[dict]:
        rows = self._q("SELECT * FROM sheets WHERE job_id=? ORDER BY id", (job_id,))
        for r in rows:
            r["cards"] = self._q("SELECT card_id, slot FROM sheet_cards WHERE sheet_id=? ORDER BY slot", (r["id"],))
        return rows

    def count_sheets(self, job_id: str) -> int:
        return self._q("SELECT COUNT(*) AS n FROM sheets WHERE job_id=?", (job_id,))[0]["n"]

    def sheets_touching_job(self, job_id: str) -> list[dict]:
        """job_id 直下のシートと、そのジョブのカードを含むシート（fill の混在シート）。"""
        rows = self._q(
            "SELECT * FROM sheets WHERE status NOT IN ('held','discarded','sending') AND (job_id=? OR id IN (SELECT sc.sheet_id FROM sheet_cards sc"
            " JOIN cards c ON c.id=sc.card_id WHERE c.job_id=?)) ORDER BY id",
            (job_id, job_id),
        )
        for r in rows:
            r["cards"] = self._q("SELECT card_id, slot FROM sheet_cards WHERE sheet_id=? ORDER BY slot", (r["id"],))
        return rows

    def error_sheet_count_touching_job(self, job_id: str) -> int:
        return self._q(
            "SELECT COUNT(*) AS n FROM sheets WHERE status='error' AND (job_id=? OR id IN"
            " (SELECT sc.sheet_id FROM sheet_cards sc JOIN cards c ON c.id=sc.card_id WHERE c.job_id=?))",
            (job_id, job_id),
        )[0]["n"]
