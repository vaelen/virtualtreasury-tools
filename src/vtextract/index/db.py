# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1


class Fts5Unavailable(RuntimeError):
    """The running sqlite3 build lacks the FTS5 extension."""


class SchemaMismatch(RuntimeError):
    """The on-disk index was built by an incompatible schema version."""


def fts5_available() -> bool:
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE VIRTUAL TABLE _probe USING fts5(x)")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        conn.close()


_DDL = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE item (
    isadg_id INTEGER PRIMARY KEY,
    reference_code TEXT,
    title TEXT,
    description TEXT,
    repository TEXT,
    content_begin TEXT, content_end TEXT,
    created_begin TEXT, created_end TEXT,
    path TEXT
);
CREATE TABLE volume (root_id TEXT PRIMARY KEY, label TEXT, reference_code TEXT);
CREATE TABLE page (
    root_id TEXT, page_key TEXT, has_text INTEGER,
    PRIMARY KEY (root_id, page_key)
);
CREATE TABLE item_volume (
    isadg_id INTEGER, root_id TEXT,
    PRIMARY KEY (isadg_id, root_id)
);
CREATE TABLE item_page (
    isadg_id INTEGER, root_id TEXT, page_key TEXT, role TEXT,
    PRIMARY KEY (isadg_id, root_id, page_key)
);
CREATE TABLE source_file (
    path TEXT PRIMARY KEY, kind TEXT, mtime REAL, size INTEGER
);
CREATE TABLE transcription_map (
    rowid INTEGER PRIMARY KEY, root_id TEXT, page_key TEXT
);
CREATE INDEX ix_item_page_page ON item_page (root_id, page_key);
CREATE VIRTUAL TABLE item_fts USING fts5(title, description);
CREATE VIRTUAL TABLE transcription_fts USING fts5(text);
"""


class IndexDB:
    """The single SQL choke point for the index. Owns the connection and schema."""

    def __init__(self, path: Path, *, rebuild: bool = False) -> None:
        if not fts5_available():
            raise Fts5Unavailable(
                "This Python's sqlite3 was built without FTS5; cannot build/query the index."
            )
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if rebuild:
            self._drop_all()
        self._ensure_schema()

    # --- lifecycle ---

    def __enter__(self) -> "IndexDB":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.commit()
        self._conn.close()

    # --- schema ---

    def _drop_all(self) -> None:
        names = [
            r[0]
            for r in self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','index') "
                "AND name NOT LIKE 'sqlite_%'"
            )
        ]
        for name in names:
            self._conn.execute(f"DROP TABLE IF EXISTS {name}")
        self._conn.commit()

    def _ensure_schema(self) -> None:
        has_meta = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'"
        ).fetchone()
        if not has_meta:
            self._conn.executescript(_DDL)
            self.set_meta("schema_version", str(SCHEMA_VERSION))
            self._conn.commit()
            return
        version = self.get_meta("schema_version")
        if version != str(SCHEMA_VERSION):
            raise SchemaMismatch(
                f"index schema version {version!r} != expected {SCHEMA_VERSION}; "
                "run `vtindex build --rebuild`."
            )

    # --- meta ---

    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def get_meta(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None
