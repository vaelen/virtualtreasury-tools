# Re-sortable search results in `vtbrowse` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `d` key to the `vtbrowse` results screen that cycles the sort order (Relevance → Date oldest → Date newest → back) by re-sorting the already-rendered result set in place, with the current mode shown in the pane title.

**Architecture:** A pure `sort_results(results, mode)` function plus a `SortMode` enum live in `screens/results.py`. `ResultsScreen` holds the current mode, re-orders its in-memory `self.results` (the `SearchHit` list it was given) and rebuilds the table rows on each `d` press. No call back to the index — the data is already in memory.

**Tech Stack:** Python, Textual (DataTable screen), pytest + pytest-asyncio, pytest-textual-snapshot.

---

## Background an implementer needs

- The results screen is `src/vtextract/tui/screens/results.py`. It is a
  `DataTable` subclass that receives `results: list` in its constructor and
  builds one table row per result in `on_mount`.
- Each result is a `SearchHit` dataclass (`src/vtextract/index/models.py:151`)
  with — among others — these fields the sort uses:
  `isadg_id: int`, `content_date: str | None`, `estimated_date: str | None`,
  `score: float`. `score` is a bm25 value: **more-negative = better match**.
- The displayed date column (`_date_cell` in `results.py`) already shows
  `content_date or estimated_date`. The sort key reuses exactly that rule.
- The pane's top-border title is set through `app.set_pane_title(text)`
  (`src/vtextract/tui/app.py:278`). The screen is mounted with the title
  `"Search Results"`; the screen will override it to append the sort mode. The
  screen-from-app call precedent already exists: `CountFooterMixin` calls
  `self.app.set_pane_count(...)` from inside the screen.
- Date strings are ISO-prefixed (`"1737"`, `"1776-01-01/1793-12-31"`), so plain
  string comparison orders them correctly.

## File structure

- **Modify** `src/vtextract/tui/screens/results.py` — add `SortMode` enum,
  `sort_results` pure function, sort state, `_populate()` (extracted from
  `on_mount`), `_update_title()`, the `d` binding, and `action_cycle_sort`.
- **Create** `tests/tui/test_results_sort.py` — unit tests for `sort_results`
  and an interaction test for the `d`-key cycle.
- **Modify** `tests/tui/test_results_screen.py` — add a `set_pane_title` no-op
  stub to the two in-file test harness apps (`_Harness`, `_ToggleHarness`), so
  the screen's `on_mount` title update does not `AttributeError`.
- **Modify** `tests/tui/test_pane_title.py` — update
  `test_results_title_is_search_results` to expect the new title that includes
  the default sort mode.
- **Regenerate** `tests/tui/__snapshots__/test_results_screen/test_results_screen_after_search.raw`
  via `--snapshot-update` (the pane title in the captured frame changes).

---

### Task 1: Pure sort logic — `SortMode` + `sort_results`

**Files:**
- Modify: `src/vtextract/tui/screens/results.py`
- Test: `tests/tui/test_results_sort.py` (create)

- [ ] **Step 1: Write the failing unit tests**

Create `tests/tui/test_results_sort.py`:

```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""Sort logic for the results screen: relevance + date asc/desc, undated last."""

from __future__ import annotations

from types import SimpleNamespace

from vtextract.tui.screens.results import SortMode, sort_results


def _hit(isadg_id, score, content_date=None, estimated_date=None):
    # sort_results is duck-typed: it only reads these four attributes.
    return SimpleNamespace(
        isadg_id=isadg_id, score=score,
        content_date=content_date, estimated_date=estimated_date,
    )


def _ids(results):
    return [r.isadg_id for r in results]


def test_sortmode_next_wraps_through_three_states():
    assert SortMode.RELEVANCE.next() is SortMode.DATE_ASC
    assert SortMode.DATE_ASC.next() is SortMode.DATE_DESC
    assert SortMode.DATE_DESC.next() is SortMode.RELEVANCE


def test_relevance_orders_best_bm25_first():
    # bm25: more-negative = better, so it must sort ascending by score.
    hits = [_hit(1, -1.0), _hit(2, -5.0), _hit(3, -3.0)]
    assert _ids(sort_results(hits, SortMode.RELEVANCE)) == [2, 3, 1]


def test_relevance_is_stable_for_ties():
    hits = [_hit(1, 0.0), _hit(2, 0.0), _hit(3, 0.0)]
    assert _ids(sort_results(hits, SortMode.RELEVANCE)) == [1, 2, 3]


def test_date_ascending_oldest_first_undated_last():
    hits = [
        _hit(1, -5.0, content_date="1850"),
        _hit(2, -1.0, content_date="1700"),
        _hit(3, -3.0),  # undated
    ]
    assert _ids(sort_results(hits, SortMode.DATE_ASC)) == [2, 1, 3]


def test_date_descending_newest_first_undated_still_last():
    hits = [
        _hit(1, -5.0, content_date="1850"),
        _hit(2, -1.0, content_date="1700"),
        _hit(3, -3.0),  # undated
    ]
    assert _ids(sort_results(hits, SortMode.DATE_DESC)) == [1, 2, 3]


def test_estimated_date_used_when_content_date_missing():
    # content_date or estimated_date — same rule the Date column displays.
    hits = [
        _hit(1, 0.0, content_date="1900"),
        _hit(2, 0.0, estimated_date="1800"),
    ]
    assert _ids(sort_results(hits, SortMode.DATE_ASC)) == [2, 1]


def test_date_ranges_compare_lexicographically():
    hits = [
        _hit(1, 0.0, content_date="1798/1799"),
        _hit(2, 0.0, content_date="1700"),
    ]
    assert _ids(sort_results(hits, SortMode.DATE_ASC)) == [2, 1]


def test_equal_dates_keep_isadg_ascending_in_both_directions():
    hits = [_hit(3, 0.0, content_date="1700"), _hit(1, 0.0, content_date="1700")]
    assert _ids(sort_results(hits, SortMode.DATE_ASC)) == [1, 3]
    assert _ids(sort_results(hits, SortMode.DATE_DESC)) == [1, 3]


def test_mode_labels_for_title():
    assert SortMode.RELEVANCE.value == "relevance"
    assert SortMode.DATE_ASC.value == "date ↑"
    assert SortMode.DATE_DESC.value == "date ↓"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/tui/test_results_sort.py -v`
Expected: FAIL — `ImportError: cannot import name 'SortMode'` (and `sort_results`).

- [ ] **Step 3: Implement `SortMode` and `sort_results`**

In `src/vtextract/tui/screens/results.py`, add `from enum import Enum` to the
imports, then add the following near the top of the module (after the existing
`_date_cell` helper):

```python
class SortMode(Enum):
    """The three result orderings the ``d`` key cycles through. The value is
    the human label shown in the pane title."""

    RELEVANCE = "relevance"
    DATE_ASC = "date ↑"   # oldest first
    DATE_DESC = "date ↓"  # newest first

    def next(self) -> "SortMode":
        order = (SortMode.RELEVANCE, SortMode.DATE_ASC, SortMode.DATE_DESC)
        return order[(order.index(self) + 1) % len(order)]


def _date_sort_key(result):
    """The date a result sorts on: content date, else estimated date, else None
    (undated). Mirrors what ``_date_cell`` displays and the
    ``COALESCE(content_begin, estimated_begin)`` ordering used by the index."""
    return result.content_date or result.estimated_date


def sort_results(results: list, mode: SortMode) -> list:
    """Return a new list of ``results`` ordered for ``mode``.

    Relevance sorts ascending by bm25 ``score`` (more-negative = better); the
    sort is stable so ties keep their incoming order. Both date modes key on
    ``content_date or estimated_date`` with undated results pinned **last** in
    either direction; equal dates keep ``isadg_id`` ascending (a stable
    secondary sort, applied before the date sort)."""
    if mode is SortMode.RELEVANCE:
        return sorted(results, key=lambda r: r.score)

    dated = sorted(
        (r for r in results if _date_sort_key(r) is not None),
        key=lambda r: r.isadg_id,
    )
    dated.sort(key=_date_sort_key, reverse=(mode is SortMode.DATE_DESC))
    undated = sorted(
        (r for r in results if _date_sort_key(r) is None),
        key=lambda r: r.isadg_id,
    )
    return dated + undated
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/tui/test_results_sort.py -v`
Expected: PASS (all nine tests).

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/tui/screens/results.py tests/tui/test_results_sort.py
git commit -m "feat(tui): add sort_results + SortMode for results ordering"
```

---

### Task 2: Render plumbing — extract `_populate()`, add sort state + title indicator

This task introduces the sort state and shows it in the pane title, and
refactors row-building into a reusable `_populate()` — but does **not** yet add
the `d` key (Task 3). After this task the results screen still renders exactly
as before, except the pane title reads `Search Results · sort: relevance`.

**Files:**
- Modify: `src/vtextract/tui/screens/results.py`
- Modify: `tests/tui/test_results_screen.py` (harness stubs)
- Modify: `tests/tui/test_pane_title.py` (title assertion)
- Regenerate: `tests/tui/__snapshots__/test_results_screen/test_results_screen_after_search.raw`

- [ ] **Step 1: Update the pane-title test to expect the sort indicator (failing)**

In `tests/tui/test_pane_title.py`, in `test_results_title_is_search_results`,
change the title assertion:

```python
        pane = app.query_one(DocumentPane)
        assert pane.border_title == "Search Results · sort: relevance"
        assert _COUNT.match(str(pane.border_subtitle or ""))
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/tui/test_pane_title.py::test_results_title_is_search_results -v`
Expected: FAIL — title is still `"Search Results"` (assertion mismatch).

- [ ] **Step 3: Add sort state, `_populate()`, and `_update_title()`**

In `src/vtextract/tui/screens/results.py`:

(a) Set the initial sort mode in `__init__`:

```python
    def __init__(self, *, bundle: Bundle, results: list, query: str) -> None:
        super().__init__(cursor_type="row")
        self.bundle = bundle
        self.results = results
        self.query = query
        self.sort_mode = SortMode.RELEVANCE
```

(b) Replace the existing `on_mount` with one that delegates row-building to a
new `_populate()` and sets the title:

```python
    def on_mount(self) -> None:
        self.add_columns("Sel", "ID", "Date", "Reference", "Title")
        self._populate()
        self._update_title()
        self._wire_count_footer()

    def _populate(self) -> None:
        """(Re)build every table row from ``self.results`` in its current order,
        re-deriving each selection marker from the bundle so membership stays
        correct after a re-sort. Leaves the cursor on the first row."""
        self.clear()  # clears rows, keeps columns
        for r in self.results:
            in_bundle = r.isadg_id in self.bundle.selected_items
            self.add_row(
                _sel_cell(in_bundle),
                str(r.isadg_id),
                _date_cell(r),
                r.reference_code or "-",
                r.title or "-",
            )
        if self.results:
            self.move_cursor(row=0)

    def _update_title(self) -> None:
        self.app.set_pane_title(  # type: ignore[attr-defined]
            f"Search Results · sort: {self.sort_mode.value}"
        )
```

- [ ] **Step 4: Add `set_pane_title` stubs to the in-file test harnesses**

In `tests/tui/test_results_screen.py`, both `_Harness` and `_ToggleHarness`
already stub `set_pane_count`. Add an analogous stub to **each** class so the
new `on_mount` title call works:

```python
    def set_pane_title(self, _text):  # satisfies _update_title
        pass
```

- [ ] **Step 5: Run the affected tests to verify they pass**

Run: `uv run pytest tests/tui/test_pane_title.py tests/tui/test_results_screen.py -v`
Expected: PASS (note: the snapshot test `test_results_screen_after_search` is
addressed in Step 6).

- [ ] **Step 6: Regenerate the results snapshot baseline**

The captured frame now shows the new pane title, so the baseline must be
updated.

Run: `uv run pytest tests/tui/test_results_screen.py::test_results_screen_after_search --snapshot-update`
Expected: the `.raw` baseline is rewritten; test reports updated/passed.

Then confirm it passes without the flag:

Run: `uv run pytest tests/tui/test_results_screen.py::test_results_screen_after_search -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/vtextract/tui/screens/results.py tests/tui/test_results_screen.py \
        tests/tui/test_pane_title.py \
        tests/tui/__snapshots__/test_results_screen/test_results_screen_after_search.raw
git commit -m "feat(tui): show sort mode in results title; extract _populate"
```

---

### Task 3: The `d` key — `action_cycle_sort`

**Files:**
- Modify: `src/vtextract/tui/screens/results.py`
- Test: `tests/tui/test_results_sort.py` (add interaction test)

- [ ] **Step 1: Write the failing interaction test**

Append to `tests/tui/test_results_sort.py`:

```python
import pytest
from textual.app import App

from vtextract.index.models import SearchHit
from vtextract.tui.bundle import Bundle
from vtextract.tui.screens.results import ResultsScreen


class _SortHarness(App):
    def __init__(self, results):
        super().__init__()
        self._results = results
        self.pane_title = None

    def compose(self):
        yield ResultsScreen(bundle=Bundle(), results=self._results, query="")

    def set_pane_count(self, _text):  # satisfies CountFooterMixin
        pass

    def set_pane_title(self, text):  # satisfies _update_title
        self.pane_title = text


def _make_hit(isadg_id, score, content_date=None):
    return SearchHit(
        isadg_id=isadg_id, title=f"R{isadg_id}", reference_code=f"R{isadg_id}",
        repository=None, content_date=content_date, created_date=None,
        estimated_date=None, estimated_source=None, matched_fields=[],
        matched_pages=[], score=score, path=f"items/{isadg_id}",
    )


# Relevance: by score asc -> [1, 3, 2]; Date asc: [2, 1, 3] (id 3 undated last);
# Date desc: [1, 2, 3] (undated still last).
_SORT_RESULTS = [
    _make_hit(1, -5.0, content_date="1850"),
    _make_hit(2, -1.0, content_date="1700"),
    _make_hit(3, -3.0, content_date=None),
]


def _row_ids(table):
    return [int(table.get_row_at(i)[1]) for i in range(table.row_count)]


@pytest.mark.asyncio
async def test_d_cycles_sort_order_and_title_and_wraps():
    async with _SortHarness(list(_SORT_RESULTS)).run_test() as pilot:
        table = pilot.app.query_one(ResultsScreen)

        # default: relevance
        assert _row_ids(table) == [1, 3, 2]
        assert pilot.app.pane_title == "Search Results · sort: relevance"

        await pilot.press("d")  # -> date ascending
        assert _row_ids(table) == [2, 1, 3]
        assert pilot.app.pane_title == "Search Results · sort: date ↑"

        await pilot.press("d")  # -> date descending
        assert _row_ids(table) == [1, 2, 3]
        assert pilot.app.pane_title == "Search Results · sort: date ↓"

        await pilot.press("d")  # wraps -> relevance
        assert _row_ids(table) == [1, 3, 2]
        assert pilot.app.pane_title == "Search Results · sort: relevance"


@pytest.mark.asyncio
async def test_d_keeps_cursor_on_same_result():
    async with _SortHarness(list(_SORT_RESULTS)).run_test() as pilot:
        table = pilot.app.query_one(ResultsScreen)
        table.move_cursor(row=2)  # relevance order row 2 == id 2
        assert int(table.get_row_at(table.cursor_row)[1]) == 2
        await pilot.press("d")  # date asc: id 2 is now row 0
        assert int(table.get_row_at(table.cursor_row)[1]) == 2


@pytest.mark.asyncio
async def test_d_on_empty_results_is_noop():
    async with _SortHarness([]).run_test() as pilot:
        table = pilot.app.query_one(ResultsScreen)
        await pilot.press("d")
        assert table.row_count == 0
        # mode did not advance; title still default
        assert pilot.app.pane_title == "Search Results · sort: relevance"
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `uv run pytest tests/tui/test_results_sort.py -k "d_cycles or d_keeps or d_on_empty" -v`
Expected: FAIL — pressing `d` does nothing (no binding/action), so order and
title never change.

- [ ] **Step 3: Add the `d` binding and `action_cycle_sort`**

In `src/vtextract/tui/screens/results.py`, add the binding to `BINDINGS`:

```python
    BINDINGS = [
        Binding("enter", "view_first_match", "view"),
        Binding("space", "toggle_item", "toggle"),
        Binding("a", "toggle_all", "all"),
        Binding("d", "cycle_sort", "sort"),
        Binding("escape", "back", "back"),
    ]
```

Then add the action method (e.g. after `action_toggle_all`):

```python
    def action_cycle_sort(self) -> None:
        if not self.results:
            return
        current_id = self.results[self.cursor_row].isadg_id
        self.sort_mode = self.sort_mode.next()
        self.results = sort_results(self.results, self.sort_mode)
        self._populate()
        for i, r in enumerate(self.results):
            if r.isadg_id == current_id:
                self.move_cursor(row=i)
                break
        self._update_title()
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `uv run pytest tests/tui/test_results_sort.py -k "d_cycles or d_keeps or d_on_empty" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/tui/screens/results.py tests/tui/test_results_sort.py
git commit -m "feat(tui): cycle results sort order on the 'd' key"
```

---

### Task 4: Full regression pass

**Files:** none (verification only).

- [ ] **Step 1: Run the whole TUI suite**

Run: `uv run pytest tests/tui/ -v`
Expected: PASS — no regressions. In particular confirm `test_bindings.py`,
`test_pane_title.py`, and `test_results_screen.py` are green.

- [ ] **Step 2: Run the full suite**

Run: `uv run pytest`
Expected: PASS (all tests, including non-TUI).

- [ ] **Step 3: Commit only if there are uncommitted changes**

If Steps 1–2 surfaced and required fixes, commit them:

```bash
git add -A
git commit -m "test(tui): fix regressions from results re-sort"
```

Otherwise this task produces no commit.

---

## Self-review notes

- **Spec coverage:** 3-way cycle on `d` (Task 3); relevance + date-asc + date-desc
  with undated-last and stable isadg tiebreak (Task 1); title indicator
  `Search Results · sort: …` (Task 2); re-sort in place / no re-query (Task 3
  reorders `self.results` only); transient per-screen state — `sort_mode`
  resets to `RELEVANCE` because a fresh `ResultsScreen` is constructed for each
  search in `app._on_search_submitted` (no config persistence added).
- **Filter-only searches:** all-equal scores → `sorted(key=score)` is stable, so
  Relevance preserves the index's date-ascending input order, as the spec notes.
  No special-casing needed.
- **Undated-last in both directions:** enforced by partitioning dated/undated
  rather than a naive `reverse=True` over the whole list (which would float
  undated to the top). Covered by
  `test_date_descending_newest_first_undated_still_last`.
- **Type consistency:** `SortMode`, `sort_results`, `_date_sort_key`,
  `_populate`, `_update_title`, `action_cycle_sort` names are used identically
  across tasks. `sort_results` is duck-typed on `.score/.content_date/`
  `.estimated_date/.isadg_id`, so it works for both `SearchHit` (runtime) and
  the `SimpleNamespace` unit-test doubles.
```
