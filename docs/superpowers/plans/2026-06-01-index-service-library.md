# Index Service Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the "vtbrowse must subprocess vtindex" constraint with a shared in-process `IndexService` library — opened once, reused — that both the `vtindex` CLI and the `vtbrowse` TUI consume, returning typed DTOs.

**Architecture:** A new synchronous `IndexService` (in `src/vtextract/index/service.py`) owns one long-lived `IndexDB` read connection and the result-enrichment logic currently living in `vtindex/cli.py`. The CLI becomes thin presentation over it. The TUI's `IndexClient` is rewritten from a subprocess wrapper into an in-process gateway that runs the service on a single dedicated executor thread for reads and a worker thread for builds, returning the same DTOs. Builds move in-process with a queue-backed progress reporter and cooperative cancellation.

**Tech Stack:** Python 3, SQLite + FTS5, `dataclasses`, `asyncio` + `concurrent.futures.ThreadPoolExecutor`, Textual (TUI), pytest (+ pytest-asyncio, pytest-textual-snapshot), `uv`.

---

## Design reference

Spec: `docs/superpowers/specs/2026-06-01-index-service-library-design.md`.

**Naming note (deviation from spec §2):** the spec calls the page DTO `PageRef`, but `vtextract.tui.bundle` already exports a `PageRef` (a selection key). To avoid a name clash in the TUI, the index DTO is named **`PageEntry`** throughout this plan.

**JSON byte-stability contract:** the `vtindex … --json` output shapes must not change. The exact current shapes (from `cli.py`) are:
- page-files dict: `{"root_id","page_key","image","metadata","transcription"}`
- page-nav/page-list entry: page-files dict **plus** `"ordinal","label"`
- matched-page entry: page-files dict **plus** `"role"`
- search result: `{"isadg_id","title","reference_code","repository","content_date","created_date","estimated_date","estimated_source","matched_fields","matched_pages",[…],"score","path"}`
- item: `{"isadg_id","reference_code","title","description","repository","content_begin","content_end","created_begin","created_end","estimated_begin","estimated_end","estimated_source","pages":[{"root_id","page_key","role"}]}`
- stats: `{"items","volumes","pages","schema_version","stale"}`
- volumes: `{"root_id","label","reference_code","item_count","title"}`
- page nav top-level: `{"volume":{"root_id","title"},"previous",…,"current",…,"next",…}`

The existing `tests/index/test_cli.py` is the guard for these. Do not weaken it.

---

## Task 1: `page_files` helper + `PageFiles` DTO (reader.py)

Move the on-disk page-file resolution out of `cli.py` into `reader.py` (its home for archive-file knowledge), returning a typed `PageFiles`.

**Files:**
- Modify: `src/vtextract/index/models.py` (add `PageFiles`)
- Modify: `src/vtextract/index/reader.py` (add `page_files`)
- Test: `tests/index/test_reader.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/index/test_reader.py`:

```python
def test_page_files_resolves_existing_and_absent(tmp_path):
    from vtextract.index.reader import page_files
    page_dir = tmp_path / "pages" / "volA"
    page_dir.mkdir(parents=True)
    (page_dir / "volA_p1.jpg.txt").write_text("hello")
    pf = page_files(tmp_path, "volA", "volA_p1.jpg")
    assert pf.transcription == str((page_dir / "volA_p1.jpg.txt").resolve())
    assert pf.image is None
    assert pf.metadata is None


def test_page_files_resolves_image_and_metadata(tmp_path):
    from vtextract.index.reader import page_files
    page_dir = tmp_path / "pages" / "volA"
    page_dir.mkdir(parents=True)
    (page_dir / "volA_p1.jpg").write_text("img")
    (page_dir / "volA_p1.jpg.json").write_text("{}")
    pf = page_files(tmp_path, "volA", "volA_p1.jpg")
    assert pf.image == str((page_dir / "volA_p1.jpg").resolve())
    assert pf.metadata == str((page_dir / "volA_p1.jpg.json").resolve())
    assert pf.transcription is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/index/test_reader.py -k page_files -v`
Expected: FAIL with `ImportError` / `cannot import name 'page_files'`.

- [ ] **Step 3: Add the `PageFiles` dataclass**

In `src/vtextract/index/models.py`, after the imports (below `from dataclasses import dataclass, field`), add near the other dataclasses:

```python
@dataclass
class PageFiles:
    """Absolute paths to a page's on-disk artefacts, or None when absent."""

    image: str | None = None
    metadata: str | None = None
    transcription: str | None = None
```

- [ ] **Step 4: Add the `page_files` helper**

In `src/vtextract/index/reader.py`, update the models import line:

```python
from vtextract.index.models import ItemRow, PageFiles, PageLink, VolumePage, VolumeRow
```

and append at the end of the file:

```python
def _resolve(page_dir: Path, name: str) -> str | None:
    path = page_dir / name
    return str(path.resolve()) if path.exists() else None


def page_files(archive: Path, root_id: str, page_key: str) -> PageFiles:
    """Resolve a page's on-disk image/metadata/transcription absolute paths.

    Page store layout (see archive.py): the image is ``{page_key}``, the
    transcription ``{page_key}.txt``, the annotations/metadata ``{page_key}.json``.
    Each field is None when the file is not present.
    """
    page_dir = Path(archive) / "pages" / root_id
    return PageFiles(
        image=_resolve(page_dir, page_key),
        metadata=_resolve(page_dir, f"{page_key}.json"),
        transcription=_resolve(page_dir, f"{page_key}.txt"),
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/index/test_reader.py -k page_files -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add src/vtextract/index/models.py src/vtextract/index/reader.py tests/index/test_reader.py
git commit -m "feat(index): add page_files resolver and PageFiles DTO in reader"
```

---

## Task 2: Public result DTOs (models.py)

Add the typed objects the service returns. Field names match today's JSON keys so TUI consumers convert mechanically (`x["k"]` → `x.k`).

**Files:**
- Modify: `src/vtextract/index/models.py`
- Test: `tests/index/test_models.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/index/test_models.py`:

```python
def test_result_dtos_construct_with_defaults():
    from vtextract.index.models import (
        IndexStats, ItemDetail, PageEntry, PageNav, SearchHit, VolumeHeader,
    )
    e = PageEntry(root_id="volA", page_key="p.jpg")
    assert e.ordinal is None and e.label is None and e.role is None
    assert e.image is None and e.metadata is None and e.transcription is None

    nav = PageNav(volume=VolumeHeader(root_id="volA", title="T"),
                  previous=None, current=e, next=None)
    assert nav.current is e and nav.volume.title == "T"

    hit = SearchHit(
        isadg_id=1, title="t", reference_code="R", repository=None,
        content_date=None, created_date=None, estimated_date=None,
        estimated_source=None, matched_fields=[], matched_pages=[e],
        score=0.0, path="items/1",
    )
    assert hit.matched_pages == [e]

    detail = ItemDetail(
        isadg_id=1, reference_code="R", title="t", description="d",
        repository=None, content_begin=None, content_end=None,
        created_begin=None, created_end=None, estimated_begin=None,
        estimated_end=None, estimated_source=None, pages=[e],
    )
    assert detail.pages == [e]

    stats = IndexStats(items=3, volumes=2, pages=9, schema_version="3", stale=False)
    assert stats.items == 3 and stats.stale is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/index/test_models.py -k result_dtos -v`
Expected: FAIL with `ImportError` (names not defined).

- [ ] **Step 3: Add the DTOs**

Append to `src/vtextract/index/models.py`:

```python
@dataclass
class PageEntry:
    """A page as returned by the index service. Different call sites populate
    different subsets: page-nav and page-list fill ordinal/label/files; matched
    pages and item pages fill role. Field names mirror the legacy JSON keys."""

    root_id: str
    page_key: str
    ordinal: int | None = None
    label: str | None = None
    image: str | None = None
    metadata: str | None = None
    transcription: str | None = None
    role: str | None = None


@dataclass
class VolumeHeader:
    root_id: str
    title: str | None = None


@dataclass
class PageNav:
    volume: VolumeHeader
    previous: PageEntry | None
    current: PageEntry | None
    next: PageEntry | None


@dataclass
class SearchHit:
    isadg_id: int
    title: str
    reference_code: str
    repository: str | None
    content_date: str | None
    created_date: str | None
    estimated_date: str | None
    estimated_source: str | None
    matched_fields: list[str]
    matched_pages: list[PageEntry]
    score: float
    path: str


@dataclass
class ItemDetail:
    isadg_id: int
    reference_code: str | None
    title: str | None
    description: str | None
    repository: str | None
    content_begin: str | None
    content_end: str | None
    created_begin: str | None
    created_end: str | None
    estimated_begin: str | None
    estimated_end: str | None
    estimated_source: str | None
    pages: list[PageEntry]


@dataclass
class IndexStats:
    items: int
    volumes: int
    pages: int
    schema_version: str | None
    stale: bool
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/index/test_models.py -k result_dtos -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/index/models.py tests/index/test_models.py
git commit -m "feat(index): add public result DTOs (PageEntry, PageNav, SearchHit, ItemDetail, IndexStats)"
```

---

## Task 3: Cooperative cancellation in `builder.build`

Add a `cancel` event the build loop checks per file, and guard the prune step so a cancelled build never deletes not-yet-seen sources.

**Files:**
- Modify: `src/vtextract/index/builder.py` (function `build`, lines ~33-80)
- Test: `tests/index/test_builder.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/index/test_builder.py` (it already imports from `vtextract.index.builder`; add these imports at the top of the new test if not present):

```python
def test_build_cancel_stops_and_does_not_prune(tmp_path):
    import shutil
    import threading
    from pathlib import Path
    from vtextract.index.builder import INDEX_RELPATH, build
    from vtextract.index.db import IndexDB

    FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "archive"
    archive = tmp_path / "archive"
    shutil.copytree(FIXTURE, archive)

    # Full build first so source_file fingerprints exist.
    build(archive)

    # Now a cancel that is already set: the loop should process nothing new and,
    # crucially, must NOT prune the existing source_file rows.
    cancel = threading.Event()
    cancel.set()
    build(archive, cancel=cancel)

    db = IndexDB(archive / INDEX_RELPATH)
    try:
        remaining = db.counts()["source_files"]
    finally:
        db.close()
    assert remaining > 0, "cancelled build must not prune existing sources"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/index/test_builder.py -k cancel -v`
Expected: FAIL with `TypeError: build() got an unexpected keyword argument 'cancel'`.

- [ ] **Step 3: Add the `cancel` parameter and prune guard**

In `src/vtextract/index/builder.py`, change the `build` signature:

```python
def build(archive, *, rebuild: bool = False, reporter=None, cancel=None) -> BuildStats:
    """(Re)build the index from the archive. Incremental unless rebuild=True.

    ``cancel`` is an optional object with ``is_set() -> bool`` (e.g.
    threading.Event); when it becomes set the file loop stops early and the
    prune step is skipped so a cancelled build never deletes unseen sources.
    """
```

Inside the `for kind, relpath, abspath in candidates:` loop, add a check as the **first** statement of the loop body (before `seen.add(relpath)`):

```python
        for kind, relpath, abspath in candidates:
            if cancel is not None and cancel.is_set():
                break
            seen.add(relpath)
```

Then guard the prune block (currently `# prune vanished sources`):

```python
        # prune vanished sources — skip entirely if cancelled, since `seen` is
        # only partial and would otherwise delete sources we never looked at.
        if cancel is None or not cancel.is_set():
            for relpath in set(fingerprints) - seen:
                db.delete_source(relpath)
                stats.removed += 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/index/test_builder.py -k cancel -v`
Expected: PASS.

- [ ] **Step 5: Run the full builder suite (no regressions)**

Run: `uv run pytest tests/index/test_builder.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/vtextract/index/builder.py tests/index/test_builder.py
git commit -m "feat(index): cooperative cancel for builder.build with prune guard"
```

---

## Task 4: `IndexService` (service.py)

The shared facade: one long-lived read connection, the enrichment logic moved out of `cli.py`, typed DTO returns, a `build` static entry point, and `reopen`/`close` lifecycle. Raises a single `IndexUnavailable` for all open failures.

**Files:**
- Create: `src/vtextract/index/service.py`
- Test: `tests/index/test_service.py`

- [ ] **Step 1: Write the failing test**

Create `tests/index/test_service.py`:

```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

import pytest

from vtextract.index.models import (
    IndexStats, ItemDetail, PageEntry, PageNav, SearchHit, SearchQuery, VolumeInfo,
)
from vtextract.index.service import IndexService, IndexUnavailable


# built_archive / built_archive_with_search_hit come from tests/index/conftest.py
# (returns {"path", "root_id": "volA", "isadg_id": 100, ["query"]}).


def test_open_missing_index_raises_unavailable(tmp_path):
    with pytest.raises(IndexUnavailable, match="build"):
        IndexService(tmp_path / "archive")


def test_volumes_returns_volume_infos(built_archive):
    with IndexService(built_archive["path"]) as svc:
        vols = svc.volumes()
    roots = sorted(v.root_id for v in vols)
    assert isinstance(vols[0], VolumeInfo)
    assert roots == ["volA", "volB"]


def test_search_returns_hits_with_enriched_pages(built_archive_with_search_hit):
    info = built_archive_with_search_hit
    with IndexService(info["path"]) as svc:
        hits = svc.search(SearchQuery(text=info["query"], fields=("transcription",), limit=0))
    assert hits and isinstance(hits[0], SearchHit)
    hit = next(h for h in hits if h.isadg_id == info["isadg_id"])
    pg = next(p for p in hit.matched_pages if p.page_key == "volA_p1.jpg")
    assert isinstance(pg, PageEntry)
    assert pg.root_id == "volA"
    assert pg.role in ("primary", "context")
    assert pg.transcription and pg.transcription.endswith("volA_p1.jpg.txt")
    assert pg.image is None


def test_pages_returns_entries_in_order(built_archive):
    with IndexService(built_archive["path"]) as svc:
        pages = svc.pages("volA")
    assert [p.page_key for p in pages] == ["volA_p0.jpg", "volA_p1.jpg"]
    assert pages[0].ordinal == 1


def test_page_nav_mid_volume(built_archive):
    with IndexService(built_archive["path"]) as svc:
        nav = svc.page("volA", "volA_p1.jpg")
    assert isinstance(nav, PageNav)
    assert nav.current.page_key == "volA_p1.jpg"
    assert nav.current.ordinal == 2
    assert nav.previous.page_key == "volA_p0.jpg"
    assert nav.next is None
    assert nav.volume.title == "Registry of Deeds Transcript Book 86: memorials 1737"


def test_page_unknown_returns_none(built_archive):
    with IndexService(built_archive["path"]) as svc:
        assert svc.page("volA", "nope.jpg") is None


def test_item_returns_detail(built_archive):
    with IndexService(built_archive["path"]) as svc:
        item = svc.item(built_archive["isadg_id"])
    assert isinstance(item, ItemDetail)
    assert item.isadg_id == built_archive["isadg_id"]
    assert all(isinstance(p, PageEntry) and p.role for p in item.pages)


def test_item_unknown_returns_none(built_archive):
    with IndexService(built_archive["path"]) as svc:
        assert svc.item(99999) is None


def test_stats(built_archive):
    with IndexService(built_archive["path"]) as svc:
        stats = svc.stats()
    assert isinstance(stats, IndexStats)
    assert stats.items == 3
    assert stats.stale is False


def test_build_then_reopen_reflects_new_item(built_archive):
    import shutil
    archive = built_archive["path"]
    svc = IndexService(archive)
    try:
        before = svc.stats().items
        # Add a new item, rebuild via the service, reopen, observe the change.
        (archive / "items" / "400").mkdir()
        shutil.copy(archive / "items" / "300" / "metadata.json",
                    archive / "items" / "400" / "metadata.json")
        IndexService.build(archive)
        svc.reopen()
        assert svc.stats().items == before + 1
    finally:
        svc.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/index/test_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vtextract.index.service'`.

- [ ] **Step 3: Create the service module**

Create `src/vtextract/index/service.py`:

```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

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
    SearchHit,
    SearchQuery,
    VolumeHeader,
    VolumeInfo,
)
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
        if self._db is None:
            self._open()
        assert self._db is not None
        return self._db

    # --- reads ---

    def is_stale(self) -> bool:
        return _is_stale(self.db, self.archive)

    def search(self, q: SearchQuery) -> list[SearchHit]:
        return [_hit_from_result(self.archive, r) for r in _query_search(self.db, q)]

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
            stale=_is_stale(self.db, self.archive),
        )

    # --- build (write path) ---

    @staticmethod
    def build(archive, *, rebuild: bool = False, reporter=None,
              cancel: "threading.Event | None" = None) -> BuildStats:
        """(Re)build the index. Static: needs no open read connection (it is the
        operation that *creates* the index). Callers holding a read connection
        should ``reopen()`` afterwards to see new data."""
        return _build(Path(archive), rebuild=rebuild, reporter=reporter, cancel=cancel)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/index/test_service.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/index/service.py tests/index/test_service.py
git commit -m "feat(index): add IndexService facade with typed DTOs and build entry point"
```

---

## Task 5: Make `vtindex/cli.py` thin presentation over the service

Replace all direct `IndexDB`/`builder` use and the inline enrichment with `IndexService` calls plus DTO→dict serializers that reproduce the exact current JSON. Keep `main()`'s exit-code behaviour, including the new `IndexUnavailable` → exit 2.

**Files:**
- Modify: `src/vtextract/index/cli.py`
- Test: `tests/index/test_cli.py`, `tests/index/test_pages_subcommand.py`, `tests/index/test_item_subcommand.py`, `tests/index/test_search_role.py` (must stay green, unchanged)

- [ ] **Step 1: Run the existing CLI tests to confirm the baseline is green**

Run: `uv run pytest tests/index/test_cli.py tests/index/test_pages_subcommand.py tests/index/test_item_subcommand.py tests/index/test_search_role.py -q`
Expected: all PASS (this is the regression guard for the refactor).

- [ ] **Step 2: Update imports**

In `src/vtextract/index/cli.py`, replace the index imports:

```python
from vtextract.index.builder import INDEX_RELPATH, build, is_stale
from vtextract.index.db import Fts5Unavailable, IndexDB, SchemaMismatch
from vtextract.index.models import SearchQuery
from vtextract.index.query import search
```

with:

```python
from vtextract.index.models import IndexStats, ItemDetail, PageEntry, PageNav, SearchHit, SearchQuery
from vtextract.index.service import IndexService, IndexUnavailable
```

(Keep the other imports — `argparse`, `json`, `sqlite3`, `sys`, `Path`, `Console`, `Table`, `load_config`, the `vtextract.theme` import, and `from vtextract.progress import BuildReporter`.)

- [ ] **Step 3: Replace the enrichment helpers with DTO serializers**

Delete `_open_for_read`, `_page_file`, `_page_dict`, `_page_nav_dict`, and `_result_dict`. Add in their place:

```python
def _page_files_dict(e: PageEntry) -> dict:
    return {
        "root_id": e.root_id,
        "page_key": e.page_key,
        "image": e.image,
        "metadata": e.metadata,
        "transcription": e.transcription,
    }


def _result_dict(h: SearchHit) -> dict:
    return {
        "isadg_id": h.isadg_id,
        "title": h.title,
        "reference_code": h.reference_code,
        "repository": h.repository,
        "content_date": h.content_date,
        "created_date": h.created_date,
        "estimated_date": h.estimated_date,
        "estimated_source": h.estimated_source,
        "matched_fields": h.matched_fields,
        "matched_pages": [{**_page_files_dict(p), "role": p.role} for p in h.matched_pages],
        "score": h.score,
        "path": h.path,
    }


def _page_nav_dict(e: PageEntry | None) -> dict | None:
    if e is None:
        return None
    return {**_page_files_dict(e), "ordinal": e.ordinal, "label": e.label}


def _item_dict(d: ItemDetail) -> dict:
    return {
        "isadg_id": d.isadg_id,
        "reference_code": d.reference_code,
        "title": d.title,
        "description": d.description,
        "repository": d.repository,
        "content_begin": d.content_begin,
        "content_end": d.content_end,
        "created_begin": d.created_begin,
        "created_end": d.created_end,
        "estimated_begin": d.estimated_begin,
        "estimated_end": d.estimated_end,
        "estimated_source": d.estimated_source,
        "pages": [{"root_id": p.root_id, "page_key": p.page_key, "role": p.role} for p in d.pages],
    }
```

> Note: `_build_results_table`/`_print_results_table` are unchanged — they read only the common attributes (`isadg_id`, `content_date`, `estimated_date`, `reference_code`, `title`) shared by `SearchResult` and `SearchHit`. `test_cli.py` still constructs `SearchResult` for those table tests, which keeps working.

- [ ] **Step 4: Rewrite `_cmd_build` to use the service**

Replace the body of `_cmd_build` that calls `build(...)`:

```python
    if args.json_progress:
        from vtextract.progress import JsonBuildReporter
        with JsonBuildReporter() as reporter:
            stats = IndexService.build(archive, rebuild=args.rebuild, reporter=reporter)
    else:
        with BuildReporter() as reporter:
            stats = IndexService.build(archive, rebuild=args.rebuild, reporter=reporter)
```

(The surrounding archive-validation and `stats.skipped` logic is unchanged.)

- [ ] **Step 5: Rewrite the read commands to use the service**

Replace `_cmd_search`:

```python
def _cmd_search(args) -> int:
    archive = _resolve_archive(args)
    query = SearchQuery(
        text=args.query,
        fields=_parse_fields(args.in_fields),
        date_from=_date_bound(args.date_from, upper=False),
        date_to=_date_bound(args.date_to, upper=True),
        date_type=args.date_type,
        volume=args.volume,
        limit=args.limit,
        offset=args.offset,
    )
    with IndexService(archive) as svc:
        if svc.is_stale():
            print("warning: index is stale; run `vtindex build` to refresh.",
                  file=sys.stderr)
        results = svc.search(query)
    if args.json:
        print(json.dumps([_result_dict(r) for r in results], indent=2))
    else:
        _print_results_table(results, theme=THEMES[args.theme], query=args.query)
    return 0 if results else 1
```

Replace `_cmd_volumes`:

```python
def _cmd_volumes(args) -> int:
    archive = _resolve_archive(args)
    with IndexService(archive) as svc:
        vols = svc.volumes()
    data = [
        {"root_id": v.root_id, "label": v.label,
         "reference_code": v.reference_code, "item_count": v.item_count,
         "title": v.title}
        for v in vols
    ]
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        _print_volumes_table(vols, theme=THEMES[args.theme])
    return 0
```

Replace `_cmd_stats`:

```python
def _cmd_stats(args) -> int:
    archive = _resolve_archive(args)
    with IndexService(archive) as svc:
        s = svc.stats()
    data = {
        "items": s.items,
        "volumes": s.volumes,
        "pages": s.pages,
        "schema_version": s.schema_version,
        "stale": s.stale,
    }
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        for k, v in data.items():
            print(f"{k}: {v}")
    return 0
```

Replace `_cmd_page`:

```python
def _cmd_page(args) -> int:
    if not args.ref:
        args.parser.print_help(sys.stderr)
        return 2
    archive = _resolve_archive(args)
    if "/" not in args.ref:
        print("error: argument must be <root_id>/<page_key>", file=sys.stderr)
        return 2
    root_id, page_key = args.ref.split("/", 1)
    with IndexService(archive) as svc:
        if svc.is_stale():
            print("warning: index is stale; run `vtindex build` to refresh.",
                  file=sys.stderr)
        nav = svc.page(root_id, page_key)
    if nav is None:
        if args.json:
            print(json.dumps(None))
        else:
            print(f"page not found: {args.ref}")
        return 1
    if nav.current.ordinal is None:
        print("warning: page ordering unavailable (re-extract this volume to "
              "regenerate volume.json).", file=sys.stderr)
    data = {
        "volume": {"root_id": nav.volume.root_id, "title": nav.volume.title},
        "previous": _page_nav_dict(nav.previous),
        "current": _page_nav_dict(nav.current),
        "next": _page_nav_dict(nav.next),
    }
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        _print_page_nav(data, nav.volume.title, theme=THEMES[args.theme])
    return 0
```

Replace `_cmd_pages`:

```python
def _cmd_pages(args) -> int:
    archive = _resolve_archive(args)
    with IndexService(archive) as svc:
        if svc.is_stale():
            print("warning: index is stale; run `vtindex build` to refresh.",
                  file=sys.stderr)
        rows = svc.pages(args.root_id)
    if not rows:
        if args.json:
            print(json.dumps([]))
        else:
            print(f"no pages for volume {args.root_id}")
        return 1
    enriched = [_page_nav_dict(p) for p in rows]
    if args.json:
        print(json.dumps(enriched, indent=2))
    else:
        _print_page_list(enriched, theme=THEMES[args.theme])
    return 0
```

Replace `_cmd_item`:

```python
def _cmd_item(args) -> int:
    archive = _resolve_archive(args)
    with IndexService(archive) as svc:
        if svc.is_stale():
            print("warning: index is stale; run `vtindex build` to refresh.",
                  file=sys.stderr)
        detail = svc.item(args.isadg_id)
    if detail is None:
        if args.json:
            print(json.dumps(None))
        else:
            print(f"item not found: {args.isadg_id}")
        return 1
    item = _item_dict(detail)
    if args.json:
        print(json.dumps(item, indent=2))
    else:
        for k, v in item.items():
            if k == "pages":
                continue
            print(f"{k}: {v if v is not None else '-'}")
        print("pages:")
        for p in item["pages"]:
            print(f"  {p['role']:7s}  {p['root_id']}/{p['page_key']}")
    return 0
```

- [ ] **Step 6: Update `main()`'s exception handling**

In `main()`, replace the `except (FileNotFoundError, SchemaMismatch, Fts5Unavailable) as exc:` clause with:

```python
    except (FileNotFoundError, IndexUnavailable) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
```

(Keep the `sqlite3.OperationalError` and `argparse.ArgumentTypeError` clauses as-is. `FileNotFoundError` is still raised by `_cmd_build`'s archive check and by `load_config`.)

- [ ] **Step 7: Run the CLI test suite to verify identical behaviour**

Run: `uv run pytest tests/index/test_cli.py tests/index/test_pages_subcommand.py tests/index/test_item_subcommand.py tests/index/test_search_role.py tests/index/test_build_json_progress.py -q`
Expected: all PASS (no test changes were needed — output is byte-stable).

- [ ] **Step 8: Commit**

```bash
git add src/vtextract/index/cli.py
git commit -m "refactor(index): make vtindex cli thin presentation over IndexService"
```

---

## Task 6: Rewrite `tui/index_client.py` as an in-process gateway

Replace subprocess spawning with an `IndexService` run on a dedicated single-thread executor (reads) and a worker thread (build), returning DTOs and yielding the same `ProgressEvent`s.

**Files:**
- Modify (full rewrite): `src/vtextract/tui/index_client.py`
- Modify (full rewrite): `tests/tui/test_index_client.py`

- [ ] **Step 1: Write the failing tests**

Replace the entire contents of `tests/tui/test_index_client.py` with:

```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from vtextract.index.models import IndexStats, ItemDetail, PageNav, SearchHit, VolumeInfo
from vtextract.tui.index_client import IndexClient, IndexError
from vtextract.tui.progress_events import DoneEvent, ProgressUpdate, StartEvent

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "archive"


@pytest.fixture
def built(tmp_path):
    """A fixture archive with its index built in-process."""
    from vtextract.index.service import IndexService
    archive = tmp_path / "archive"
    shutil.copytree(FIXTURE, archive)
    IndexService.build(archive)
    return archive


@pytest.fixture
def unbuilt(tmp_path):
    archive = tmp_path / "archive"
    shutil.copytree(FIXTURE, archive)
    return archive


@pytest.mark.asyncio
async def test_volumes_returns_volume_infos(built):
    client = IndexClient(built)
    try:
        vols = await client.volumes()
    finally:
        client.close()
    assert isinstance(vols[0], VolumeInfo)
    assert sorted(v.root_id for v in vols) == ["volA", "volB"]


@pytest.mark.asyncio
async def test_search_returns_hits(built):
    client = IndexClient(built)
    try:
        hits = await client.search(query="Houston", fields=("title",), limit=0)
    finally:
        client.close()
    assert hits and isinstance(hits[0], SearchHit)
    assert hits[0].isadg_id == 100


@pytest.mark.asyncio
async def test_page_and_pages_and_item(built):
    client = IndexClient(built)
    try:
        nav = await client.page("volA", "volA_p1.jpg")
        pages = await client.pages("volA")
        item = await client.item(100)
    finally:
        client.close()
    assert isinstance(nav, PageNav) and nav.previous.page_key == "volA_p0.jpg"
    assert [p.page_key for p in pages] == ["volA_p0.jpg", "volA_p1.jpg"]
    assert isinstance(item, ItemDetail) and item.isadg_id == 100


@pytest.mark.asyncio
async def test_stats_returns_index_stats(built):
    client = IndexClient(built)
    try:
        stats = await client.stats()
    finally:
        client.close()
    assert isinstance(stats, IndexStats)
    assert stats.items == 3


@pytest.mark.asyncio
async def test_stats_raises_index_error_when_missing(unbuilt):
    client = IndexClient(unbuilt)
    try:
        with pytest.raises(IndexError):
            await client.stats()
    finally:
        client.close()


@pytest.mark.asyncio
async def test_build_stream_emits_events_then_index_is_usable(unbuilt):
    client = IndexClient(unbuilt)
    try:
        events = [ev async for ev in client.build_stream()]
        assert isinstance(events[0], StartEvent)
        assert any(isinstance(e, ProgressUpdate) for e in events)
        assert isinstance(events[-1], DoneEvent)
        # After the build, reads must work (service refreshed).
        stats = await client.stats()
        assert stats.items == 3
    finally:
        client.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/tui/test_index_client.py -v`
Expected: FAIL (the current subprocess `IndexClient` returns dicts / has no DTOs; several asserts fail or error).

- [ ] **Step 3: Rewrite the gateway**

Replace the entire contents of `src/vtextract/tui/index_client.py` with:

```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""In-process gateway to the archive index for the vtbrowse TUI.

This is the ONLY place in vtextract/tui/ that holds an ``IndexService``. It runs
the (synchronous) service on a dedicated single-thread executor so the Textual
event loop stays responsive and the SQLite connection stays confined to one
thread. Builds run on a worker thread with a queue-backed progress reporter and
cooperative cancellation. Read methods return the service's typed DTOs.

Per the architectural boundary (tests/test_no_direct_db.py) tui/ never imports
vtextract.index.{db,query,builder}; it goes through vtextract.index.service.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from vtextract.index.models import SearchQuery
from vtextract.index.service import IndexService, IndexUnavailable
from vtextract.tui.progress_events import (
    DoneEvent,
    ErrorEvent,
    LogEvent,
    ProgressEvent,
    ProgressUpdate,
    StartEvent,
)


class IndexError(RuntimeError):
    """The index is unavailable (missing or incompatible). Mirrors the old
    subprocess exit-2 condition so callers (App._detect_index_state) are
    unchanged."""


class _QueueBuildReporter:
    """A ``builder.build()``-compatible reporter that turns build progress into
    ``ProgressEvent``s, handed to a thread-safe ``emit`` callback (the build runs
    on a worker thread, so ``emit`` marshals back onto the event loop)."""

    def __init__(self, emit) -> None:
        self._emit = emit
        self._total = 0
        self._current = 0
        self._started = time.monotonic()

    def start(self, total: int) -> None:
        self._total = total
        self._current = 0
        self._emit(LogEvent(message=f"Indexing {total} files."))
        self._emit(ProgressUpdate(phase="indexing", current=0, total=total))

    def advance(self, n: int = 1) -> None:
        self._current += n
        self._emit(ProgressUpdate(phase="indexing", current=self._current,
                                  total=self._total))

    def finish(self, *, added: int, updated: int, removed: int,
               unchanged: int, skipped: int) -> None:
        self._emit(DoneEvent(
            elapsed_seconds=round(time.monotonic() - self._started, 2),
            counters={"added": added, "updated": updated, "removed": removed,
                      "unchanged": unchanged, "skipped": skipped},
        ))


class IndexClient:
    """In-process gateway holding an ``IndexService`` on a single executor thread."""

    def __init__(self, archive: Path) -> None:
        self.archive = Path(archive)
        self._service: IndexService | None = None
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vtindex-read")

    # ---------- read dispatch (single dedicated thread) ----------

    def _run(self, fn):
        try:
            if self._service is None:
                self._service = IndexService(self.archive)
            return fn(self._service)
        except IndexUnavailable as exc:
            raise IndexError(str(exc)) from exc

    async def _call(self, fn):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._pool, self._run, fn)

    async def volumes(self):
        return await self._call(lambda s: s.volumes())

    async def search(self, *, query: str | None = None,
                     fields: tuple[str, ...] | None = None,
                     date_from: str | None = None, date_to: str | None = None,
                     date_type: str = "content", volume: str | None = None,
                     limit: int = 50, offset: int = 0):
        q = SearchQuery(
            text=query or None,
            fields=fields or ("title", "description", "transcription"),
            date_from=date_from, date_to=date_to, date_type=date_type,
            volume=volume, limit=limit, offset=offset,
        )
        return await self._call(lambda s: s.search(q))

    async def page(self, root_id: str, page_key: str):
        return await self._call(lambda s: s.page(root_id, page_key))

    async def pages(self, root_id: str):
        return await self._call(lambda s: s.pages(root_id))

    async def item(self, isadg_id: int):
        return await self._call(lambda s: s.item(isadg_id))

    async def stats(self):
        return await self._call(lambda s: s.stats())

    # ---------- lifecycle ----------

    def _reset_service(self) -> None:
        """Runs on the read thread: drop the service so the next read reopens it."""
        if self._service is not None:
            self._service.close()
            self._service = None

    def close(self) -> None:
        self._pool.shutdown(wait=False)

    # ---------- in-process build ----------

    async def build_stream(
        self, *, rebuild: bool = False,
        cancel_event: asyncio.Event | None = None,
    ) -> AsyncIterator[ProgressEvent]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        cancel = threading.Event()
        sentinel = object()

        def emit(ev: ProgressEvent) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, ev)

        reporter = _QueueBuildReporter(emit)

        def run_build() -> None:
            emit(StartEvent(tool="vtindex build", argv=[]))
            try:
                IndexService.build(self.archive, rebuild=rebuild,
                                   reporter=reporter, cancel=cancel)
            except Exception as exc:  # noqa: BLE001 — surface as a stream event
                emit(ErrorEvent(message=str(exc), exit_code=1))
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, sentinel)

        fut = loop.run_in_executor(None, run_build)
        try:
            while True:
                ev = await queue.get()
                if ev is sentinel:
                    break
                yield ev
                if cancel_event is not None and cancel_event.is_set():
                    cancel.set()
        finally:
            # Consumer aclose()'d or finished: ensure the build stops, drain the
            # worker, then refresh the read connection so post-build reads see
            # new rows (mandatory after --rebuild drops/recreates tables).
            cancel.set()
            await fut
            await loop.run_in_executor(self._pool, self._reset_service)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/tui/test_index_client.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/tui/index_client.py tests/tui/test_index_client.py
git commit -m "feat(tui): rewrite IndexClient as in-process gateway over IndexService"
```

---

## Task 7: Update `tests/tui/test_stream_cancel.py` for in-process cancel

The two `IndexClient` tests assert subprocess SIGTERM/SIGKILL, which no longer applies. Replace them with a cooperative-cancel test. The `ExtractClient` test stays (it is still a subprocess).

**Files:**
- Modify: `tests/tui/test_stream_cancel.py`

- [ ] **Step 1: Replace the IndexClient subprocess tests**

In `tests/tui/test_stream_cancel.py`, delete `test_index_build_stream_terminates_subprocess_on_cancel` and `test_build_stream_kills_after_terminate_timeout` (the two `IndexClient` tests). Keep `test_extract_stream_terminates_subprocess_on_cancel` and the `_FakeProc` class it relies on. Update the module docstring to:

```python
"""Cancellation contracts for the progress streams.

ExtractClient._stream still drives a subprocess, so it must terminate() the
child on cancel (verified here with a fake process). IndexClient.build_stream is
now in-process: cancellation is cooperative — setting cancel_event stops the
build loop and the stream ends without a synthetic error event.
"""
```

Add this in-process test (it does a real build of the fixture archive; the cancel is checked per-file by `builder.build`):

```python
import shutil
from pathlib import Path

from vtextract.tui.progress_events import ErrorEvent

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "archive"


@pytest.mark.asyncio
async def test_index_build_stream_cancel_is_cooperative_and_clean(tmp_path):
    archive = tmp_path / "archive"
    shutil.copytree(_FIXTURE, archive)

    cancel_event = asyncio.Event()
    client = IndexClient(archive=archive)
    try:
        stream = client.build_stream(cancel_event=cancel_event)
        received = []
        async for ev in stream:
            received.append(ev)
            # Cancel as soon as the first event arrives, then stop consuming.
            cancel_event.set()
            await stream.aclose()
            break
        assert received, "stream should have yielded at least one event"
        # Cancellation must not surface as an error event.
        assert not any(isinstance(e, ErrorEvent) for e in received)
    finally:
        client.close()
```

- [ ] **Step 2: Run the test file**

Run: `uv run pytest tests/tui/test_stream_cancel.py -v`
Expected: all PASS (the extract test plus the new cooperative-cancel test).

- [ ] **Step 3: Commit**

```bash
git add tests/tui/test_stream_cancel.py
git commit -m "test(tui): cooperative-cancel test for in-process build_stream"
```

---

## Task 8: Update TUI consumers to attribute access (DTOs)

Read methods now return DTOs. Convert each consumer from dict indexing to attribute access. Field names are identical, so changes are mechanical. Also close the gateway on app exit.

**Files:**
- Modify: `src/vtextract/tui/screens/volumes.py`
- Modify: `src/vtextract/tui/screens/pages.py`
- Modify: `src/vtextract/tui/screens/transcription.py`
- Modify: `src/vtextract/tui/screens/results.py`
- Modify: `src/vtextract/tui/dialogs/info.py`
- Modify: `src/vtextract/tui/app.py`

- [ ] **Step 1: Confirm the current TUI suite is green (baseline)**

Run: `uv run pytest tests/tui -q`
Expected: most PASS; `test_index_client.py` and `test_stream_cancel.py` already updated in Tasks 6–7. Note any failures now caused by DTO returns in screen/dialog tests — those are what this task fixes. Record the baseline.

- [ ] **Step 2: Update `screens/volumes.py`**

In `on_mount`, replace the loop body:

```python
        for v in await self.index.volumes():
            title = v.title or v.label or v.root_id
            self.add_row(
                v.root_id,
                str(v.item_count),
                title,
                v.reference_code or "-",
            )
            self._row_root_ids.append(v.root_id)
            self._row_titles.append(title)
```

- [ ] **Step 3: Update `screens/pages.py`**

Change the `_pages` annotation and the two methods that read page fields. Update `__init__`'s `self._pages: list[dict] = []` to `self._pages: list = []`. Replace `_add`:

```python
    def _add(self, p) -> None:
        ref = PageRef(self.root_id, p.page_key)
        self.add_row(
            str(p.ordinal),
            p.page_key,
            "•" if p.transcription else "",
            "•" if p.image else "",
            "*" if self.bundle.is_in_bundle(ref) else "",
        )
```

In `action_view_page`, `action_toggle_select`, `action_toggle_all`, and `selected_context`, replace `p["page_key"]` with `p.page_key` (4 occurrences across those methods; e.g. `PageRef(self.root_id, p.page_key)`, `self.app.open_transcription(self.root_id, p.page_key)`, and `return ("page", self.root_id, p.page_key)`).

- [ ] **Step 4: Update `screens/transcription.py`**

Replace `action_prev_page` and `action_next_page`:

```python
    async def action_prev_page(self) -> None:
        nav = await self.index.page(self.root_id, self.page_key)
        if nav and nav.previous:
            self.app.open_transcription(  # type: ignore[attr-defined]
                self.root_id, nav.previous.page_key,
                query=self.query, origin=self.origin, view=self.view)

    async def action_next_page(self) -> None:
        nav = await self.index.page(self.root_id, self.page_key)
        if nav and nav.next:
            self.app.open_transcription(  # type: ignore[attr-defined]
                self.root_id, nav.next.page_key,
                query=self.query, origin=self.origin, view=self.view)
```

- [ ] **Step 5: Update `screens/results.py`**

`results` is now `list[SearchHit]`. Update `_date_cell`, the `__init__` annotation, `on_mount`, and the toggle/view actions to attribute access:

```python
def _date_cell(result) -> str:
    """The catalog's single date: the content date, else the estimated date in
    square brackets (the ISAD(G) convention for a supplied/estimated date)."""
    content = result.content_date
    if content:
        return content
    estimated = result.estimated_date
    return f"[{estimated}]" if estimated else "-"
```

Change `def __init__(self, *, bundle: Bundle, results: list[dict], query: str)` to `results: list`. In `on_mount`:

```python
        for r in self.results:
            in_bundle = r.isadg_id in self.bundle.selected_items
            self.add_row(
                _sel_cell(in_bundle),
                str(r.isadg_id),
                _date_cell(r),
                r.reference_code or "-",
                r.title or "-",
            )
```

In `action_view_first_match`:

```python
        r = self.results[self.cursor_row]
        pages = r.matched_pages or []
        if not pages:
            return
        target = next((p for p in pages if p.role == "primary"), pages[0])
        self.app.open_transcription(  # type: ignore[attr-defined]
            target.root_id, target.page_key, query=self.query,
            origin="results")
```

In `action_toggle_item`:

```python
        r = self.results[self.cursor_row]
        refs = [PageRef(p.root_id, p.page_key) for p in r.matched_pages]
        self.bundle.toggle_item(r.isadg_id, refs)
        in_bundle = r.isadg_id in self.bundle.selected_items
        self.update_cell_at((self.cursor_row, 0), _sel_cell(in_bundle))
        self.app.bundle_changed()  # type: ignore[attr-defined]
```

In `action_toggle_all`:

```python
        all_selected = all(
            r.isadg_id in self.bundle.selected_items for r in self.results
        )
        for row, r in enumerate(self.results):
            in_bundle = r.isadg_id in self.bundle.selected_items
            if all_selected == in_bundle:
                refs = [PageRef(p.root_id, p.page_key) for p in r.matched_pages]
                self.bundle.toggle_item(r.isadg_id, refs)
            self.update_cell_at((row, 0), _sel_cell(not all_selected))
        self.app.bundle_changed()  # type: ignore[attr-defined]
```

In `selected_context`:

```python
        return ("item", self.results[self.cursor_row].isadg_id)
```

- [ ] **Step 6: Update `dialogs/info.py`**

`PageInfoDialog._body` — the contributing-items loop:

```python
        for iid in contributing:
            item = await self.index.item(iid)
            title = item.title if item else ""
            lines.append(f"  {iid}  {title or ''}")
```

`VolumeInfoDialog._body`:

```python
    async def _body(self) -> str:
        vols = {v.root_id: v for v in await self.index.volumes()}
        v = vols.get(self.root_id)
        pages = await self.index.pages(self.root_id)
        in_bundle = sum(1 for p in self.bundle.effective_pages()
                        if p.root_id == self.root_id)
        return "\n".join([
            f"Root ID      {self.root_id}",
            f"Title        {(v.title if v else None) or '-'}",
            f"Reference    {(v.reference_code if v else None) or '-'}",
            f"Label        {(v.label if v else None) or '-'}",
            f"Items        {v.item_count if v else 0}",
            f"Pages        {len(pages)}",
            f"In bundle    {in_bundle} pages from this volume",
        ])
```

`ItemInfoDialog._body`:

```python
    async def _body(self) -> str:
        item = await self.index.item(self.isadg_id)
        if item is None:
            return f"item {self.isadg_id} not found"
        pages_block = "\n".join(
            f"  {p.role:7s}  {p.root_id}/{p.page_key}"
            for p in item.pages
        )
        in_bundle = self.isadg_id in self.bundle.selected_items
        est = _fmt_range(item.estimated_begin, item.estimated_end)
        source = item.estimated_source
        if est != "-" and source:
            est = f"{est} (from {source})"
        return "\n".join([
            f"ISADG ID     {item.isadg_id}",
            f"Title        {item.title or '-'}",
            f"Reference    {item.reference_code or '-'}",
            f"Repository   {item.repository or '-'}",
            f"Content date {_fmt_range(item.content_begin, item.content_end)}",
            f"Created date {_fmt_range(item.created_begin, item.created_end)}",
            f"Estimated    {est}",
            "",
            f"Pages ({len(item.pages)})",
            pages_block,
            "",
            f"In bundle    {'yes (item selected)' if in_bundle else 'no'}",
        ])
```

- [ ] **Step 7: Update `app.py`**

Change the `last_results` annotation (line ~106) from `self.last_results: list[dict] = []` to `self.last_results: list = []`.

Update `_detect_index_state` and `_poll_stale` to read the DTO attribute instead of `.get("stale")`:

```python
    async def _detect_index_state(self) -> Literal["missing", "stale", "ok"]:
        try:
            stats = await self.index.stats()
        except IndexError:
            return "missing"
        return "stale" if stats.stale else "ok"
```

```python
    async def _poll_stale(self) -> None:
        try:
            stats = await self.index.stats()
        except IndexError:
            return
        is_stale = bool(stats.stale)
        if is_stale != self._stale_chip_visible:
            self._stale_chip_visible = is_stale
            self._refresh_header_chip()
```

Add an unmount hook to release the executor thread (place it next to the other lifecycle methods, e.g. after `on_mount`):

```python
    def on_unmount(self) -> None:
        self.index.close()
```

- [ ] **Step 8: Run the full TUI suite**

Run: `uv run pytest tests/tui -q`
Expected: all PASS. If a snapshot test fails with an unchanged-looking screen, inspect the diff; rendered output should be identical, so a genuine diff means a missed conversion — fix the code, do **not** blindly `--snapshot-update`.

- [ ] **Step 9: Commit**

```bash
git add src/vtextract/tui/screens/volumes.py src/vtextract/tui/screens/pages.py \
        src/vtextract/tui/screens/transcription.py src/vtextract/tui/screens/results.py \
        src/vtextract/tui/dialogs/info.py src/vtextract/tui/app.py
git commit -m "refactor(tui): consume IndexService DTOs by attribute access"
```

---

## Task 9: Retarget the boundary test + docs; full-suite verification

The boundary rule shifts from "shell out to vtindex" to "go through `index.service`". The test's logic is unchanged (it still forbids `db`/`query`/`builder`); update its prose. Update CLAUDE.md. Run everything.

**Files:**
- Modify: `tests/test_no_direct_db.py` (docstring + assertion message only)
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the boundary test prose**

In `tests/test_no_direct_db.py`, replace the module docstring with:

```python
"""Enforces the architectural boundary from
docs/superpowers/specs/2026-06-01-index-service-library-design.md: vtbrowse
accesses the index ONLY through the shared library (vtextract.index.service /
vtextract.index.models). It never imports the index backend (db / query /
builder) or the network layer (fetcher / client) directly. The single holder of
an IndexService is tui/index_client.py."""
```

Replace the final `assert` message:

```python
    assert not offenders, (
        "vtbrowse modules must go through vtextract.index.service (and "
        "index.models) instead of importing the index backend or network layer "
        "directly:\n  "
        + "\n  ".join(offenders)
    )
```

- [ ] **Step 2: Verify the boundary test passes**

Run: `uv run pytest tests/test_no_direct_db.py -v`
Expected: PASS (the new `index_client.py` imports only `index.service` + `index.models`).

- [ ] **Step 3: Update CLAUDE.md**

In `CLAUDE.md`, in the `index/` bullet, append a sentence noting the public entry point. Change the start of that bullet to mention `service.py`:

```
- `index/` (subpackage) — the `vtindex` CLI. `service.py` is the **single public
  entry point** (the `IndexService` facade: long-lived read connection, typed
  DTOs, build entry point); both the CLI and the TUI consume it and nothing
  else touches the backend. `db.py` is the **single SQL choke
  point** (SQLite + FTS5; analogous to `client.py`). `reader.py` is pure
  archive-file parsing (analogous to `schema.py`). `builder.py` does an
  incremental, stat-fingerprint build (analogous to `fetcher.py`). `query.py`
  composes a search from `db` primitives. `cli.py` is thin presentation over
  `service.py` (Rich tables + `--json`). Build progress reuses
  `progress.BuildReporter`.
```

In the `tui/` bullet, replace the "Architectural boundary" sentence and the `index_client.py` sub-bullet:

```
- `tui/` (subpackage) — the `vtbrowse` TUI. **Architectural boundary:** `tui/`
  never imports `vtextract.index.{db,query,builder}` or
  `vtextract.{fetcher,client}` directly. Index access goes through the shared
  `vtextract.index.service` library (in-process); extraction still shells out.
  CI enforces this with `tests/test_no_direct_db.py`. Module map:
```

```
  - `index_client.py` — the sole holder of an in-process `IndexService`
    (`vtextract.index.service`); runs reads on a dedicated single-thread
    executor and builds on a worker thread, returning typed DTOs and yielding
    progress events. No longer a subprocess wrapper.
```

- [ ] **Step 4: Run the entire test suite**

Run: `uv run pytest -q`
Expected: all PASS (including `tests/index`, `tests/tui`, and the boundary test).

- [ ] **Step 5: Manual smoke check (optional but recommended)**

Run the CLI to confirm unchanged behaviour against your real archive:

```bash
uv run vtindex stats --archive ./archive --json
uv run vtindex search Houston --in title --archive ./archive --json
```

Expected: same JSON shapes as before this work.

- [ ] **Step 6: Commit**

```bash
git add tests/test_no_direct_db.py CLAUDE.md
git commit -m "docs: retarget index access boundary to the shared service library"
```

---

## Self-review notes (for the executor)

- **Spec coverage:** §1 service → Task 4; §2 DTOs → Tasks 1–2; §3 thin CLI → Task 5; §4 in-process gateway → Task 6; §5 in-process build + cancel + reopen → Tasks 3, 6 (+ Task 7 test); §6 boundary/docs → Task 9.
- **Byte-stable JSON:** guaranteed by Task 5 serializers + the unchanged `tests/index/test_cli.py` (Step 1/Step 7 gates).
- **`PageEntry` vs spec `PageRef`:** deliberate rename to avoid clashing with `tui.bundle.PageRef`; flagged at the top of this plan.
- **`IndexError` symbol:** the TUI keeps its own `IndexError` (in `index_client.py`); the service raises `IndexUnavailable`; the gateway translates one to the other so `app.py`'s `except IndexError` is untouched.
- **No new imports of forbidden modules in `tui/`:** the gateway imports only `vtextract.index.service` and `vtextract.index.models`.
