# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

import sqlite3
from pathlib import Path

from vtextract.index.models import VolumeInfo

SCHEMA_VERSION = 3


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


def fts_query(text: str) -> str:
    """Turn user keyword input into a safe FTS5 MATCH expression.

    Each whitespace-delimited token is wrapped as a quoted FTS5 string so that
    apostrophes, commas, parentheses, hyphens, etc. in ordinary words (e.g.
    "O'Brien", "Cork (city)") are matched literally rather than parsed as FTS5
    operators. Tokens combine with implicit AND. Returns "" when there are no
    tokens.
    """
    tokens = text.split()
    return " ".join('"' + t.replace('"', '""') + '"' for t in tokens)


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
    estimated_begin TEXT, estimated_end TEXT, estimated_source TEXT,
    path TEXT
);
CREATE TABLE volume (root_id TEXT PRIMARY KEY, label TEXT, reference_code TEXT, title TEXT);
CREATE TABLE page (
    root_id TEXT, page_key TEXT, ordinal INTEGER, label TEXT, has_text INTEGER,
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
            "content_begin, content_end, created_begin, created_end, "
            "estimated_begin, estimated_end, estimated_source, path) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (item.isadg_id, item.reference_code, item.title, item.description,
             item.repository, item.content_begin, item.content_end,
             item.created_begin, item.created_end,
             item.estimated_begin, item.estimated_end, item.estimated_source,
             item.path),
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
            "INSERT INTO volume (root_id, label, reference_code, title) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(root_id) DO UPDATE SET label=excluded.label, "
            "reference_code=excluded.reference_code, title=excluded.title",
            (volume.root_id, volume.label, volume.reference_code, volume.title),
        )
        # The volume page list is authoritative for page existence + ordinal + label.
        # Clear this volume's ordinals, (re)assign from the list, then prune
        # volume-only rows (has_text=0) no longer listed. Transcription-backed rows
        # survive with their ordering cleared if dropped from the list.
        self._conn.execute(
            "UPDATE page SET ordinal=NULL, label=NULL WHERE root_id=?", (volume.root_id,)
        )
        for page in volume.pages:
            self._conn.execute(
                "INSERT INTO page (root_id, page_key, ordinal, label, has_text) "
                "VALUES (?, ?, ?, ?, 0) "
                "ON CONFLICT(root_id, page_key) DO UPDATE SET "
                "ordinal=excluded.ordinal, label=excluded.label",
                (volume.root_id, page.page_key, page.ordinal, page.label),
            )
        self._conn.execute(
            "DELETE FROM page WHERE root_id=? AND ordinal IS NULL AND has_text=0",
            (volume.root_id,),
        )
        self._set_fingerprint(path, "volume", mtime, size)

    # --- transcription (page) upsert / delete ---

    def upsert_transcription(
        self, root_id: str, page_key: str, text: str, *, fingerprint: tuple[str, float, int]
    ) -> None:
        path, mtime, size = fingerprint
        self._delete_page_fts(root_id, page_key)
        self._conn.execute(
            "INSERT INTO page (root_id, page_key, has_text) VALUES (?, ?, 1) "
            "ON CONFLICT(root_id, page_key) DO UPDATE SET has_text=1",
            (root_id, page_key),
        )
        cur = self._conn.execute("INSERT INTO transcription_fts (text) VALUES (?)", (text,))
        self._conn.execute(
            "INSERT INTO transcription_map (rowid, root_id, page_key) VALUES (?, ?, ?)",
            (cur.lastrowid, root_id, page_key),
        )
        self._set_fingerprint(path, "transcription", mtime, size)

    def _delete_page_fts(self, root_id: str, page_key: str) -> None:
        """Remove FTS data for a page (transcription_fts + transcription_map).

        Does NOT touch the page row itself — callers are responsible for that.
        """
        rows = list(self._conn.execute(
            "SELECT rowid FROM transcription_map WHERE root_id=? AND page_key=?",
            (root_id, page_key),
        ))
        for r in rows:
            self._conn.execute("DELETE FROM transcription_fts WHERE rowid=?", (r["rowid"],))
            self._conn.execute("DELETE FROM transcription_map WHERE rowid=?", (r["rowid"],))

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
            # Remove the page row only if it has no volume ordering (no volume indexed it).
            # If a volume owns the row, clearing has_text is sufficient.
            self._conn.execute(
                "DELETE FROM page WHERE root_id=? AND page_key=? AND ordinal IS NULL",
                (root_id, page_key),
            )
            self._conn.execute(
                "UPDATE page SET has_text=0 WHERE root_id=? AND page_key=? AND ordinal IS NOT NULL",
                (root_id, page_key),
            )
        elif kind == "volume":
            root_id = path.split("/")[1]
            self._conn.execute("DELETE FROM volume WHERE root_id=?", (root_id,))
            self._conn.execute(
                "UPDATE page SET ordinal=NULL, label=NULL WHERE root_id=?", (root_id,)
            )
            self._conn.execute(
                "DELETE FROM page WHERE root_id=? AND ordinal IS NULL AND has_text=0",
                (root_id,),
            )
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

    # --- search primitives ---

    def item_fts_search(self, text: str, fields: tuple[str, ...]) -> dict[int, float]:
        """Return {isadg_id: best bm25 score} for title/description FTS matches."""
        cols = [f for f in fields if f in ("title", "description")]
        if not cols:
            return {}
        query = fts_query(text)
        if not query:
            return {}
        match = "{" + " ".join(cols) + "} : " + query
        rows = self._conn.execute(
            "SELECT rowid, bm25(item_fts) AS score FROM item_fts "
            "WHERE item_fts MATCH ?",
            (match,),
        )
        return {r["rowid"]: r["score"] for r in rows}

    def transcription_fts_search(self, text: str) -> list[tuple[str, str, float]]:
        """Return [(root_id, page_key, score)] for transcription FTS matches."""
        query = fts_query(text)
        if not query:
            return []
        rows = self._conn.execute(
            "SELECT tm.root_id AS root_id, tm.page_key AS page_key, "
            "bm25(transcription_fts) AS score FROM transcription_fts "
            "JOIN transcription_map tm ON tm.rowid = transcription_fts.rowid "
            "WHERE transcription_fts MATCH ?",
            (query,),
        )
        return [(r["root_id"], r["page_key"], r["score"]) for r in rows]

    def items_for_pages(
        self, pages: list[tuple[str, str]]
    ) -> dict[int, list[tuple[str, str, str]]]:
        """Map matched (root_id,page_key) pages to the items that reference them.

        Each value is a list of ``(root_id, page_key, role)`` tuples; ``role``
        comes straight from ``item_page.role`` (``"primary"`` or ``"context"``).
        """
        out: dict[int, list[tuple[str, str, str]]] = {}
        for root_id, page_key in pages:
            for r in self._conn.execute(
                "SELECT isadg_id, role FROM item_page WHERE root_id=? AND page_key=?",
                (root_id, page_key),
            ):
                out.setdefault(r["isadg_id"], []).append((root_id, page_key, r["role"]))
        return out

    def filter_items(
        self,
        ids: set[int] | None,
        *,
        date_type: str = "content",
        date_from: str | None = None,
        date_to: str | None = None,
        volume: str | None = None,
    ):
        """Return item rows (as sqlite3.Row) passing the structured filters.

        ids=None means 'all items'. Results are ordered by content_begin asc,
        then isadg_id, for stable filter-only output.
        """
        begin_col = "content_begin" if date_type == "content" else "created_begin"
        end_col = "content_end" if date_type == "content" else "created_end"
        where: list[str] = []
        params: list = []
        if ids is not None:
            if not ids:
                return []
            placeholders = ",".join("?" * len(ids))
            where.append(f"i.isadg_id IN ({placeholders})")
            params.extend(ids)
        if date_to is not None:
            where.append(f"i.{begin_col} IS NOT NULL AND i.{begin_col} <= ?")
            params.append(date_to)
        if date_from is not None:
            where.append(f"i.{end_col} IS NOT NULL AND i.{end_col} >= ?")
            params.append(date_from)
        if volume is not None:
            where.append(
                "EXISTS (SELECT 1 FROM item_volume iv "
                "WHERE iv.isadg_id = i.isadg_id AND iv.root_id = ?)"
            )
            params.append(volume)
        sql = "SELECT * FROM item i"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY i.content_begin IS NULL, i.content_begin, i.isadg_id"
        return list(self._conn.execute(sql, params))

    def volumes(self) -> list[VolumeInfo]:
        """Return VolumeInfo for all volumes, ordered by root_id."""
        rows = self._conn.execute(
            "SELECT v.root_id, v.label, v.reference_code, v.title, "
            "(SELECT COUNT(DISTINCT iv.isadg_id) FROM item_volume iv "
            " WHERE iv.root_id = v.root_id) AS item_count "
            "FROM volume v ORDER BY v.root_id"
        )
        return [
            VolumeInfo(
                root_id=r["root_id"], label=r["label"],
                reference_code=r["reference_code"], item_count=r["item_count"],
                title=r["title"],
            )
            for r in rows
        ]

    def volume(self, root_id: str) -> dict | None:
        """Return one volume row as a dict, or None."""
        row = self._conn.execute(
            "SELECT root_id, label, reference_code, title FROM volume WHERE root_id=?",
            (root_id,),
        ).fetchone()
        return dict(row) if row else None

    def get_page(self, root_id: str, page_key: str) -> dict | None:
        """Return one page row (root_id, page_key, ordinal, label, has_text) or None."""
        row = self._conn.execute(
            "SELECT root_id, page_key, ordinal, label, has_text FROM page "
            "WHERE root_id=? AND page_key=?",
            (root_id, page_key),
        ).fetchone()
        return dict(row) if row else None

    def page_at_ordinal(self, root_id: str, ordinal: int | None) -> dict | None:
        """Return the page at a given 1-based ordinal in a volume, or None."""
        if ordinal is None:
            return None
        row = self._conn.execute(
            "SELECT root_id, page_key, ordinal, label, has_text FROM page "
            "WHERE root_id=? AND ordinal=?",
            (root_id, ordinal),
        ).fetchone()
        return dict(row) if row else None

    def pages(self, root_id: str) -> list[dict]:
        """Return every indexed page in a volume, ordered by ordinal.

        Pages whose ordinal is NULL (transcription-backed rows whose volume.json
        no longer lists them) are excluded — the contract is "every page of
        this volume" and a volumeless page has no volume position.
        """
        rows = self._conn.execute(
            "SELECT page_key, ordinal, label FROM page "
            "WHERE root_id=? AND ordinal IS NOT NULL ORDER BY ordinal",
            (root_id,),
        ).fetchall()
        return [
            {"root_id": root_id, "page_key": r["page_key"],
             "ordinal": r["ordinal"], "label": r["label"]}
            for r in rows
        ]

    def item(self, isadg_id: int) -> dict | None:
        """Return one item's header + its matched-pages list (with role), or None."""
        row = self._conn.execute(
            "SELECT isadg_id, reference_code, title, description, repository, "
            "content_begin, content_end, created_begin, created_end, "
            "estimated_begin, estimated_end, estimated_source "
            "FROM item WHERE isadg_id = ?",
            (isadg_id,),
        ).fetchone()
        if row is None:
            return None
        pages = [
            {"root_id": pr["root_id"], "page_key": pr["page_key"], "role": pr["role"]}
            for pr in self._conn.execute(
                "SELECT ip.root_id AS root_id, ip.page_key AS page_key, "
                "ip.role AS role FROM item_page ip "
                "LEFT JOIN page p ON p.root_id = ip.root_id "
                "AND p.page_key = ip.page_key "
                "WHERE ip.isadg_id = ? "
                "ORDER BY p.ordinal IS NULL, p.ordinal, ip.root_id, ip.page_key",
                (isadg_id,),
            )
        ]
        return {
            "isadg_id": row["isadg_id"],
            "reference_code": row["reference_code"],
            "title": row["title"],
            "description": row["description"],
            "repository": row["repository"],
            "content_begin": row["content_begin"],
            "content_end": row["content_end"],
            "created_begin": row["created_begin"],
            "created_end": row["created_end"],
            "estimated_begin": row["estimated_begin"],
            "estimated_end": row["estimated_end"],
            "estimated_source": row["estimated_source"],
            "pages": pages,
        }
