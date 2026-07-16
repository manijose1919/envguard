"""SQLite persistence for scan history.

Each scan run produces one `scans` row and N `findings` rows. The database
lives in the scanned project's root as `.envguard.db` by default so history
travels with the repo checkout (and is trivially gitignored).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT    NOT NULL,
    project_dir TEXT    NOT NULL,
    files_scanned INTEGER NOT NULL,
    refs_found  INTEGER NOT NULL,
    keys_declared INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS findings (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id   INTEGER NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    kind      TEXT    NOT NULL CHECK (kind IN ('MISSING','UNUSED','DRIFT','EMPTY')),
    severity  TEXT    NOT NULL CHECK (severity IN ('error','warning','info')),
    key       TEXT    NOT NULL,
    detail    TEXT    NOT NULL,
    locations TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_findings_scan ON findings(scan_id);
CREATE INDEX IF NOT EXISTS idx_findings_key  ON findings(key);
"""


@dataclass(frozen=True)
class Finding:
    kind: str        # MISSING | UNUSED | DRIFT | EMPTY
    severity: str    # error | warning | info
    key: str
    detail: str
    locations: tuple[str, ...] = ()


class Store:
    """Single-threaded connection wrapper. Not thread-safe: the HTTP server
    must open a fresh Store per request rather than sharing one instance."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def save_scan(
        self,
        project_dir: str,
        files_scanned: int,
        refs_found: int,
        keys_declared: int,
        findings: list[Finding],
    ) -> int:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO scans (created_at, project_dir, files_scanned,"
                " refs_found, keys_declared) VALUES (?,?,?,?,?)",
                (now, project_dir, files_scanned, refs_found, keys_declared),
            )
            scan_id = cur.lastrowid
            self._conn.executemany(
                "INSERT INTO findings (scan_id, kind, severity, key, detail,"
                " locations) VALUES (?,?,?,?,?,?)",
                [
                    (scan_id, f.kind, f.severity, f.key, f.detail,
                     "\n".join(f.locations))
                    for f in findings
                ],
            )
        return scan_id

    def list_scans(self, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT s.*,
                   COALESCE(SUM(f.severity='error'), 0)   AS errors,
                   COALESCE(SUM(f.severity='warning'), 0) AS warnings,
                   COALESCE(SUM(f.severity='info'), 0)    AS infos
            FROM scans s LEFT JOIN findings f ON f.scan_id = s.id
            GROUP BY s.id ORDER BY s.id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_findings(self, scan_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT kind, severity, key, detail, locations FROM findings"
            " WHERE scan_id = ? ORDER BY CASE severity WHEN 'error' THEN 0"
            " WHEN 'warning' THEN 1 ELSE 2 END, kind, key",
            (scan_id,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["locations"] = d["locations"].split("\n") if d["locations"] else []
            out.append(d)
        return out

    def latest_scan_id(self) -> int | None:
        row = self._conn.execute("SELECT MAX(id) AS m FROM scans").fetchone()
        return row["m"]
