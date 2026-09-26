# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

"""The single public entry point to the archive index.

``IndexService`` owns one long-lived ``IndexDB`` read connection and the
result-enrichment logic (resolving on-disk page-file paths, assembling page
navigation, mapping rows to typed DTOs). Consumers — the ``vtindex`` CLI and
the ``vtbrowse`` TUI — use this facade and never touch ``db`` / ``query`` /
``builder`` directly, so the SQLite backend can be replaced behind this API.
"""

from __future__ import annotations

import threading
from pathlib import Path

from vtextract.index.builder import INDEX_RELPATH, build as _build, is_stale as _is_stale
from vtextract.index.db import Fts5Unavailable, IndexDB, SchemaMismatch
from vtextract.index.models import (
    BuildStats,
    IndexStats,
    ItemDetail,
    PageEntry,
    PageNav,
    PersonHit,
    SearchHit,
    SearchQuery,
    VolumeHeader,
    VolumeInfo,
)
from vtextract.index.people import people_search as _people_search
from vtextract.index.query import search as _query_search
from vtextract.index.reader import page_files


class IndexUnavailable(RuntimeError):
    """The index cannot be opened: missing, wrong schema, or no FTS5 support."""


def _hit_from_result(archive: Path, r) -> SearchHit:
    matched = []
    for root_id, page_key, role in r.matched_pages:
        pf = page_files(archive, root_id, page_key)
        matched.append(PageEntry(
            root_id=root_id, page_key=page_key,
            image=pf.image, metadata=pf.metadata, transcription=pf.transcription,
            role=role,
        ))
    return SearchHit(
        isadg_id=r.isadg_id, title=r.title, reference_code=r.reference_code,
        repository=r.repository, content_date=r.content_date,
        created_date=r.created_date, estimated_date=r.estimated_date,
        estimated_source=r.estimated_source, matched_fields=r.matched_fields,
        matched_pages=matched, score=r.score, path=r.path,
    )


def _page_entry(archive: Path, row: dict) -> PageEntry:
    pf = page_files(archive, row["root_id"], row["page_key"])
    return PageEntry(
        root_id=row["root_id"], page_key=row["page_key"],
        ordinal=row["ordinal"], label=row["label"],
        image=pf.image, metadata=pf.metadata, transcription=pf.transcription,
        names=pf.names, notes=pf.notes,
    )


class IndexService:
    def __init__(self, archive: Path) -> None:
        self.archive = Path(archive)
        self._db: IndexDB | None = None
        self._open()

    # --- lifecycle ---

    def _open(self) -> None:
        db_path = self.archive / INDEX_RELPATH
        if not db_path.exists():
            raise IndexUnavailable(
                f"no index at {db_path}; run `vtindex build --archive {self.archive}` first."
            )
        try:
            self._db = IndexDB(db_path)
        except (SchemaMismatch, Fts5Unavailable) as exc:
            raise IndexUnavailable(str(exc)) from exc

    def reopen(self) -> None:
        """Close and re-open the read connection (call after a build)."""
        self.close()
        self._open()

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None

    def __enter__(self) -> "IndexService":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def db(self) -> IndexDB:
        # Lazily (re)open if a prior close() nulled the handle; reopen() relies
        # on this so a closed service is transparently usable again.
        if self._db is None:
            self._open()
        assert self._db is not None
        return self._db

    # --- reads ---

    def is_stale(self) -> bool:
        return _is_stale(self.db, self.archive)

    def search(self, q: SearchQuery) -> list[SearchHit]:
        return [_hit_from_result(self.archive, r) for r in _query_search(self.db, q)]

    def people(self, name: str) -> list[PersonHit]:
        return _people_search(self.db, name)

    def volumes(self) -> list[VolumeInfo]:
        return self.db.volumes()

    def pages(self, root_id: str) -> list[PageEntry]:
        return [_page_entry(self.archive, row) for row in self.db.pages(root_id)]

    def page(self, root_id: str, page_key: str) -> PageNav | None:
        current = self.db.get_page(root_id, page_key)
        if current is None:
            return None
        ordinal = current["ordinal"]
        if ordinal is None:
            previous = nxt = None
        else:
            previous = self.db.page_at_ordinal(root_id, ordinal - 1)
            nxt = self.db.page_at_ordinal(root_id, ordinal + 1)
        vol = self.db.volume(root_id) or {"root_id": root_id, "title": None}
        return PageNav(
            volume=VolumeHeader(root_id=root_id, title=vol.get("title")),
            previous=_page_entry(self.archive, previous) if previous else None,
            current=_page_entry(self.archive, current),
            next=_page_entry(self.archive, nxt) if nxt else None,
        )

    def item(self, isadg_id: int) -> ItemDetail | None:
        """Return an item's header + its page links. The page entries are
        link-only (root_id/page_key/role); image/metadata/transcription are left
        None to match the legacy item output — callers needing a page's files
        should use ``page()`` / ``pages()``."""
        row = self.db.item(isadg_id)
        if row is None:
            return None
        pages = [
            PageEntry(root_id=p["root_id"], page_key=p["page_key"], role=p["role"])
            for p in row["pages"]
        ]
        return ItemDetail(
            isadg_id=row["isadg_id"], reference_code=row["reference_code"],
            title=row["title"], description=row["description"],
            repository=row["repository"],
            content_begin=row["content_begin"], content_end=row["content_end"],
            created_begin=row["created_begin"], created_end=row["created_end"],
            estimated_begin=row["estimated_begin"], estimated_end=row["estimated_end"],
            estimated_source=row["estimated_source"], pages=pages,
        )

    def stats(self) -> IndexStats:
        counts = self.db.counts()
        return IndexStats(
            items=counts["items"], volumes=counts["volumes"], pages=counts["pages"],
            schema_version=self.db.get_meta("schema_version"),
            stale=self.is_stale(),
        )

    # --- build (write path) ---

    @staticmethod
    def build(archive, *, rebuild: bool = False, reporter=None,
              cancel: "threading.Event | None" = None) -> BuildStats:
        """(Re)build the index. Static: needs no open read connection (it is the
        operation that *creates* the index). Callers holding a read connection
        should ``reopen()`` afterwards to see new data."""
        return _build(Path(archive), rebuild=rebuild, reporter=reporter, cancel=cancel)
