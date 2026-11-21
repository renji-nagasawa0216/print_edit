"""SQLite 保存（仕様 8 節）。"""
from __future__ import annotations

import json
import shutil
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
  image_path TEXT, width_px INTEGER, height_px INTEGER,
  reg TEXT NOT NULL DEFAULT 'pending', name TEXT, migrated INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS cards_job ON cards(job_id);
CREATE TABLE IF NOT EXISTS sheets(
  id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, pdf_path TEXT, status TEXT, created_at TEXT, error TEXT, snapshot TEXT);
CREATE TABLE IF NOT EXISTS sheet_cards(
  sheet_id INTEGER, card_id INTEGER, slot INTEGER, PRIMARY KEY(sheet_id, slot));
CREATE TABLE IF NOT EXISTS presets(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, data TEXT NOT NULL, builtin INTEGER NOT NULL DEFAULT 0,
  created_at TEXT);
"""

# cards.reg: pending=登録待ち / master=名刺マスタ / deleted=マスタから削除（論理削除）/ discarded=登録待ちで破棄
REG_PENDING, REG_MASTER, REG_DELETED, REG_DISCARDED = "pending", "master", "deleted", "discarded"
NAME_MAX = 100
PRESET_NAME_MAX = 50
CARD_SELECT = (
    "SELECT c.*, j.source_name AS source_name, j.created_at AS job_created_at,"
    " EXISTS(SELECT 1 FROM sheet_cards sc WHERE sc.card_id=c.id) AS used FROM cards c LEFT JOIN jobs j ON j.id=c.job_id"
)
CARD_ORDER = " ORDER BY j.created_at, j.rowid, c.idx, c.id"


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _migrate(self) -> None:
        """旧 DB（cards に reg 列が無い）を 1 回だけ新体系へ移す。移行前に db.sqlite3 のコピーを作り、変更は 1 トランザクション。
        破棄済み（discarded）以外は登録待ち（移行分）へ、discarded は破棄のまま。冪等: reg 列があれば何もしない。"""
        con = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        try:
            def cols(t: str) -> list[str]:
                return [r[1] for r in con.execute(f"PRAGMA table_info({t})").fetchall()]

            if not cols("cards") or "reg" in cols("cards"):
                return
            bak = self.path.with_name(self.path.name + ".bak")
            n = 1
            while bak.exists():
                n += 1
                bak = self.path.with_name(f"{self.path.name}.bak{n}")
            shutil.copy2(self.path, bak)
            con.execute("BEGIN IMMEDIATE")
            try:
                if "reg" not in cols("cards"):  # 別プロセスが先に移行していたら何もしない
                    con.execute("ALTER TABLE cards ADD COLUMN reg TEXT NOT NULL DEFAULT 'pending'")
                    con.execute("ALTER TABLE cards ADD COLUMN name TEXT")
                    con.execute("ALTER TABLE cards ADD COLUMN migrated INTEGER NOT NULL DEFAULT 0")
                    if cols("sheets") and "snapshot" not in cols("sheets"):
                        con.execute("ALTER TABLE sheets ADD COLUMN snapshot TEXT")
                    con.execute("UPDATE cards SET reg='discarded' WHERE status='discarded'")
                    con.execute("UPDATE cards SET reg='pending', migrated=1 WHERE status!='discarded'")
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        finally:
            con.close()

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

    def last_ingest_at(self) -> str | None:
        rows = self._q("SELECT created_at FROM jobs ORDER BY julianday(created_at) DESC, rowid DESC LIMIT 1")
        return rows[0]["created_at"] if rows else None

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
        if "used" in r:
            r["used"] = bool(r["used"])
        if "migrated" in r:
            r["migrated"] = bool(r["migrated"])
        return r

    def list_cards(self, job_id: str | None = None, status: str | None = None, reg: str | None = None, q: str | None = None) -> list[dict]:
        """reg: 登録状態の絞り込み。q: 名前・元ファイル名・取込日（YYYY-MM-DD）の部分一致（OR・英字の大小無視）。
        並びは取込日時の古い順・同じ取り込み内は idx 順。"""
        where, args = [], []
        if job_id:
            where.append("c.job_id=?")
            args.append(job_id)
        if status:
            where.append("c.status=?")
            args.append(status)
        if reg:
            where.append("c.reg=?")
            args.append(reg)
        if q:
            where.append(
                "(instr(lower(coalesce(c.name,'')), lower(?))>0 OR instr(lower(coalesce(j.source_name,'')), lower(?))>0"
                " OR instr(substr(coalesce(j.created_at,''),1,10), ?)>0)"
            )
            args += [q, q, q]
        sql = CARD_SELECT + (" WHERE " + " AND ".join(where) if where else "") + CARD_ORDER
        return [self._card(r) for r in self._q(sql, args)]

    def get_card(self, id: int) -> dict | None:
        r = self._q(CARD_SELECT + " WHERE c.id=?", (id,))
        return self._card(r[0]) if r else None

    def set_card_status(self, id: int, status: str) -> None:
        self._x("UPDATE cards SET status=? WHERE id=?", (status, id))

    def change_reg(self, id: int, from_reg: str, to_reg: str) -> bool:
        """reg が from_reg のときだけ to_reg へ変える（原子的）。取れたら True。登録と破棄の同時操作は先に通った方だけ有効。"""
        with self._conn() as c:
            return c.execute("UPDATE cards SET reg=? WHERE id=? AND reg=?", (to_reg, id, from_reg)).rowcount == 1

    def set_card_name(self, id: int, name: str | None) -> None:
        self._x("UPDATE cards SET name=? WHERE id=?", (name, id))

    # presets（既定値）
    @staticmethod
    def _preset(r: dict) -> dict:
        return {"id": r["id"], "name": r["name"], "builtin": bool(r["builtin"]), "data": json.loads(r["data"])}

    def list_presets(self) -> list[dict]:
        return [self._preset(r) for r in self._q("SELECT * FROM presets ORDER BY id")]

    def get_preset(self, id: int) -> dict | None:
        r = self._q("SELECT * FROM presets WHERE id=?", (id,))
        return self._preset(r[0]) if r else None

    def default_preset(self) -> dict | None:
        r = self._q("SELECT * FROM presets WHERE builtin=1 ORDER BY id LIMIT 1")
        return self._preset(r[0]) if r else None

    def preset_count(self) -> int:
        return self._q("SELECT COUNT(*) AS n FROM presets")[0]["n"]

    def add_preset(self, name: str, data: dict, builtin: bool = False) -> int:
        return self._x("INSERT INTO presets(name,data,builtin,created_at) VALUES(?,?,?,?)", (name, json.dumps(data, ensure_ascii=False), int(builtin), now()))

    def update_preset(self, id: int, name: str | None, data: dict | None) -> None:
        with self._conn() as c:
            if name is not None:
                c.execute("UPDATE presets SET name=? WHERE id=?", (name, id))
            if data is not None:
                c.execute("UPDATE presets SET data=? WHERE id=?", (json.dumps(data, ensure_ascii=False), id))

    def delete_preset(self, id: int) -> None:
        self._x("DELETE FROM presets WHERE id=? AND builtin=0", (id,))

    # sheets
    def add_sheet(
        self, job_id: str | None, pdf_path: str, status: str, card_ids: list[int], slots: dict[int, int] | None = None, snapshot: dict | None = None
    ) -> int:
        """slots（スロット番号→card_id）があればその配置で、無ければ card_ids を 1 番から順に置く。"""
        placed = slots if slots is not None else {i + 1: cid for i, cid in enumerate(card_ids)}
        with self._conn() as c:
            sid = c.execute(
                "INSERT INTO sheets(job_id,pdf_path,status,created_at,snapshot) VALUES(?,?,?,?,?)",
                (job_id, pdf_path, status, now(), json.dumps(snapshot, ensure_ascii=False) if snapshot is not None else None),
            ).lastrowid
            c.executemany("INSERT INTO sheet_cards(sheet_id,card_id,slot) VALUES(?,?,?)", [(sid, cid, slot) for slot, cid in sorted(placed.items())])
            return sid

    def replace_sheet_content(self, id: int, slots: dict[int, int], snapshot: dict) -> None:
        """上書き保存: 同じシート（同 id・同 PDF パス）の配置と作成時設定だけを置き換える。"""
        with self._conn() as c:
            c.execute("DELETE FROM sheet_cards WHERE sheet_id=?", (id,))
            c.executemany("INSERT INTO sheet_cards(sheet_id,card_id,slot) VALUES(?,?,?)", [(id, cid, slot) for slot, cid in sorted(slots.items())])
            c.execute("UPDATE sheets SET snapshot=? WHERE id=?", (json.dumps(snapshot, ensure_ascii=False), id))

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

    def history(self) -> list[dict]:
        """履歴一覧: ジョブと、job_id の無いシート（kind='pdf'）を作成日時の新しい順に混ぜる。"""
        rows = [{"kind": "job", **j} for j in self.list_jobs()]
        for s in self._q("SELECT * FROM sheets WHERE job_id IS NULL ORDER BY created_at DESC, id DESC"):
            s["cards"] = self._q("SELECT card_id, slot FROM sheet_cards WHERE sheet_id=? ORDER BY slot", (s["id"],))
            s.pop("snapshot", None)
            rows.append({"kind": "pdf", **s})
        rows.sort(key=lambda r: r["created_at"] or "", reverse=True)
        return rows

    def sheet_card_ids(self, sheet_id: int) -> list[int]:
        return [r["card_id"] for r in self._q("SELECT DISTINCT card_id FROM sheet_cards WHERE sheet_id=? ORDER BY card_id", (sheet_id,))]

    def get_sheet(self, id: int) -> dict | None:
        r = self._q("SELECT * FROM sheets WHERE id=?", (id,))
        if not r:
            return None
        r[0]["snapshot"] = json.loads(r[0]["snapshot"]) if r[0].get("snapshot") else None
        return r[0]

    def sheet_slots(self, sheet_id: int) -> dict[int, int]:
        return {r["slot"]: r["card_id"] for r in self._q("SELECT card_id, slot FROM sheet_cards WHERE sheet_id=? ORDER BY slot", (sheet_id,))}

    def list_sheets(self, job_id: str) -> list[dict]:
        rows = self._q("SELECT id, job_id, pdf_path, status, created_at, error, (snapshot IS NOT NULL) AS has_snapshot FROM sheets WHERE job_id=? ORDER BY id", (job_id,))
        for r in rows:
            r["has_snapshot"] = bool(r["has_snapshot"])
            r["cards"] = self._q("SELECT card_id, slot FROM sheet_cards WHERE sheet_id=? ORDER BY slot", (r["id"],))
        return rows

    def count_sheets(self, job_id: str) -> int:
        return self._q("SELECT COUNT(*) AS n FROM sheets WHERE job_id=?", (job_id,))[0]["n"]
