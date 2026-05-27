# vtindex Archive Index — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a second CLI, `vtindex`, that builds a persistent SQLite/FTS5 index over a `vtextract` archive and runs structured keyword + time-frame + volume searches without re-reading every file on each query.

**Architecture:** A new subpackage `src/vtextract/index/` mirroring the existing one-responsibility module discipline: `db.py` is the single SQL choke point (connection, schema, FTS5 detection, all queries); `reader.py` is pure archive-file parsing; `builder.py` orchestrates incremental builds via stat fingerprints; `query.py` composes a search from db primitives; `cli.py` wires argparse, archive resolution, output, and exit codes. Build progress reuses the existing `rich`-based reporter in `progress.py`, which is generalized so a neutral single-bar reporter is shared by build while the extractor's two-bar fetch behavior is layered on top.

**Tech Stack:** Python 3, stdlib `sqlite3` with the FTS5 extension (no server, single file), `rich` (already a dependency), argparse, pytest.

**Spec:** `docs/superpowers/specs/2026-05-27-vtindex-archive-index-design.md`

---

## Reference: design facts the implementer must honor

- **Archive layout** (input): `items/<isadgID>/metadata.json`, `pages/<rootID>/<pageKey>.jpg` with sibling `<pageKey>.jpg.txt` (transcription) and `<pageKey>.jpg.json` (annotations), and `pages/<rootID>/volume.json` = `{label, reference_code}`.
- **`metadata.json` shape** (written by `archive.py`): top-level `isadgID` (int), `referenceCode` (str), `title` (str), `pages` (list of `{page_key, root_id, role, ...}`), `searchHit` (dict), `detail` (dict|null).
- **`searchHit` fields used:** `documentRepositoryName` (str), `contentDate {gte,lte}`, `createdDate {gte,lte}`, and the description lists `scopeAndContent`, `archivalHistory`, `archivistsNote`, `administrativeOrBiographicalHistory`, `note` (each a list of strings, may be empty/absent). `createdDate` is absent on some items; `contentDate` is effectively always present.
- **Dates** are stored as ISO strings only (`YYYY-MM-DD`). A bare-year query bound is converted to ISO at the CLI edge (`1737` → from `1737-01-01`, to `1737-12-31`). Range match is an **overlap** test on ISO bounds (`begin <= to AND end >= from`), which sorts correctly lexicographically. (This refines the spec, which mentioned redundant integer-year columns; ISO-only filtering covers the requirement with less schema.)
- **Result unit is the item.** Transcription is page-level and a page is shared by many items: a transcription keyword hit resolves to items by joining the matched page through `item_page`, and the result reports the matched page(s).
- **An item's transcription `.txt` may be absent** (only downloaded volumes have pages). Absence is normal → `page.has_text = 0`, no transcription FTS row.
- **The index lives at** `<archive>/index/vtindex.sqlite3`.

## File structure

| File | Responsibility |
|---|---|
| `src/vtextract/progress.py` (modify) | Extract `ProgressReporter` base (rich plumbing + single overall bar); keep `Reporter` (fetch, two bars) layered on it; add `BuildReporter` (neutral single bar). |
| `src/vtextract/index/__init__.py` (create) | Empty package marker. |
| `src/vtextract/index/models.py` (create) | Dataclasses: `PageLink`, `ItemRow`, `VolumeRow`, `SearchQuery`, `SearchResult`, `VolumeInfo`, `BuildStats`. |
| `src/vtextract/index/db.py` (create) | `IndexDB`: connection, schema DDL, `SCHEMA_VERSION`, FTS5 probe, all SQL (fingerprints, upserts, deletes, prune, meta, counts, search primitives, volumes). The only module issuing SQL. |
| `src/vtextract/index/reader.py` (create) | Pure parsing: `read_item`, `read_volume`, `read_transcription`, helpers `compose_description`, `date_bounds`. No DB, no `rich`. |
| `src/vtextract/index/builder.py` (create) | `build(archive, *, rebuild, reporter)`: stat-fingerprint diff, upsert/delete via `IndexDB`, progress, returns `BuildStats`. |
| `src/vtextract/index/query.py` (create) | `search(db, query)`: combine item-FTS + transcription-FTS matches, apply structured filters via `db`, assemble/sort/limit `SearchResult`s. |
| `src/vtextract/index/cli.py` (create) | argparse for `build`/`search`/`volumes`/`stats`; archive resolution; human/JSON rendering; exit codes; staleness warning; `main()`. |
| `pyproject.toml` (modify) | Add `vtindex = "vtextract.index.cli:main"` console script. |
| `tests/fixtures/archive/...` (create) | Small committed fixture archive (items, volumes, transcriptions). |
| `tests/index/test_*.py` (create) | One test module per index module. |
| `README.md`, `CLAUDE.md` (modify) | Document `vtindex`. |

---

## Setup (once, before Task 1)

- [ ] **Create the worktree virtualenv and install dev deps**

This worktree has no `.venv`. Create one and install the package editable with dev extras (matches the project's `.venv/bin/python -m pytest` convention).

Run:
```bash
python3 -m venv .venv
.venv/bin/python -m pip install -q -e ".[dev]"
.venv/bin/python -m pytest -q
```
Expected: the existing suite passes (baseline green before any change).

---

## Task 1: Generalize `progress.py` (shared reporter)

**Files:**
- Modify: `src/vtextract/progress.py`
- Test: `tests/test_progress.py` (existing, must still pass), `tests/index/test_build_reporter.py` (create)

- [ ] **Step 1: Add the new BuildReporter test**

Create `tests/index/test_build_reporter.py`:
```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from io import StringIO

from rich.console import Console

from vtextract.progress import BuildReporter


def _build_reporter():
    buf = StringIO()
    console = Console(file=buf, force_terminal=False, width=120)
    return BuildReporter(console=console, enabled=False), buf


def test_build_reporter_emits_neutral_lines():
    reporter, buf = _build_reporter()
    with reporter:
        reporter.start(3)
        reporter.advance()
        reporter.advance()
        reporter.advance()
    reporter.finish(added=1, updated=1, removed=0, unchanged=1, skipped=0)

    out = buf.getvalue()
    assert "Indexing 3 files." in out
    assert "indexed: 1 added, 1 updated, 0 removed, 1 unchanged, 0 skipped" in out
```

- [ ] **Step 2: Run both progress tests to verify the new one fails**

Run: `.venv/bin/python -m pytest tests/test_progress.py tests/index/test_build_reporter.py -v`
Expected: existing `test_progress.py` PASSES; new `test_build_reporter.py` FAILS with `ImportError: cannot import name 'BuildReporter'`.

- [ ] **Step 3: Refactor `progress.py` — extract base, keep Reporter, add BuildReporter**

Replace the entire contents of `src/vtextract/progress.py` with:
```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)


class ProgressReporter:
    """Shared progress plumbing: a single 'overall' bar plus plain status lines.

    The only place that knows about ``rich``. When ``enabled`` is false (the
    default off a TTY) the live bar is disabled and only the plain status lines
    are emitted, so piped output stays clean. ``console`` and ``enabled`` are
    injectable for testing. Used as a context manager around a loop.
    """

    def __init__(self, *, console: Console | None = None, enabled: bool | None = None) -> None:
        self.console = console or Console(stderr=True)
        self.enabled = self.console.is_terminal if enabled is None else enabled
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=self.console,
            disable=not self.enabled,
        )
        self._overall: int | None = None

    def __enter__(self):
        self.progress.__enter__()
        return self

    def __exit__(self, *exc) -> None:
        self.progress.__exit__(*exc)

    def _say(self, message: str) -> None:
        # Literal output: don't let ids or exception reprs be read as markup.
        self.console.print(message, markup=False, highlight=False)

    def _begin_overall(self, n: int, description: str = "overall") -> None:
        if self._overall is None:
            self._overall = self.progress.add_task(description, total=n)
        else:
            self.progress.update(self._overall, total=n)

    def advance(self) -> None:
        if self._overall is not None:
            self.progress.advance(self._overall)


class Reporter(ProgressReporter):
    """Live progress + status output for the fetch loop.

    Renders two bars — overall progress across resources and per-page progress
    within the current resource — and prints fetching/done/skipping/failed
    status lines above them.
    """

    def __init__(self, *, console: Console | None = None, enabled: bool | None = None) -> None:
        super().__init__(console=console, enabled=enabled)
        self._item: int | None = None

    def set_total(self, n: int, noun: str = "matches") -> None:
        """Announce the count and size the overall bar."""
        self._say(f"Found {n} {noun}.")
        self._begin_overall(n)

    def start_item(self, label) -> None:
        self._say(f"fetching {label}...")
        if self._item is None:
            self._item = self.progress.add_task(str(label), total=None)
        else:
            self.progress.reset(self._item, total=None, description=str(label))

    def item_pages(self, n: int) -> None:
        if self._item is not None:
            self.progress.update(self._item, total=n, completed=0)

    def page_done(self) -> None:
        if self._item is not None:
            self.progress.advance(self._item)

    def item_done(self, label) -> None:
        self._say(f"done {label}")
        self.advance()

    def skip(self, label) -> None:
        self._say(f"skipping {label}, already archived")
        self.advance()

    def fail(self, label, exc: BaseException) -> None:
        self._say(f"FAILED {label}: {exc!r}")
        self.advance()

    def finish(self, completed: int, failed: int) -> None:
        self._say(f"finished: {completed} archived, {failed} failed")


class BuildReporter(ProgressReporter):
    """Live progress + status output for the index build loop (one bar)."""

    def start(self, total: int) -> None:
        self._say(f"Indexing {total} files.")
        self._begin_overall(total, description="indexing")

    def finish(
        self, *, added: int, updated: int, removed: int, unchanged: int, skipped: int
    ) -> None:
        self._say(
            f"indexed: {added} added, {updated} updated, {removed} removed, "
            f"{unchanged} unchanged, {skipped} skipped"
        )
```

- [ ] **Step 4: Run the progress tests to verify all pass**

Run: `.venv/bin/python -m pytest tests/test_progress.py tests/index/test_build_reporter.py -v`
Expected: all PASS (existing `Reporter` behavior unchanged; `BuildReporter` works).

- [ ] **Step 5: Run the full suite to confirm no fetch regressions**

Run: `.venv/bin/python -m pytest -q`
Expected: all PASS (the extractor's `cli`/`fetcher` use `Reporter` unchanged).

- [ ] **Step 6: Commit**

```bash
git add src/vtextract/progress.py tests/index/test_build_reporter.py
git commit -m "refactor: extract ProgressReporter base; add BuildReporter for index build"
```

---

## Task 2: Index subpackage scaffold + models

**Files:**
- Create: `src/vtextract/index/__init__.py`, `src/vtextract/index/models.py`
- Create: `tests/index/__init__.py` (empty, so the test package imports cleanly)
- Test: `tests/index/test_models.py`

- [ ] **Step 1: Write the failing test**

Create `tests/index/test_models.py`:
```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from vtextract.index.models import (
    BuildStats,
    ItemRow,
    PageLink,
    SearchQuery,
    SearchResult,
    VolumeInfo,
    VolumeRow,
)


def test_item_row_defaults():
    row = ItemRow(isadg_id=1, reference_code="R", title="T", description="D", repository="Repo")
    assert row.content_begin is None and row.created_end is None
    assert row.volumes == [] and row.pages == []
    assert row.path == "items/1"


def test_search_query_defaults():
    q = SearchQuery()
    assert q.text is None
    assert q.fields == ("title", "description", "transcription")
    assert q.date_type == "content"
    assert q.limit == 50
    assert q.volume is None


def test_build_stats_total():
    s = BuildStats(added=2, updated=1, removed=0, unchanged=5, skipped=1)
    # processed = files looked at this build = added + updated + unchanged + skipped
    assert s.processed == 9


def test_search_result_roundtrip_fields():
    r = SearchResult(
        isadg_id=1, title="T", reference_code="R", repository="Repo",
        content_date="1737-05-06", created_date=None,
        matched_fields=["title"], matched_pages=[("208925", "p.jpg")],
        score=1.5, path="items/1",
    )
    assert r.matched_pages == [("208925", "p.jpg")]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/index/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vtextract.index'`.

- [ ] **Step 3: Create the package and models**

Create `src/vtextract/index/__init__.py`:
```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved
```

Create `tests/index/__init__.py`:
```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved
```

Create `src/vtextract/index/models.py`:
```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PageLink:
    """An item's reference to a physical page."""

    root_id: str
    page_key: str
    role: str  # "primary" | "context"


@dataclass
class ItemRow:
    """A catalogued resource, flattened for indexing."""

    isadg_id: int
    reference_code: str
    title: str
    description: str
    repository: str | None
    content_begin: str | None = None
    content_end: str | None = None
    created_begin: str | None = None
    created_end: str | None = None
    volumes: list[str] = field(default_factory=list)
    pages: list[PageLink] = field(default_factory=list)

    @property
    def path(self) -> str:
        return f"items/{self.isadg_id}"


@dataclass
class VolumeRow:
    root_id: str
    label: str | None
    reference_code: str | None


@dataclass
class SearchQuery:
    text: str | None = None
    fields: tuple[str, ...] = ("title", "description", "transcription")
    date_from: str | None = None  # ISO YYYY-MM-DD (inclusive lower bound)
    date_to: str | None = None    # ISO YYYY-MM-DD (inclusive upper bound)
    date_type: str = "content"    # "content" | "created"
    volume: str | None = None
    limit: int = 50


@dataclass
class SearchResult:
    isadg_id: int
    title: str
    reference_code: str
    repository: str | None
    content_date: str | None
    created_date: str | None
    matched_fields: list[str]
    matched_pages: list[tuple[str, str]]  # (root_id, page_key)
    score: float
    path: str


@dataclass
class VolumeInfo:
    root_id: str
    label: str | None
    reference_code: str | None
    item_count: int


@dataclass
class BuildStats:
    added: int = 0
    updated: int = 0
    removed: int = 0
    unchanged: int = 0
    skipped: int = 0

    @property
    def processed(self) -> int:
        """Source files looked at this build (excludes vanished/removed)."""
        return self.added + self.updated + self.unchanged + self.skipped
```

- [ ] **Step 4: Run it to verify it passes**

Run: `.venv/bin/python -m pytest tests/index/test_models.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/index/__init__.py src/vtextract/index/models.py tests/index/__init__.py tests/index/test_models.py
git commit -m "feat: add vtextract.index package scaffold and dataclasses"
```

---

## Task 3: `db.py` — connection, schema, FTS5 detection

**Files:**
- Create: `src/vtextract/index/db.py`
- Test: `tests/index/test_db_schema.py`

- [ ] **Step 1: Write the failing test**

Create `tests/index/test_db_schema.py`:
```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import sqlite3

import pytest

from vtextract.index.db import IndexDB, SCHEMA_VERSION, SchemaMismatch, fts5_available


def test_fts5_available_true_on_this_interpreter():
    assert fts5_available() is True


def test_open_creates_schema_and_version(tmp_path):
    db_path = tmp_path / "index" / "vtindex.sqlite3"
    with IndexDB(db_path) as db:
        assert db.get_meta("schema_version") == str(SCHEMA_VERSION)
        tables = {
            r[0]
            for r in db._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"meta", "item", "volume", "page", "item_volume", "item_page",
                "source_file", "transcription_map"} <= tables
    assert db_path.exists()  # parent dir created


def test_reopen_same_version_keeps_data(tmp_path):
    db_path = tmp_path / "index" / "vtindex.sqlite3"
    with IndexDB(db_path) as db:
        db.set_meta("probe", "1")
    with IndexDB(db_path) as db:
        assert db.get_meta("probe") == "1"


def test_version_mismatch_raises(tmp_path):
    db_path = tmp_path / "index" / "vtindex.sqlite3"
    with IndexDB(db_path) as db:
        db.set_meta("schema_version", "0")
    with pytest.raises(SchemaMismatch):
        IndexDB(db_path)


def test_rebuild_drops_and_recreates(tmp_path):
    db_path = tmp_path / "index" / "vtindex.sqlite3"
    with IndexDB(db_path) as db:
        db.set_meta("probe", "1")
    with IndexDB(db_path, rebuild=True) as db:
        assert db.get_meta("probe") is None
        assert db.get_meta("schema_version") == str(SCHEMA_VERSION)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/index/test_db_schema.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vtextract.index.db'`.

- [ ] **Step 3: Implement `db.py` (connection + schema only)**

Create `src/vtextract/index/db.py`:
```python
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
```

- [ ] **Step 4: Run it to verify it passes**

Run: `.venv/bin/python -m pytest tests/index/test_db_schema.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/index/db.py tests/index/test_db_schema.py
git commit -m "feat: add IndexDB connection, schema, and FTS5 detection"
```

---

## Task 4: Test fixture archive

A small, committed archive used by reader/builder/query/cli tests. It must exercise: multiple volumes, an item spanning two volumes, a page shared by two items, an item with no transcription on disk, an item missing `createdDate`, and one malformed metadata file (added later in Task 7, not here).

**Files:**
- Create fixture files under `tests/fixtures/archive/`
- Test: `tests/index/test_fixture_sanity.py`

- [ ] **Step 1: Write the failing sanity test**

Create `tests/index/test_fixture_sanity.py`:
```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import json
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "archive"


def test_fixture_archive_has_expected_items_and_pages():
    items = sorted(p.name for p in (FIXTURE / "items").iterdir())
    assert items == ["100", "200", "300"]
    # volume.json present for both volumes
    assert (FIXTURE / "pages" / "volA" / "volume.json").exists()
    assert (FIXTURE / "pages" / "volB" / "volume.json").exists()
    # item 100 references a page that has transcription text on disk
    meta = json.loads((FIXTURE / "items" / "100" / "metadata.json").read_text())
    assert meta["isadgID"] == 100
    primary = [p for p in meta["pages"] if p["role"] == "primary"]
    assert primary and (
        FIXTURE / "pages" / primary[0]["root_id"] / f'{primary[0]["page_key"]}.txt'
    ).exists()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/index/test_fixture_sanity.py -v`
Expected: FAIL (fixture files do not exist).

- [ ] **Step 3: Create the fixture files**

Create `tests/fixtures/archive/items/100/metadata.json`:
```json
{
  "isadgID": 100,
  "referenceCode": "FIX 1/A/1",
  "title": "Will of HOUSTON, JOHN, Dublin, merchant, created 1737",
  "pages": [
    {"page_key": "volA_p1.jpg", "root_id": "volA", "role": "primary",
     "path": "pages/volA/volA_p1.jpg", "canvas_label": "p1"},
    {"page_key": "volA_p0.jpg", "root_id": "volA", "role": "context",
     "path": "pages/volA/volA_p0.jpg", "canvas_label": "p0"}
  ],
  "searchHit": {
    "documentRepositoryName": "Registry of Deeds",
    "displayTitle": "Will of HOUSTON, JOHN, Dublin, merchant, created 1737",
    "contentDate": {"gte": "1737-05-06", "lte": "1737-05-06"},
    "createdDate": {"gte": "1737-01-18", "lte": "1737-01-18"},
    "scopeAndContent": ["Mentions a seal and a memorial in Dublin."],
    "archivalHistory": ["Abstract of a will from the Registry of Deeds."],
    "archivistsNote": [], "administrativeOrBiographicalHistory": [], "note": []
  },
  "detail": null
}
```

Create `tests/fixtures/archive/items/200/metadata.json` (shares `volA_p1.jpg` with item 100; also spans `volB`):
```json
{
  "isadgID": 200,
  "referenceCode": "FIX 1/A/2",
  "title": "Deed of MITCHELL, ROSE, Cork, spinster, created 1751",
  "pages": [
    {"page_key": "volA_p1.jpg", "root_id": "volA", "role": "primary",
     "path": "pages/volA/volA_p1.jpg", "canvas_label": "p1"},
    {"page_key": "volB_p5.jpg", "root_id": "volB", "role": "primary",
     "path": "pages/volB/volB_p5.jpg", "canvas_label": "p5"}
  ],
  "searchHit": {
    "documentRepositoryName": "Public Record Office of Northern Ireland",
    "displayTitle": "Deed of MITCHELL, ROSE, Cork, spinster, created 1751",
    "contentDate": {"gte": "1751-03-01", "lte": "1751-03-01"},
    "createdDate": {"gte": "1751-02-01", "lte": "1751-02-01"},
    "scopeAndContent": ["A deed concerning land near Cork."],
    "archivalHistory": [], "archivistsNote": ["Curated 2025."],
    "administrativeOrBiographicalHistory": [], "note": []
  },
  "detail": null
}
```

Create `tests/fixtures/archive/items/300/metadata.json` (no transcription on disk; no `createdDate`):
```json
{
  "isadgID": 300,
  "referenceCode": "FIX 2/B/1",
  "title": "Grant of land, Galway, 1689",
  "pages": [
    {"page_key": "volB_p9.jpg", "root_id": "volB", "role": "primary",
     "path": "pages/volB/volB_p9.jpg", "canvas_label": "p9"}
  ],
  "searchHit": {
    "documentRepositoryName": "National Archives, Ireland",
    "displayTitle": "Grant of land, Galway, 1689",
    "contentDate": {"gte": "1689-01-01", "lte": "1689-12-31"},
    "scopeAndContent": ["A grant of land in Galway."],
    "archivalHistory": [], "archivistsNote": [],
    "administrativeOrBiographicalHistory": [], "note": []
  },
  "detail": null
}
```

Create `tests/fixtures/archive/pages/volA/volume.json`:
```json
{"label": "Registry of Deeds Transcript Book 86", "reference_code": "IMC 1954/RoD/1/86"}
```

Create `tests/fixtures/archive/pages/volB/volume.json`:
```json
{"label": "PRONI Deeds Volume 25", "reference_code": "PRONI D4164/A/25"}
```

Create `tests/fixtures/archive/pages/volA/volA_p1.jpg.txt`:
```
John Houston of Dublin, merchant. His seal and memorial.
A neighbouring abstract for Rose Mitchell appears on this page.
```

Create `tests/fixtures/archive/pages/volA/volA_p0.jpg.txt`:
```
Context page preceding the Houston will.
```

Create `tests/fixtures/archive/pages/volB/volB_p5.jpg.txt`:
```
Deed of Rose Mitchell concerning land near Cork.
```

(Note: item 300's page `volB/volB_p9.jpg.txt` is intentionally NOT created — it exercises absent transcription.)

- [ ] **Step 4: Run the sanity test to verify it passes**

Run: `.venv/bin/python -m pytest tests/index/test_fixture_sanity.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/archive tests/index/test_fixture_sanity.py
git commit -m "test: add fixture archive for index tests"
```

---

## Task 5: `reader.py` — pure archive parsing

**Files:**
- Create: `src/vtextract/index/reader.py`
- Test: `tests/index/test_reader.py`

- [ ] **Step 1: Write the failing test**

Create `tests/index/test_reader.py`:
```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from pathlib import Path

from vtextract.index.reader import (
    compose_description,
    date_bounds,
    read_item,
    read_transcription,
    read_volume,
)

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "archive"


def test_read_item_core_fields():
    row = read_item(FIXTURE / "items" / "100" / "metadata.json")
    assert row.isadg_id == 100
    assert row.reference_code == "FIX 1/A/1"
    assert row.repository == "Registry of Deeds"
    assert "Houston" in row.title or "HOUSTON" in row.title
    assert row.content_begin == "1737-05-06" and row.content_end == "1737-05-06"
    assert row.created_begin == "1737-01-18"
    assert row.path == "items/100"


def test_read_item_description_concatenates_fields():
    row = read_item(FIXTURE / "items" / "100" / "metadata.json")
    assert "seal and a memorial" in row.description
    assert "Abstract of a will" in row.description


def test_read_item_volumes_and_pages():
    row = read_item(FIXTURE / "items" / "200" / "metadata.json")
    assert set(row.volumes) == {"volA", "volB"}
    primary = [p for p in row.pages if p.role == "primary"]
    assert {(p.root_id, p.page_key) for p in primary} == {
        ("volA", "volA_p1.jpg"), ("volB", "volB_p5.jpg")
    }


def test_read_item_missing_created_date_is_none():
    row = read_item(FIXTURE / "items" / "300" / "metadata.json")
    assert row.created_begin is None and row.created_end is None
    assert row.content_begin == "1689-01-01" and row.content_end == "1689-12-31"


def test_date_bounds_content_and_created():
    hit = {
        "contentDate": {"gte": "1737-05-06", "lte": "1737-05-06"},
        "createdDate": {"gte": "1737-01-18", "lte": "1737-01-18"},
    }
    assert date_bounds(hit, "content") == ("1737-05-06", "1737-05-06")
    assert date_bounds(hit, "created") == ("1737-01-18", "1737-01-18")
    assert date_bounds({}, "content") == (None, None)


def test_compose_description_skips_empty_lists():
    hit = {
        "scopeAndContent": ["A.", "B."],
        "archivalHistory": [],
        "note": ["C."],
    }
    assert compose_description(hit) == "A.\nB.\nC."


def test_read_volume():
    vol = read_volume(FIXTURE / "pages" / "volA" / "volume.json", root_id="volA")
    assert vol.root_id == "volA"
    assert vol.label == "Registry of Deeds Transcript Book 86"
    assert vol.reference_code == "IMC 1954/RoD/1/86"


def test_read_transcription_reads_text():
    text = read_transcription(FIXTURE / "pages" / "volA" / "volA_p1.jpg.txt")
    assert "John Houston of Dublin" in text
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/index/test_reader.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vtextract.index.reader'`.

- [ ] **Step 3: Implement `reader.py`**

Create `src/vtextract/index/reader.py`:
```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

import json
from pathlib import Path

from vtextract.index.models import ItemRow, PageLink, VolumeRow

# Description is composed from these searchHit fields, in this order. Each is a
# list of strings on the search hit (may be empty or absent).
_DESCRIPTION_FIELDS = (
    "scopeAndContent",
    "archivalHistory",
    "archivistsNote",
    "administrativeOrBiographicalHistory",
    "note",
)


def compose_description(search_hit: dict) -> str:
    """Join the free-text description fields into one newline-separated blob."""
    parts: list[str] = []
    for field in _DESCRIPTION_FIELDS:
        for value in search_hit.get(field) or []:
            if value:
                parts.append(str(value))
    return "\n".join(parts)


def date_bounds(search_hit: dict, kind: str) -> tuple[str | None, str | None]:
    """Return (begin, end) ISO dates for kind in {"content", "created"}."""
    key = "contentDate" if kind == "content" else "createdDate"
    span = search_hit.get(key) or {}
    return span.get("gte"), span.get("lte")


def read_item(meta_path: Path) -> ItemRow:
    """Parse an items/<id>/metadata.json into an ItemRow."""
    data = json.loads(Path(meta_path).read_text())
    hit = data.get("searchHit") or {}
    pages = [
        PageLink(root_id=str(p["root_id"]), page_key=p["page_key"], role=p.get("role", "primary"))
        for p in data.get("pages") or []
    ]
    content_begin, content_end = date_bounds(hit, "content")
    created_begin, created_end = date_bounds(hit, "created")
    volumes: list[str] = []
    for p in pages:
        if p.root_id not in volumes:
            volumes.append(p.root_id)
    return ItemRow(
        isadg_id=int(data["isadgID"]),
        reference_code=data.get("referenceCode") or "",
        title=data.get("title") or hit.get("displayTitle") or "",
        description=compose_description(hit),
        repository=hit.get("documentRepositoryName"),
        content_begin=content_begin,
        content_end=content_end,
        created_begin=created_begin,
        created_end=created_end,
        volumes=volumes,
        pages=pages,
    )


def read_volume(volume_path: Path, *, root_id: str) -> VolumeRow:
    data = json.loads(Path(volume_path).read_text())
    return VolumeRow(
        root_id=root_id,
        label=data.get("label"),
        reference_code=data.get("reference_code"),
    )


def read_transcription(txt_path: Path) -> str:
    return Path(txt_path).read_text()
```

- [ ] **Step 4: Run it to verify it passes**

Run: `.venv/bin/python -m pytest tests/index/test_reader.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/index/reader.py tests/index/test_reader.py
git commit -m "feat: add reader for parsing archive files into index rows"
```

---

## Task 6: `db.py` — write/fingerprint/count methods

Adds the mutation and bookkeeping methods the builder needs. SQL stays in `db.py`.

**Files:**
- Modify: `src/vtextract/index/db.py`
- Test: `tests/index/test_db_write.py`

- [ ] **Step 1: Write the failing test**

Create `tests/index/test_db_write.py`:
```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from vtextract.index.db import IndexDB
from vtextract.index.models import ItemRow, PageLink, VolumeRow


def _db(tmp_path):
    return IndexDB(tmp_path / "index" / "vtindex.sqlite3")


def _item(**kw):
    base = dict(
        isadg_id=100, reference_code="R", title="Houston will", description="a seal",
        repository="RoD", content_begin="1737-05-06", content_end="1737-05-06",
        volumes=["volA"], pages=[PageLink("volA", "volA_p1.jpg", "primary")],
    )
    base.update(kw)
    return ItemRow(**base)


def test_upsert_item_inserts_rows_and_fts(tmp_path):
    with _db(tmp_path) as db:
        db.upsert_item(_item(), fingerprint=("items/100/metadata.json", 1.0, 10))
        assert db.counts()["items"] == 1
        assert db.counts()["item_volume"] == 1
        assert db.counts()["item_page"] == 1
        # item_fts row keyed by isadg_id
        hit = {r["rowid"]: r for r in db._conn.execute(
            "SELECT rowid, title FROM item_fts WHERE item_fts MATCH ?", ("houston",))}
        assert 100 in hit


def test_upsert_item_replaces_on_reindex(tmp_path):
    with _db(tmp_path) as db:
        db.upsert_item(_item(), fingerprint=("items/100/metadata.json", 1.0, 10))
        db.upsert_item(
            _item(title="Changed title", volumes=["volB"],
                  pages=[PageLink("volB", "volB_p5.jpg", "primary")]),
            fingerprint=("items/100/metadata.json", 2.0, 12),
        )
        assert db.counts()["items"] == 1
        assert db.counts()["item_volume"] == 1
        rows = list(db._conn.execute("SELECT root_id FROM item_volume WHERE isadg_id=100"))
        assert rows[0]["root_id"] == "volB"
        old = list(db._conn.execute(
            "SELECT rowid FROM item_fts WHERE item_fts MATCH ?", ("Houston",)))
        assert old == []  # old title text gone


def test_upsert_volume_and_transcription(tmp_path):
    with _db(tmp_path) as db:
        db.upsert_volume(VolumeRow("volA", "Vol A", "REF-A"),
                         fingerprint=("pages/volA/volume.json", 1.0, 5))
        db.upsert_transcription("volA", "volA_p1.jpg", "Houston of Dublin",
                                fingerprint=("pages/volA/volA_p1.jpg.txt", 1.0, 9))
        assert db.counts()["volumes"] == 1
        assert db.counts()["pages"] == 1
        rows = list(db._conn.execute(
            "SELECT tm.root_id, tm.page_key FROM transcription_fts f "
            "JOIN transcription_map tm ON tm.rowid = f.rowid "
            "WHERE transcription_fts MATCH ?", ("dublin",)))
        assert (rows[0]["root_id"], rows[0]["page_key"]) == ("volA", "volA_p1.jpg")


def test_fingerprints_and_delete_source(tmp_path):
    with _db(tmp_path) as db:
        db.upsert_item(_item(), fingerprint=("items/100/metadata.json", 1.5, 10))
        fps = db.fingerprints()
        assert fps["items/100/metadata.json"] == (1.5, 10)
        db.delete_source("items/100/metadata.json")
        assert db.counts()["items"] == 0
        assert "items/100/metadata.json" not in db.fingerprints()


def test_delete_transcription_source_removes_fts(tmp_path):
    with _db(tmp_path) as db:
        db.upsert_transcription("volA", "volA_p1.jpg", "Houston",
                                fingerprint=("pages/volA/volA_p1.jpg.txt", 1.0, 7))
        db.delete_source("pages/volA/volA_p1.jpg.txt")
        assert db.counts()["pages"] == 0
        assert list(db._conn.execute("SELECT * FROM transcription_map")) == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/index/test_db_write.py -v`
Expected: FAIL with `AttributeError: 'IndexDB' object has no attribute 'upsert_item'`.

- [ ] **Step 3: Add the write methods to `db.py`**

Append these methods inside the `IndexDB` class in `src/vtextract/index/db.py` (after `get_meta`):
```python
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
```

- [ ] **Step 4: Run it to verify it passes**

Run: `.venv/bin/python -m pytest tests/index/test_db_write.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/index/db.py tests/index/test_db_write.py
git commit -m "feat: add IndexDB upsert/delete/fingerprint/count methods"
```

---

## Task 7: `builder.py` — incremental build

**Files:**
- Create: `src/vtextract/index/builder.py`
- Modify: `tests/fixtures/archive/` (add one malformed metadata item for the skip test — created inside the test via tmp copy, not committed broken)
- Test: `tests/index/test_builder.py`

- [ ] **Step 1: Write the failing test**

Create `tests/index/test_builder.py`:
```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import shutil
from pathlib import Path

from vtextract.index.builder import build
from vtextract.index.db import IndexDB

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "archive"


def _copy_archive(tmp_path) -> Path:
    dest = tmp_path / "archive"
    shutil.copytree(FIXTURE, dest)
    return dest


def test_full_build_indexes_everything(tmp_path):
    archive = _copy_archive(tmp_path)
    stats = build(archive)
    # 3 items + 2 volume.json + 3 transcription .txt (volA_p1, volA_p0, volB_p5) = 8
    assert stats.added == 8
    with IndexDB(archive / "index" / "vtindex.sqlite3") as db:
        c = db.counts()
    assert c["items"] == 3
    assert c["volumes"] == 2
    assert c["pages"] == 3  # one page row per transcription on disk


def test_incremental_skips_unchanged(tmp_path):
    archive = _copy_archive(tmp_path)
    build(archive)
    stats2 = build(archive)
    assert stats2.added == 0 and stats2.updated == 0 and stats2.removed == 0
    assert stats2.unchanged > 0


def test_incremental_detects_change(tmp_path):
    archive = _copy_archive(tmp_path)
    build(archive)
    meta = archive / "items" / "300" / "metadata.json"
    text = meta.read_text().replace("Galway", "Mayo")
    meta.write_text(text)
    # bump mtime to be safe across fast filesystems
    import os, time
    os.utime(meta, (time.time() + 5, time.time() + 5))
    stats = build(archive)
    assert stats.updated == 1
    with IndexDB(archive / "index" / "vtindex.sqlite3") as db:
        rows = list(db._conn.execute(
            "SELECT rowid FROM item_fts WHERE item_fts MATCH ?", ("Mayo",)))
    assert rows and rows[0]["rowid"] == 300


def test_incremental_removes_vanished(tmp_path):
    archive = _copy_archive(tmp_path)
    build(archive)
    shutil.rmtree(archive / "items" / "300")
    stats = build(archive)
    assert stats.removed == 1
    with IndexDB(archive / "index" / "vtindex.sqlite3") as db:
        assert db.counts()["items"] == 2


def test_malformed_metadata_is_skipped(tmp_path):
    archive = _copy_archive(tmp_path)
    (archive / "items" / "999").mkdir()
    (archive / "items" / "999" / "metadata.json").write_text("{ not json")
    stats = build(archive)
    assert stats.skipped == 1
    with IndexDB(archive / "index" / "vtindex.sqlite3") as db:
        assert db.counts()["items"] == 3  # the 3 good ones only


def test_rebuild_flag_starts_fresh(tmp_path):
    archive = _copy_archive(tmp_path)
    build(archive)
    stats = build(archive, rebuild=True)
    assert stats.added > 0 and stats.unchanged == 0
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/index/test_builder.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vtextract.index.builder'`.

- [ ] **Step 3: Implement `builder.py`**

Create `src/vtextract/index/builder.py`:
```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from pathlib import Path

from vtextract.index.db import IndexDB
from vtextract.index.models import BuildStats
from vtextract.index.reader import read_item, read_transcription, read_volume

INDEX_RELPATH = Path("index") / "vtindex.sqlite3"


def _candidates(archive: Path) -> list[tuple[str, str, Path]]:
    """Return (kind, relpath, abspath) for every source file in the archive."""
    out: list[tuple[str, str, Path]] = []
    items_dir = archive / "items"
    if items_dir.is_dir():
        for meta in sorted(items_dir.glob("*/metadata.json")):
            out.append(("item", f"items/{meta.parent.name}/metadata.json", meta))
    pages_dir = archive / "pages"
    if pages_dir.is_dir():
        for vol in sorted(pages_dir.glob("*/volume.json")):
            out.append(("volume", f"pages/{vol.parent.name}/volume.json", vol))
        for txt in sorted(pages_dir.glob("*/*.jpg.txt")):
            out.append(("transcription", f"pages/{txt.parent.name}/{txt.name}", txt))
    return out


def build(archive, *, rebuild: bool = False, reporter=None) -> BuildStats:
    """(Re)build the index from the archive. Incremental unless rebuild=True."""
    archive = Path(archive)
    db = IndexDB(archive / INDEX_RELPATH, rebuild=rebuild)
    stats = BuildStats()
    try:
        candidates = _candidates(archive)
        fingerprints = db.fingerprints()
        seen: set[str] = set()
        if reporter is not None:
            reporter.start(len(candidates))
        for kind, relpath, abspath in candidates:
            seen.add(relpath)
            st = abspath.stat()
            fp = (st.st_mtime, st.st_size)
            prior = fingerprints.get(relpath)
            if prior == fp:
                stats.unchanged += 1
                if reporter is not None:
                    reporter.advance()
                continue
            try:
                _index_one(db, kind, relpath, abspath, st)
            except Exception:
                stats.skipped += 1
                if reporter is not None:
                    reporter.advance()
                continue
            if prior is None:
                stats.added += 1
            else:
                stats.updated += 1
            if reporter is not None:
                reporter.advance()
        # prune vanished sources
        for relpath in set(fingerprints) - seen:
            db.delete_source(relpath)
            stats.removed += 1
        db.set_meta("item_count", str(db.counts()["items"]))
        db.commit()
    finally:
        if reporter is not None:
            reporter.finish(
                added=stats.added, updated=stats.updated, removed=stats.removed,
                unchanged=stats.unchanged, skipped=stats.skipped,
            )
        db.close()
    return stats


def _index_one(db: IndexDB, kind: str, relpath: str, abspath: Path, st) -> None:
    fp = (relpath, st.st_mtime, st.st_size)
    if kind == "item":
        db.upsert_item(read_item(abspath), fingerprint=fp)
    elif kind == "volume":
        root_id = abspath.parent.name
        db.upsert_volume(read_volume(abspath, root_id=root_id), fingerprint=fp)
    elif kind == "transcription":
        root_id = abspath.parent.name
        page_key = abspath.name[: -len(".txt")]  # strip .txt; page_key keeps .jpg
        db.upsert_transcription(root_id, page_key, read_transcription(abspath), fingerprint=fp)
```

- [ ] **Step 4: Run it to verify it passes**

Run: `.venv/bin/python -m pytest tests/index/test_builder.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/index/builder.py tests/index/test_builder.py
git commit -m "feat: add incremental index builder with stat fingerprints"
```

---

## Task 8: `db.py` search primitives + `query.py`

**Files:**
- Modify: `src/vtextract/index/db.py` (add search/volumes primitives)
- Create: `src/vtextract/index/query.py`
- Test: `tests/index/test_query.py`

- [ ] **Step 1: Write the failing test**

Create `tests/index/test_query.py`:
```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import shutil
from pathlib import Path

from vtextract.index.builder import build
from vtextract.index.db import IndexDB
from vtextract.index.models import SearchQuery
from vtextract.index.query import search

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "archive"


def _built(tmp_path) -> IndexDB:
    archive = tmp_path / "archive"
    shutil.copytree(FIXTURE, archive)
    build(archive)
    return IndexDB(archive / "index" / "vtindex.sqlite3")


def test_keyword_in_title(tmp_path):
    with _built(tmp_path) as db:
        results = search(db, SearchQuery(text="Houston", fields=("title",)))
    ids = [r.isadg_id for r in results]
    assert ids == [100]
    assert "title" in results[0].matched_fields


def test_keyword_in_description(tmp_path):
    with _built(tmp_path) as db:
        results = search(db, SearchQuery(text="memorial", fields=("description",)))
    assert [r.isadg_id for r in results] == [100]
    assert "description" in results[0].matched_fields


def test_keyword_in_transcription_resolves_to_items(tmp_path):
    # "Houston" appears in volA_p1.jpg.txt, a page shared by items 100 and 200.
    with _built(tmp_path) as db:
        results = search(db, SearchQuery(text="Houston", fields=("transcription",)))
    ids = sorted(r.isadg_id for r in results)
    assert ids == [100, 200]
    r100 = next(r for r in results if r.isadg_id == 100)
    assert ("volA", "volA_p1.jpg") in r100.matched_pages
    assert "transcription" in r100.matched_fields


def test_all_fields_default(tmp_path):
    with _built(tmp_path) as db:
        results = search(db, SearchQuery(text="Cork"))
    # "Cork" is in item 200 title+description and in volB_p5 transcription
    assert [r.isadg_id for r in results] == [200]


def test_date_filter_content_overlap(tmp_path):
    with _built(tmp_path) as db:
        results = search(db, SearchQuery(date_from="1700-01-01", date_to="1740-12-31"))
    ids = sorted(r.isadg_id for r in results)
    assert ids == [100]  # 1737 content date; 200 is 1751, 300 is 1689


def test_date_filter_year_bounds_via_iso(tmp_path):
    with _built(tmp_path) as db:
        results = search(db, SearchQuery(date_from="1689-01-01", date_to="1689-12-31"))
    assert [r.isadg_id for r in results] == [300]


def test_created_date_type(tmp_path):
    with _built(tmp_path) as db:
        results = search(
            db, SearchQuery(date_type="created", date_from="1737-01-01", date_to="1737-01-31"))
    assert [r.isadg_id for r in results] == [100]  # created 1737-01-18


def test_volume_filter(tmp_path):
    with _built(tmp_path) as db:
        results = search(db, SearchQuery(volume="volB"))
    ids = sorted(r.isadg_id for r in results)
    assert ids == [200, 300]  # both reference volB


def test_filter_only_no_text_returns_all_sorted_by_date(tmp_path):
    with _built(tmp_path) as db:
        results = search(db, SearchQuery())
    ids = [r.isadg_id for r in results]
    assert ids == [300, 100, 200]  # 1689, 1737, 1751 ascending by content_begin


def test_limit(tmp_path):
    with _built(tmp_path) as db:
        results = search(db, SearchQuery(limit=1))
    assert len(results) == 1


def test_keyword_and_date_combine(tmp_path):
    with _built(tmp_path) as db:
        results = search(
            db, SearchQuery(text="Houston", date_from="1900-01-01", date_to="1950-12-31"))
    assert results == []  # keyword matches 100 but date excludes it
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/index/test_query.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vtextract.index.query'`.

- [ ] **Step 3: Add search primitives to `db.py`**

Append these methods inside `IndexDB` in `src/vtextract/index/db.py`:
```python
    # --- search primitives ---

    def item_fts_search(self, text: str, fields: tuple[str, ...]) -> dict[int, float]:
        """Return {isadg_id: best bm25 score} for title/description FTS matches."""
        cols = [f for f in fields if f in ("title", "description")]
        if not cols:
            return {}
        match = "{" + " ".join(cols) + "} : " + text
        rows = self._conn.execute(
            "SELECT rowid, bm25(item_fts) AS score FROM item_fts "
            "WHERE item_fts MATCH ?",
            (match,),
        )
        return {r["rowid"]: r["score"] for r in rows}

    def transcription_fts_search(self, text: str) -> list[tuple[str, str, float]]:
        """Return [(root_id, page_key, score)] for transcription FTS matches."""
        rows = self._conn.execute(
            "SELECT tm.root_id AS root_id, tm.page_key AS page_key, "
            "bm25(transcription_fts) AS score FROM transcription_fts "
            "JOIN transcription_map tm ON tm.rowid = transcription_fts.rowid "
            "WHERE transcription_fts MATCH ?",
            (text,),
        )
        return [(r["root_id"], r["page_key"], r["score"]) for r in rows]

    def items_for_pages(self, pages: list[tuple[str, str]]) -> dict[int, list[tuple[str, str]]]:
        """Map matched (root_id,page_key) pages to the items that reference them."""
        out: dict[int, list[tuple[str, str]]] = {}
        for root_id, page_key in pages:
            for r in self._conn.execute(
                "SELECT isadg_id FROM item_page WHERE root_id=? AND page_key=?",
                (root_id, page_key),
            ):
                out.setdefault(r["isadg_id"], []).append((root_id, page_key))
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

    def volumes(self):
        """Return [(root_id, label, reference_code, item_count)] for all volumes."""
        return list(self._conn.execute(
            "SELECT v.root_id, v.label, v.reference_code, "
            "(SELECT COUNT(DISTINCT iv.isadg_id) FROM item_volume iv "
            " WHERE iv.root_id = v.root_id) AS item_count "
            "FROM volume v ORDER BY v.root_id"
        ))
```

- [ ] **Step 4: Implement `query.py`**

Create `src/vtextract/index/query.py`:
```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from vtextract.index.db import IndexDB
from vtextract.index.models import SearchQuery, SearchResult


def search(db: IndexDB, q: SearchQuery) -> list[SearchResult]:
    """Run a SearchQuery and return ordered SearchResults."""
    candidate_ids: set[int] | None = None
    scores: dict[int, float] = {}
    matched_fields: dict[int, set[str]] = {}
    matched_pages: dict[int, list[tuple[str, str]]] = {}

    if q.text:
        candidate_ids = set()
        # title/description
        for isadg_id, score in db.item_fts_search(q.text, q.fields).items():
            candidate_ids.add(isadg_id)
            _record_score(scores, isadg_id, score)
            # which of title/description we searched
            for f in q.fields:
                if f in ("title", "description"):
                    matched_fields.setdefault(isadg_id, set()).add(f)
        # transcription
        if "transcription" in q.fields:
            page_hits = db.transcription_fts_search(q.text)
            best_page_score = {(r, p): s for r, p, s in page_hits}
            pages = list(best_page_score)
            for isadg_id, pgs in db.items_for_pages(pages).items():
                candidate_ids.add(isadg_id)
                matched_fields.setdefault(isadg_id, set()).add("transcription")
                matched_pages.setdefault(isadg_id, []).extend(pgs)
                for pg in pgs:
                    _record_score(scores, isadg_id, best_page_score[pg])

    rows = db.filter_items(
        candidate_ids,
        date_type=q.date_type,
        date_from=q.date_from,
        date_to=q.date_to,
        volume=q.volume,
    )

    results: list[SearchResult] = []
    for row in rows:
        isadg_id = row["isadg_id"]
        results.append(
            SearchResult(
                isadg_id=isadg_id,
                title=row["title"],
                reference_code=row["reference_code"],
                repository=row["repository"],
                content_date=_fmt_date(row["content_begin"], row["content_end"]),
                created_date=_fmt_date(row["created_begin"], row["created_end"]),
                matched_fields=sorted(matched_fields.get(isadg_id, set())),
                matched_pages=matched_pages.get(isadg_id, []),
                score=scores.get(isadg_id, 0.0),
                path=row["path"],
            )
        )

    if q.text:
        # best (most negative) bm25 first; ties keep filter order (date asc)
        results.sort(key=lambda r: r.score)
    return results[: q.limit]


def _record_score(scores: dict[int, float], isadg_id: int, score: float) -> None:
    # bm25 is more-negative = better; keep the best (minimum).
    if isadg_id not in scores or score < scores[isadg_id]:
        scores[isadg_id] = score


def _fmt_date(begin: str | None, end: str | None) -> str | None:
    if not begin and not end:
        return None
    if begin == end:
        return begin
    return f"{begin}/{end}"
```

- [ ] **Step 5: Run it to verify it passes**

Run: `.venv/bin/python -m pytest tests/index/test_query.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/vtextract/index/db.py src/vtextract/index/query.py tests/index/test_query.py
git commit -m "feat: add search primitives and query composition"
```

---

## Task 9: `cli.py` — subcommands, output, exit codes

Exit codes (grep convention): `0` = success / ≥1 match, `1` = no matches, `2` = error/usage.

**Files:**
- Create: `src/vtextract/index/cli.py`
- Test: `tests/index/test_cli.py`

- [ ] **Step 1: Write the failing test**

Create `tests/index/test_cli.py`:
```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import json
import shutil
from pathlib import Path

from vtextract.index.cli import main

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "archive"


def _archive(tmp_path) -> Path:
    dest = tmp_path / "archive"
    shutil.copytree(FIXTURE, dest)
    return dest


def test_build_then_search_json_match(tmp_path, capsys):
    archive = _archive(tmp_path)
    assert main(["build", "--archive", str(archive)]) == 0
    capsys.readouterr()
    code = main(["search", "Houston", "--in", "title", "--archive", str(archive), "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert code == 0
    assert [r["isadg_id"] for r in payload] == [100]
    assert payload[0]["matched_fields"] == ["title"]


def test_search_no_match_exit_1(tmp_path, capsys):
    archive = _archive(tmp_path)
    main(["build", "--archive", str(archive)])
    capsys.readouterr()
    code = main(["search", "zzznotfound", "--archive", str(archive), "--json"])
    out = capsys.readouterr().out
    assert code == 1
    assert json.loads(out) == []


def test_search_missing_index_exit_2(tmp_path, capsys):
    archive = _archive(tmp_path)  # never built
    code = main(["search", "Houston", "--archive", str(archive)])
    err = capsys.readouterr().err
    assert code == 2
    assert "build" in err.lower()


def test_volumes_json(tmp_path, capsys):
    archive = _archive(tmp_path)
    main(["build", "--archive", str(archive)])
    capsys.readouterr()
    code = main(["volumes", "--archive", str(archive), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    roots = sorted(v["root_id"] for v in payload)
    assert roots == ["volA", "volB"]


def test_stats_json(tmp_path, capsys):
    archive = _archive(tmp_path)
    main(["build", "--archive", str(archive)])
    capsys.readouterr()
    code = main(["stats", "--archive", str(archive), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["items"] == 3
    assert payload["stale"] is False


def test_date_and_volume_filters(tmp_path, capsys):
    archive = _archive(tmp_path)
    main(["build", "--archive", str(archive)])
    capsys.readouterr()
    code = main(["search", "--from", "1689", "--to", "1689",
                 "--archive", str(archive), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert [r["isadg_id"] for r in payload] == [300]


def test_archive_from_env(tmp_path, capsys, monkeypatch):
    archive = _archive(tmp_path)
    monkeypatch.setenv("VT_ARCHIVE", str(archive))
    assert main(["build"]) == 0
    capsys.readouterr()
    assert main(["search", "Houston", "--in", "title", "--json"]) == 0


def test_stale_index_warns(tmp_path, capsys):
    archive = _archive(tmp_path)
    main(["build", "--archive", str(archive)])
    capsys.readouterr()
    # add a new item after build -> archive changed -> stale
    (archive / "items" / "400").mkdir()
    shutil.copy(archive / "items" / "300" / "metadata.json",
                archive / "items" / "400" / "metadata.json")
    code = main(["search", "Galway", "--in", "title", "--archive", str(archive), "--json"])
    err = capsys.readouterr().err
    assert code == 0
    assert "stale" in err.lower() or "build" in err.lower()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/index/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vtextract.index.cli'`.

- [ ] **Step 3: Implement `cli.py`**

Create `src/vtextract/index/cli.py`:
```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from vtextract.index.builder import INDEX_RELPATH, _candidates, build
from vtextract.index.db import Fts5Unavailable, IndexDB, SchemaMismatch
from vtextract.index.models import SearchQuery
from vtextract.index.query import search
from vtextract.progress import BuildReporter

_FIELD_CHOICES = ("title", "description", "transcription")


def _resolve_archive(value: str | None) -> Path:
    return Path(value or os.environ.get("VT_ARCHIVE") or "archive")


def _date_bound(value: str | None, *, upper: bool) -> str | None:
    """Normalize a CLI date bound to ISO. A bare year expands to Jan 1 / Dec 31."""
    if value is None:
        return None
    value = value.strip()
    if len(value) == 4 and value.isdigit():
        return f"{value}-12-31" if upper else f"{value}-01-01"
    return value


def _parse_fields(value: str | None) -> tuple[str, ...]:
    if not value:
        return _FIELD_CHOICES
    fields = tuple(f.strip() for f in value.split(",") if f.strip())
    bad = [f for f in fields if f not in _FIELD_CHOICES]
    if bad:
        raise argparse.ArgumentTypeError(
            f"unknown field(s): {', '.join(bad)}; choose from {', '.join(_FIELD_CHOICES)}"
        )
    return fields


def _is_stale(db: IndexDB, archive: Path) -> bool:
    """True if any source file is new/changed/removed vs the stored fingerprints."""
    fingerprints = db.fingerprints()
    seen: set[str] = set()
    for _kind, relpath, abspath in _candidates(archive):
        seen.add(relpath)
        st = abspath.stat()
        if fingerprints.get(relpath) != (st.st_mtime, st.st_size):
            return True
    return bool(set(fingerprints) - seen)


def _open_for_read(archive: Path) -> IndexDB:
    db_path = archive / INDEX_RELPATH
    if not db_path.exists():
        raise FileNotFoundError(
            f"no index at {db_path}; run `vtindex build --archive {archive}` first."
        )
    return IndexDB(db_path)


def _cmd_build(args) -> int:
    archive = _resolve_archive(args.archive)
    reporter = BuildReporter()
    build(archive, rebuild=args.rebuild, reporter=reporter)
    return 0


def _cmd_search(args) -> int:
    archive = _resolve_archive(args.archive)
    query = SearchQuery(
        text=args.query,
        fields=_parse_fields(args.in_fields),
        date_from=_date_bound(args.date_from, upper=False),
        date_to=_date_bound(args.date_to, upper=True),
        date_type=args.date_type,
        volume=args.volume,
        limit=args.limit,
    )
    with _open_for_read(archive) as db:
        if _is_stale(db, archive):
            print("warning: index is stale; run `vtindex build` to refresh.",
                  file=sys.stderr)
        results = search(db, query)
    if args.json:
        print(json.dumps([_result_dict(r) for r in results], indent=2))
    else:
        _print_results_table(results)
    return 0 if results else 1


def _cmd_volumes(args) -> int:
    archive = _resolve_archive(args.archive)
    with _open_for_read(archive) as db:
        rows = db.volumes()
    data = [
        {"root_id": r["root_id"], "label": r["label"],
         "reference_code": r["reference_code"], "item_count": r["item_count"]}
        for r in rows
    ]
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        for d in data:
            print(f'{d["root_id"]}\t{d["item_count"]:>4}\t{d["label"] or ""}\t'
                  f'{d["reference_code"] or ""}')
    return 0


def _cmd_stats(args) -> int:
    archive = _resolve_archive(args.archive)
    with _open_for_read(archive) as db:
        counts = db.counts()
        stale = _is_stale(db, archive)
        data = {
            "items": counts["items"],
            "volumes": counts["volumes"],
            "pages": counts["pages"],
            "schema_version": db.get_meta("schema_version"),
            "stale": stale,
        }
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        for k, v in data.items():
            print(f"{k}: {v}")
    return 0


def _result_dict(r) -> dict:
    return {
        "isadg_id": r.isadg_id,
        "title": r.title,
        "reference_code": r.reference_code,
        "repository": r.repository,
        "content_date": r.content_date,
        "created_date": r.created_date,
        "matched_fields": r.matched_fields,
        "matched_pages": [{"root_id": rt, "page_key": pk} for rt, pk in r.matched_pages],
        "score": r.score,
        "path": r.path,
    }


def _print_results_table(results) -> None:
    if not results:
        print("no matches")
        return
    for r in results:
        fields = ",".join(r.matched_fields) if r.matched_fields else "-"
        print(f'{r.isadg_id}\t{r.content_date or "-"}\t{r.reference_code}\t'
              f'{r.title}\t[{fields}]')


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vtindex",
        description="Build and search a local index over a vtextract archive.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="(re)build the index from the archive")
    p_build.add_argument("--archive", help="archive dir (default: $VT_ARCHIVE or ./archive)")
    p_build.add_argument("--rebuild", action="store_true", help="discard and rebuild fully")
    p_build.set_defaults(func=_cmd_build)

    p_search = sub.add_parser("search", help="search the index")
    p_search.add_argument("query", nargs="?", help="FTS5 keyword expression (optional)")
    p_search.add_argument("--archive")
    p_search.add_argument("--in", dest="in_fields",
                          help="comma list of: title,description,transcription (default: all)")
    p_search.add_argument("--from", dest="date_from", help="lower date bound (YEAR or ISO)")
    p_search.add_argument("--to", dest="date_to", help="upper date bound (YEAR or ISO)")
    p_search.add_argument("--date-type", choices=("content", "created"), default="content")
    p_search.add_argument("--volume", help="restrict to items referencing this volume root id")
    p_search.add_argument("--limit", type=int, default=50)
    p_search.add_argument("--json", action="store_true")
    p_search.set_defaults(func=_cmd_search)

    p_vol = sub.add_parser("volumes", help="list indexed volumes")
    p_vol.add_argument("--archive")
    p_vol.add_argument("--json", action="store_true")
    p_vol.set_defaults(func=_cmd_volumes)

    p_stats = sub.add_parser("stats", help="show index stats and staleness")
    p_stats.add_argument("--archive")
    p_stats.add_argument("--json", action="store_true")
    p_stats.set_defaults(func=_cmd_stats)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, SchemaMismatch, Fts5Unavailable) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except argparse.ArgumentTypeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
```

- [ ] **Step 4: Run it to verify it passes**

Run: `.venv/bin/python -m pytest tests/index/test_cli.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all PASS (existing + new).

- [ ] **Step 6: Commit**

```bash
git add src/vtextract/index/cli.py tests/index/test_cli.py
git commit -m "feat: add vtindex CLI (build/search/volumes/stats) with grep-style exit codes"
```

---

## Task 10: Entry point + docs

**Files:**
- Modify: `pyproject.toml`, `README.md`, `CLAUDE.md`

- [ ] **Step 1: Add the console-script entry point**

In `pyproject.toml`, under `[project.scripts]` (which currently has `vtextract = "vtextract.cli:main"`), add:
```toml
vtindex = "vtextract.index.cli:main"
```

- [ ] **Step 2: Reinstall so the entry point exists, then smoke-test the CLI end to end**

Run:
```bash
.venv/bin/python -m pip install -q -e ".[dev]"
.venv/bin/vtindex build --archive tests/fixtures/archive --rebuild
.venv/bin/vtindex search Houston --in title --archive tests/fixtures/archive --json
echo "exit=$?"
.venv/bin/vtindex search zzznotfound --archive tests/fixtures/archive --json; echo "exit=$?"
```
Expected: build prints an `indexed: ...` summary; the first search prints a JSON array containing item `100` and exits `0`; the second prints `[]` and exits `1`. (This writes `tests/fixtures/archive/index/` — delete it before committing in Step 4.)

- [ ] **Step 3: Document `vtindex` in README and CLAUDE.md**

In `README.md`, after the "Archive layout" section, add:
```markdown
## Searching the archive

`vtindex` builds a local SQLite/FTS5 index over an archive so you can search it
without re-reading every file. The index lives at `<archive>/index/`.

```bash
# build (or incrementally refresh) the index after a download
vtindex build --archive ./archive

# keyword search (title + description + transcription by default)
vtindex search "houston" --archive ./archive

# restrict fields, add a time frame and a volume, get JSON for scripting
vtindex search "deed" --in title,transcription \
  --from 1700 --to 1760 --date-type content --volume 208925 \
  --archive ./archive --json

# discover volume ids/labels, or inspect the index
vtindex volumes --archive ./archive
vtindex stats   --archive ./archive
```

The archive dir defaults to `$VT_ARCHIVE` or `./archive`. Exit codes follow the
grep convention: `0` = at least one match, `1` = no matches, `2` = error (e.g.
the index has not been built yet). Re-running `vtindex build` is incremental —
it only reads files whose size/mtime changed since the last build.
```

In `CLAUDE.md`, under the "Architecture" section, add a bullet group:
```markdown
- `index/` (subpackage) — the `vtindex` CLI. `db.py` is the **single SQL choke
  point** (SQLite + FTS5; analogous to `client.py`). `reader.py` is pure
  archive-file parsing (analogous to `schema.py`). `builder.py` does an
  incremental, stat-fingerprint build (analogous to `fetcher.py`). `query.py`
  composes a search from `db` primitives. `cli.py` wires `build`/`search`/
  `volumes`/`stats`. Build progress reuses `progress.BuildReporter`.
```
Also add to the "Running things" section:
```markdown
- **Index CLI:** `.venv/bin/vtindex build --archive ./archive` then
  `.venv/bin/vtindex search "<keyword>" --archive ./archive [--json]`.
```

- [ ] **Step 4: Remove the smoke-test index and commit**

Run:
```bash
rm -rf tests/fixtures/archive/index
git add pyproject.toml README.md CLAUDE.md
git commit -m "feat: register vtindex entry point and document the index CLI"
```

- [ ] **Step 5: Final full-suite run**

Run: `.venv/bin/python -m pytest -q`
Expected: all PASS.

---

## Done-when checklist

- [ ] `vtindex build` builds `<archive>/index/vtindex.sqlite3`; re-running is incremental (only changed files read).
- [ ] `vtindex search` supports keyword (`--in` over title/description/transcription), time frame (`--from`/`--to`, year or ISO, `--date-type`), and `--volume`; results are item-level and page-aware for transcription hits.
- [ ] `--json` output and grep-style exit codes (0 match / 1 no-match / 2 error) work.
- [ ] `vtindex volumes` and `vtindex stats` work; stats reports staleness.
- [ ] The extractor's existing `Reporter` behavior and tests are unchanged.
- [ ] FTS5-unavailable, missing-index, and schema-mismatch paths exit `2` with a clear message.
- [ ] Full test suite passes; no network or real credential is used.
```
