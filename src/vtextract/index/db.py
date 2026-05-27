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

    # --- fingerprints ---

    def fingerprints(self) -> dict[str, tuple[float, int]]:
        return {
            r["path"]: (r["mtime"], r["size"])
            for r in self._conn.execute("SELECT path, mtime, size FROM source_file")
        }

    def _set_fingerprint(self, path: str, kind: str, mtime: float, size: int) -> None:
        self._conn.execute(
            "INSERT INTO source_file (path, kind, mtime, size) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(path) DO UPDATE SET kind=excluded.kind, "
            "mtime=excluded.mtime, size=excluded.size",
            (path, kind, mtime, size),
        )

    # --- item upsert / delete ---

    def upsert_item(self, item, *, fingerprint: tuple[str, float, int]) -> None:
        path, mtime, size = fingerprint
        self._delete_item_rows(item.isadg_id)
        self._conn.execute(
            "INSERT INTO item (isadg_id, reference_code, title, description, repository, "
            "content_begin, content_end, created_begin, created_end, path) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (item.isadg_id, item.reference_code, item.title, item.description,
             item.repository, item.content_begin, item.content_end,
             item.created_begin, item.created_end, item.path),
        )
        self._conn.execute(
            "INSERT INTO item_fts (rowid, title, description) VALUES (?, ?, ?)",
            (item.isadg_id, item.title, item.description),
        )
        for root_id in item.volumes:
            self._conn.execute(
                "INSERT OR IGNORE INTO item_volume (isadg_id, root_id) VALUES (?, ?)",
                (item.isadg_id, root_id),
            )
        for page in item.pages:
            self._conn.execute(
                "INSERT OR IGNORE INTO item_page (isadg_id, root_id, page_key, role) "
                "VALUES (?, ?, ?, ?)",
                (item.isadg_id, page.root_id, page.page_key, page.role),
            )
        self._set_fingerprint(path, "item", mtime, size)

    def _delete_item_rows(self, isadg_id: int) -> None:
        self._conn.execute("DELETE FROM item WHERE isadg_id=?", (isadg_id,))
        self._conn.execute("DELETE FROM item_fts WHERE rowid=?", (isadg_id,))
        self._conn.execute("DELETE FROM item_volume WHERE isadg_id=?", (isadg_id,))
        self._conn.execute("DELETE FROM item_page WHERE isadg_id=?", (isadg_id,))

    # --- volume upsert ---

    def upsert_volume(self, volume, *, fingerprint: tuple[str, float, int]) -> None:
        path, mtime, size = fingerprint
        self._conn.execute(
            "INSERT INTO volume (root_id, label, reference_code) VALUES (?, ?, ?) "
            "ON CONFLICT(root_id) DO UPDATE SET label=excluded.label, "
            "reference_code=excluded.reference_code",
            (volume.root_id, volume.label, volume.reference_code),
        )
        self._set_fingerprint(path, "volume", mtime, size)

    # --- transcription (page) upsert / delete ---

    def upsert_transcription(
        self, root_id: str, page_key: str, text: str, *, fingerprint: tuple[str, float, int]
    ) -> None:
        path, mtime, size = fingerprint
        self._delete_page_fts(root_id, page_key)
        self._conn.execute(
            "INSERT OR REPLACE INTO page (root_id, page_key, has_text) VALUES (?, ?, 1)",
            (root_id, page_key),
        )
        cur = self._conn.execute("INSERT INTO transcription_fts (text) VALUES (?)", (text,))
        self._conn.execute(
            "INSERT INTO transcription_map (rowid, root_id, page_key) VALUES (?, ?, ?)",
            (cur.lastrowid, root_id, page_key),
        )
        self._set_fingerprint(path, "transcription", mtime, size)

    def _delete_page_fts(self, root_id: str, page_key: str) -> None:
        rows = list(self._conn.execute(
            "SELECT rowid FROM transcription_map WHERE root_id=? AND page_key=?",
            (root_id, page_key),
        ))
        for r in rows:
            self._conn.execute("DELETE FROM transcription_fts WHERE rowid=?", (r["rowid"],))
            self._conn.execute("DELETE FROM transcription_map WHERE rowid=?", (r["rowid"],))
        self._conn.execute(
            "DELETE FROM page WHERE root_id=? AND page_key=?", (root_id, page_key)
        )

    # --- generic source deletion (used by build prune) ---

    def delete_source(self, path: str) -> None:
        row = self._conn.execute(
            "SELECT kind FROM source_file WHERE path=?", (path,)
        ).fetchone()
        if row is None:
            return
        kind = row["kind"]
        if kind == "item":
            isadg_id = int(path.split("/")[1])
            self._delete_item_rows(isadg_id)
        elif kind == "transcription":
            # path = pages/<root_id>/<page_key>.txt ; page_key already ends in .jpg
            parts = path.split("/")
            root_id = parts[1]
            page_key = parts[2][: -len(".txt")]
            self._delete_page_fts(root_id, page_key)
        elif kind == "volume":
            root_id = path.split("/")[1]
            self._conn.execute("DELETE FROM volume WHERE root_id=?", (root_id,))
        self._conn.execute("DELETE FROM source_file WHERE path=?", (path,))

    # --- counts ---

    def counts(self) -> dict[str, int]:
        # Keys: items, volumes, pages, item_volume, item_page, source_files.
        names = ["item", "volume", "page", "item_volume", "item_page", "source_file"]
        plural = {"item": "items", "volume": "volumes", "page": "pages",
                  "source_file": "source_files"}
        out = {}
        for name in names:
            key = plural.get(name, name)
            out[key] = self._conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        return out
