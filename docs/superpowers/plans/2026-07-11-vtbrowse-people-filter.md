# vtbrowse People Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "People" field to the vtbrowse search dialog that narrows results (AND) to items referencing a page where that person appears, intersected with the existing text/date/volume filters.

**Architecture:** The filter lives in the index layer's `query.search()`, reusing the existing `people_search()` (person FTS over canonical + aliases) and the existing `db.filter_items(candidate_ids, ...)` intersection path. A new `person` field flows: SearchDialog → SearchSpec → app.py → IndexClient.search() → SearchQuery → query.search(). The `tui/` → index boundary is preserved (TUI goes through `IndexService`/`IndexClient`, no new direct `db`/`query` imports).

**Tech Stack:** Python, uv, pytest, httpx.MockTransport (fixtures only), Textual (TUI).

## Global Constraints

- Tests run entirely against committed fixtures in `docs/examples/`; never hit the live site or use a real credential. Run with `uv run pytest`.
- TDD: failing test → see it fail → minimal implementation → see it pass → commit. Every feature commit pairs code with its test.
- Conventional commit messages (`feat:`).
- `tui/` never imports `vtextract.index.{db,query,builder}` directly; index access goes through `vtextract.index.service` (enforced by `tests/test_no_direct_db.py`).
- Keep files small and single-purpose; only `client.py` performs HTTP.
- Commit message trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

### Task 1: Add `person` filter to the index query layer

This is the core of the feature — the actual filtering. Everything else just threads the value here.

**Files:**
- Modify: `src/vtextract/index/models.py` (add `person` field to `SearchQuery`, ~line 87-95)
- Modify: `src/vtextract/index/query.py` (import `people_search`, add intersection block before `filter_items`, ~line 17-45)
- Test: `tests/index/test_query_person.py` (create) — or add to the existing query test module if one exists; check `tests/index/` first and follow the existing pattern.

**Interfaces:**
- Consumes: `people_search(db, name) -> list[PersonHit]` from `vtextract.index.people`; each `PersonHit` has `.items: list[int]` (isadg_ids referencing the page). `db.filter_items(ids, ...)` treats `ids=None` as "all", empty set as "none".
- Produces: `SearchQuery` now has field `person: str | None = None`. `query.search(db, q)` filters results to items referencing a page mentioning `q.person` when it is set.

**Before writing the test:** inspect `tests/index/` (or `tests/`) for the existing query-search test module and how it constructs an `IndexDB` from fixtures (there is an established pattern — a built index over `docs/examples/`). Reuse that fixture/builder setup exactly rather than inventing a new one. Pick a person name and an isadg_id that actually exist together in the fixture archive by inspecting the built index (e.g. run `people_search` over a broad name, or read a `.names.json` sidecar under the fixtures). Use real fixture values in the assertions below.

- [ ] **Step 1: Add the `person` field to `SearchQuery`**

In `src/vtextract/index/models.py`, in the `SearchQuery` dataclass, add the field (place it after `volume`):

```python
@dataclass
class SearchQuery:
    text: str | None = None
    fields: tuple[str, ...] = ("title", "description", "transcription")
    date_from: str | None = None  # ISO YYYY-MM-DD (inclusive lower bound)
    date_to: str | None = None    # ISO YYYY-MM-DD (inclusive upper bound)
    date_type: str = "content"    # "content" | "created"
    volume: str | None = None
    person: str | None = None     # narrow to items referencing a page mentioning this person
    limit: int = 50
    offset: int = 0
```

- [ ] **Step 2: Write the failing test**

Create `tests/index/test_query_person.py` (adapt imports/fixtures to the existing query-test pattern you found). Replace `PERSON_NAME`, `EXPECTED_ID`, and `TEXT_MATCH` with real fixture values:

```python
from vtextract.index.models import SearchQuery
from vtextract.index.query import search
from vtextract.index.people import people_search

# Use the same built-over-fixtures IndexDB fixture the other query tests use;
# assume it is available here as `db` (mirror the existing test's setup).

def test_person_only_returns_items_mentioning_person(db):
    q = SearchQuery(person=PERSON_NAME)
    results = search(db, q)
    ids = {r.isadg_id for r in results}
    assert EXPECTED_ID in ids
    # every result references a page where the person appears
    allowed = {i for h in people_search(db, PERSON_NAME) for i in h.items}
    assert ids <= allowed

def test_person_plus_text_is_intersection(db):
    ids_person = {r.isadg_id for r in search(db, SearchQuery(person=PERSON_NAME))}
    ids_text = {r.isadg_id for r in search(db, SearchQuery(text=TEXT_MATCH))}
    ids_both = {r.isadg_id for r in search(db, SearchQuery(text=TEXT_MATCH, person=PERSON_NAME))}
    assert ids_both == ids_person & ids_text

def test_unmatched_person_returns_empty(db):
    results = search(db, SearchQuery(person="Zzzqxwv Notaperson"))
    assert results == []

def test_blank_person_unchanged(db):
    with_field = search(db, SearchQuery(text=TEXT_MATCH, person=None))
    baseline = search(db, SearchQuery(text=TEXT_MATCH))
    assert [r.isadg_id for r in with_field] == [r.isadg_id for r in baseline]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/index/test_query_person.py -v`
Expected: FAIL — person filtering not implemented, so `test_person_only...`, `test_person_plus_text...`, and `test_unmatched_person...` fail (person-only returns all items; unmatched returns everything).

- [ ] **Step 4: Implement the filter in `query.search()`**

In `src/vtextract/index/query.py`, add the import at the top with the other imports:

```python
from vtextract.index.people import people_search
```

Then in `search()`, insert this block after the `if q.text:` candidate-building block and **before** the `rows = db.filter_items(...)` call:

```python
    if q.person:
        person_ids = {i for hit in people_search(db, q.person) for i in hit.items}
        candidate_ids = person_ids if candidate_ids is None else candidate_ids & person_ids
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/index/test_query_person.py -v`
Expected: PASS (all four)

- [ ] **Step 6: Run the full index test module to check for regressions**

Run: `uv run pytest tests/index/ -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/vtextract/index/models.py src/vtextract/index/query.py tests/index/test_query_person.py
git commit -m "feat: add person filter to index query layer

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Thread `person` through IndexClient.search()

**Files:**
- Modify: `src/vtextract/tui/index_client.py` (`search()` method, ~line 99-110)
- Test: `tests/tui/test_index_client.py` (add a test) — check `tests/tui/` for the existing index_client test module and pattern; if none, add to the closest existing TUI test that builds an index over fixtures.

**Interfaces:**
- Consumes: `SearchQuery(..., person=...)` from Task 1.
- Produces: `IndexClient.search(..., person: str | None = None)` passes `person` into the `SearchQuery`.

**Before writing the test:** find how existing `IndexClient` tests construct the client against a fixture archive (built index). Reuse it. If the simplest verification is that `person` reaches `SearchQuery`, prefer an end-to-end assertion (a `person=` search over fixtures returns the narrowed set) using the same real fixture values as Task 1.

- [ ] **Step 1: Write the failing test**

In the existing IndexClient test module (adapt fixture/async setup to match it):

```python
import pytest

@pytest.mark.asyncio
async def test_search_person_narrows_results(index_client):
    # index_client: an IndexClient over the fixture archive (mirror existing tests)
    person_ids = {r.isadg_id for r in await index_client.search(person=PERSON_NAME)}
    all_ids = {r.isadg_id for r in await index_client.search(query=TEXT_MATCH)}
    both = {r.isadg_id for r in await index_client.search(query=TEXT_MATCH, person=PERSON_NAME)}
    assert both == person_ids & all_ids
    assert both  # non-empty for the chosen fixture values
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/tui/test_index_client.py -v -k person`
Expected: FAIL — `search()` has no `person` parameter (`TypeError: unexpected keyword argument 'person'`).

- [ ] **Step 3: Add the parameter**

In `src/vtextract/tui/index_client.py`, update `search()`:

```python
    async def search(self, *, query: str | None = None,
                     fields: tuple[str, ...] | None = None,
                     date_from: str | None = None, date_to: str | None = None,
                     date_type: str = "content", volume: str | None = None,
                     person: str | None = None,
                     limit: int = 50, offset: int = 0):
        q = SearchQuery(
            text=query or None,
            fields=fields or ("title", "description", "transcription"),
            date_from=date_from, date_to=date_to, date_type=date_type,
            volume=volume, person=person, limit=limit, offset=offset,
        )
        return await self._call(lambda s: s.search(q))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/tui/test_index_client.py -v -k person`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/tui/index_client.py tests/tui/test_index_client.py
git commit -m "feat: thread person filter through IndexClient.search

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Add the People field to the search dialog + wire app.py

**Files:**
- Modify: `src/vtextract/tui/dialogs/search.py` (add `person` to `SearchSpec`, add `Input` to `compose()`, read in `_collect()`)
- Modify: `src/vtextract/tui/app.py` (`_on_search_submitted`, ~line 370-381: pass `person=spec.person`)
- Test: `tests/tui/` — add a `_collect()` test to the existing search-dialog test module (check for `tests/tui/test_search_dialog.py` or similar; follow its pattern for driving the ModalScreen).

**Interfaces:**
- Consumes: `IndexClient.search(..., person=...)` from Task 2.
- Produces: `SearchSpec` gains `person: str | None`; the dialog collects it; `app.py` forwards it.

- [ ] **Step 1: Write the failing test**

Follow the existing search-dialog test pattern (it likely mounts the dialog in a test `App` via `run_test()` and inspects `_collect()`, or tests `_collect()` through a mounted instance). Add:

```python
async def test_collect_includes_person(...):
    # mount SearchDialog as the existing dialog tests do
    dialog.query_one("#query", Input).value = "land"
    dialog.query_one("#person", Input).value = "  John Smith  "
    spec = dialog._collect()
    assert spec.person == "John Smith"

async def test_collect_person_blank_is_none(...):
    # mount SearchDialog; leave #person empty
    spec = dialog._collect()
    assert spec.person is None
```

If the existing tests assert on the dialog's rendered snapshot, a screen change is expected — regenerate the snapshot baseline in Step 5 with `--snapshot-update` after confirming the new layout is correct.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/tui/ -v -k person`
Expected: FAIL — `SearchSpec` has no `person`; `#person` widget does not exist.

- [ ] **Step 3: Implement the dialog change**

In `src/vtextract/tui/dialogs/search.py`:

Add to `SearchSpec`:

```python
@dataclass
class SearchSpec:
    query: str
    fields: tuple[str, ...]
    date_from: str | None
    date_to: str | None
    date_type: str
    volume: str | None
    person: str | None
```

In `compose()`, add a person input after the volume input (before the button row):

```python
            yield Input(placeholder="Volume (root id, optional)",
                        id="volume", value=self.default_volume or "")
            yield Input(placeholder="People (name, optional)", id="person")
            yield Horizontal(
                Button("Search", id="submit", variant="primary"),
                Button("Cancel", id="cancel"),
            )
```

In `_collect()`, add the person read to the returned `SearchSpec`:

```python
        return SearchSpec(
            query=self.query_one("#query", Input).value.strip(),
            fields=fields,
            date_from=self.query_one("#from", Input).value.strip() or None,
            date_to=self.query_one("#to", Input).value.strip() or None,
            date_type="content",
            volume=self.query_one("#volume", Input).value.strip() or None,
            person=self.query_one("#person", Input).value.strip() or None,
        )
```

- [ ] **Step 4: Wire `app.py`**

In `src/vtextract/tui/app.py`, in `_on_search_submitted`, add `person=spec.person` to the `self.index.search(...)` call:

```python
        rows = await self.index.search(
            query=spec.query, fields=spec.fields,
            date_from=spec.date_from, date_to=spec.date_to,
            date_type=spec.date_type, volume=spec.volume,
            person=spec.person,
            limit=0,  # the TUI renders the full result set, not a 50-row page
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/tui/ -v -k person`
Expected: PASS

If any snapshot test failed due to the added input row, verify the new layout looks right and regenerate:
Run: `uv run pytest tests/tui/ --snapshot-update` then re-run `uv run pytest tests/tui/ -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/vtextract/tui/dialogs/search.py src/vtextract/tui/app.py tests/tui/
git commit -m "feat: add People field to vtbrowse search dialog

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Full-suite verification

**Files:** none (verification only).

- [ ] **Step 1: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS (no regressions; new tests included).

- [ ] **Step 2: Smoke-check the boundary test explicitly**

Run: `uv run pytest tests/test_no_direct_db.py -q`
Expected: PASS — `tui/` still routes index access through `IndexService`; no new direct `db`/`query` imports were introduced.

- [ ] **Step 3 (optional manual): drive the TUI**

If an archive with a built index and a `person` table is available, run `uv run vtbrowse --archive ./archive`, open search (`/` or the search key), type a known name into the People field, and confirm results narrow. This is a manual confirmation, not a gate.
