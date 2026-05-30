# vtbrowse select / deselect all (`a`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `a` keystroke that selects or deselects every row in the Results and Pages lists (smart toggle), reusing the existing bundle toggle methods.

**Architecture:** Two new screen actions — `ResultsScreen.action_toggle_all` and `PagesScreen.action_toggle_all` — each checks whether all rows are already in the bundle, then calls the existing per-row `Bundle.toggle_item` / `Bundle.toggle_page` for the rows that need flipping, refreshes the "Sel" column, and fires `app.bundle_changed()` once. No bundle-model changes. `VolumesScreen` is untouched.

**Tech Stack:** Python, Textual (`DataTable` screens, `Binding`), pytest + `pytest-asyncio`, pytest-textual-snapshot.

Spec: `docs/superpowers/specs/2026-05-30-vtbrowse-select-all-design.md`

---

### Task 1: `a` selects / deselects all on ResultsScreen

**Files:**
- Modify: `src/vtextract/tui/screens/results.py` (add binding + `action_toggle_all`)
- Test: `tests/tui/test_results_screen.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/tui/test_results_screen.py`. The existing `_Harness` lacks
`bundle_changed`; add a second harness that records it and lets us pass a shared
`Bundle`.

```python
class _ToggleHarness(App):
    def __init__(self, results, bundle):
        super().__init__()
        self._results = results
        self._bundle = bundle
        self.bundle_changed_calls = 0

    def compose(self):
        yield ResultsScreen(bundle=self._bundle, results=self._results, query="")

    def set_pane_count(self, _text):  # satisfies CountFooterMixin
        pass

    def bundle_changed(self):
        self.bundle_changed_calls += 1


_TOGGLE_RESULTS = [
    {"isadg_id": 1, "content_date": "1700", "estimated_date": None,
     "reference_code": "R1", "title": "One",
     "matched_pages": [{"root_id": "V", "page_key": "p1"}]},
    {"isadg_id": 2, "content_date": "1701", "estimated_date": None,
     "reference_code": "R2", "title": "Two",
     "matched_pages": [{"root_id": "V", "page_key": "p2"}]},
]


@pytest.mark.asyncio
async def test_results_a_selects_all_then_deselects_all():
    bundle = Bundle()
    harness = _ToggleHarness(_TOGGLE_RESULTS, bundle)
    async with harness.run_test() as pilot:
        await pilot.press("a")  # nothing selected -> select all
        assert set(bundle.selected_items) == {1, 2}
        table = pilot.app.query_one(ResultsScreen)
        assert table.get_row_at(0)[0] == "[x]"
        assert table.get_row_at(1)[0] == "[x]"

        await pilot.press("a")  # all selected -> deselect all
        assert bundle.selected_items == {}
        assert table.get_row_at(0)[0] == "[ ]"
        assert harness.bundle_changed_calls == 2


@pytest.mark.asyncio
async def test_results_a_from_partial_selects_all():
    bundle = Bundle()
    bundle.toggle_item(1, [PageRef("V", "p1")])  # only id 1 selected
    harness = _ToggleHarness(_TOGGLE_RESULTS, bundle)
    async with harness.run_test() as pilot:
        await pilot.press("a")  # partial -> select all (not deselect)
        assert set(bundle.selected_items) == {1, 2}


@pytest.mark.asyncio
async def test_results_a_on_empty_is_noop():
    bundle = Bundle()
    harness = _ToggleHarness([], bundle)
    async with harness.run_test() as pilot:
        await pilot.press("a")
        assert bundle.selected_items == {}
        assert harness.bundle_changed_calls == 0
```

The test file currently imports only `Bundle`
(`from vtextract.tui.bundle import Bundle`); the new tests also use `PageRef`,
so change that import line to
`from vtextract.tui.bundle import Bundle, PageRef`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/tui/test_results_screen.py -k "toggle or a_selects or a_from or a_on_empty" -v`
Expected: FAIL — pressing `a` does nothing (no binding), so `selected_items` stays `{}` and the first assert fails.

- [ ] **Step 3: Add the binding and action**

In `src/vtextract/tui/screens/results.py`, add to `BINDINGS`:

```python
    BINDINGS = [
        Binding("enter", "view_first_match", "view"),
        Binding("space", "toggle_item", "toggle"),
        Binding("a", "toggle_all", "all"),
        Binding("escape", "back", "back"),
    ]
```

Add the action method (place it after `action_toggle_item`):

```python
    def action_toggle_all(self) -> None:
        if not self.results:
            return
        all_selected = all(
            r["isadg_id"] in self.bundle.selected_items for r in self.results
        )
        for row, r in enumerate(self.results):
            in_bundle = r["isadg_id"] in self.bundle.selected_items
            if all_selected == in_bundle:
                refs = [PageRef(p["root_id"], p["page_key"])
                        for p in r.get("matched_pages", [])]
                self.bundle.toggle_item(r["isadg_id"], refs)
            self.update_cell_at(
                (row, 0),
                "[ ]" if all_selected else "[x]",
            )
        self.app.bundle_changed()  # type: ignore[attr-defined]
```

Note: `all_selected == in_bundle` flips exactly the rows that need changing —
when selecting all, flip rows not in the bundle; when deselecting all, flip rows
in the bundle.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/tui/test_results_screen.py -k "toggle or a_selects or a_from or a_on_empty" -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/tui/screens/results.py tests/tui/test_results_screen.py
git commit -m "feat(vtbrowse): 'a' selects/deselects all search results"
```

---

### Task 2: `a` selects / deselects all on PagesScreen

**Files:**
- Modify: `src/vtextract/tui/screens/pages.py` (add binding + `action_toggle_all`)
- Test: `tests/tui/test_pages_screen.py` (append unit tests with a fake index)

- [ ] **Step 1: Write the failing test**

Append to `tests/tui/test_pages_screen.py`. `PagesScreen.on_mount` awaits
`self.index.pages(root_id)`, so supply a tiny fake index; no real `IndexClient`
or archive is needed for these unit tests.

```python
import pytest
from textual.app import App

from vtextract.tui.bundle import Bundle, PageRef
from vtextract.tui.screens.pages import PagesScreen


class _FakeIndex:
    def __init__(self, pages):
        self._pages = pages

    async def pages(self, _root_id):
        return self._pages


class _PagesHarness(App):
    def __init__(self, pages, bundle, root_id="V"):
        super().__init__()
        self._index = _FakeIndex(pages)
        self._bundle = bundle
        self._root_id = root_id
        self.bundle_changed_calls = 0

    def compose(self):
        yield PagesScreen(index=self._index, bundle=self._bundle,
                          root_id=self._root_id)

    def set_pane_count(self, _text):  # satisfies CountFooterMixin
        pass

    def bundle_changed(self):
        self.bundle_changed_calls += 1


_PAGES = [
    {"ordinal": 1, "page_key": "p1", "transcription": True, "image": True},
    {"ordinal": 2, "page_key": "p2", "transcription": False, "image": True},
]


@pytest.mark.asyncio
async def test_pages_a_selects_all_then_deselects_all():
    bundle = Bundle()
    harness = _PagesHarness(_PAGES, bundle)
    async with harness.run_test() as pilot:
        await pilot.press("a")  # none -> select all
        assert bundle.is_in_bundle(PageRef("V", "p1"))
        assert bundle.is_in_bundle(PageRef("V", "p2"))
        table = pilot.app.query_one(PagesScreen)
        assert table.get_row_at(0)[4] == "*"
        assert table.get_row_at(1)[4] == "*"

        await pilot.press("a")  # all -> deselect all
        assert not bundle.is_in_bundle(PageRef("V", "p1"))
        assert not bundle.is_in_bundle(PageRef("V", "p2"))
        assert table.get_row_at(0)[4] == ""
        assert harness.bundle_changed_calls == 2


@pytest.mark.asyncio
async def test_pages_a_treats_item_included_page_as_selected():
    # A page implicitly in the bundle via a selected item counts as selected,
    # so a partial state selects the rest (does not deselect).
    bundle = Bundle(selected_items={9: [PageRef("V", "p1")]})
    harness = _PagesHarness(_PAGES, bundle)
    async with harness.run_test() as pilot:
        await pilot.press("a")  # p1 already in via item -> select all the rest
        assert bundle.is_in_bundle(PageRef("V", "p1"))
        assert bundle.is_in_bundle(PageRef("V", "p2"))


@pytest.mark.asyncio
async def test_pages_a_on_empty_is_noop():
    bundle = Bundle()
    harness = _PagesHarness([], bundle)
    async with harness.run_test() as pilot:
        await pilot.press("a")
        assert bundle.page_state == {}
        assert harness.bundle_changed_calls == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/tui/test_pages_screen.py -k "a_selects or a_treats or a_on_empty" -v`
Expected: FAIL — `a` is unbound, so `is_in_bundle` stays False after the press.

- [ ] **Step 3: Add the binding and action**

In `src/vtextract/tui/screens/pages.py`, add to `BINDINGS`:

```python
    BINDINGS = [
        Binding("enter", "view_page", "view"),
        Binding("space", "toggle_select", "select"),
        Binding("a", "toggle_all", "all"),
        Binding("escape", "back", "back"),
    ]
```

Add the action method (place it after `action_toggle_select`):

```python
    def action_toggle_all(self) -> None:
        if not self._pages:
            return
        refs = [PageRef(self.root_id, p["page_key"]) for p in self._pages]
        all_selected = all(self.bundle.is_in_bundle(ref) for ref in refs)
        for row, ref in enumerate(refs):
            in_bundle = self.bundle.is_in_bundle(ref)
            if all_selected == in_bundle:
                self.bundle.toggle_page(ref)
            self.update_cell_at(
                (row, 4),
                "" if all_selected else "*",
            )
        self.app.bundle_changed()  # type: ignore[attr-defined]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/tui/test_pages_screen.py -k "a_selects or a_treats or a_on_empty" -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/tui/screens/pages.py tests/tui/test_pages_screen.py
git commit -m "feat(vtbrowse): 'a' selects/deselects all pages in a volume"
```

---

### Task 3: Document `a` in the Help dialog

**Files:**
- Modify: `src/vtextract/tui/dialogs/help.py:11-35` (`_BINDINGS` tuple)
- Test: `tests/tui/test_help_dialog.py` (append a content assertion); regenerate snapshot

- [ ] **Step 1: Write the failing test**

Append to `tests/tui/test_help_dialog.py`:

```python
def test_help_lists_select_all_binding():
    """The Help dialog documents the 'a' select/deselect-all shortcut."""
    from vtextract.tui.dialogs.help import _BINDINGS

    keys = {key for key, _ctx, _action in _BINDINGS}
    assert "a" in keys
    row = next(r for r in _BINDINGS if r[0] == "a")
    assert "select" in row[2].lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/tui/test_help_dialog.py::test_help_lists_select_all_binding -v`
Expected: FAIL — no `"a"` entry in `_BINDINGS`, so the `next(...)` raises `StopIteration`.

- [ ] **Step 3: Add the help entry**

In `src/vtextract/tui/dialogs/help.py`, insert a row in `_BINDINGS` right after
the `space` "search result row" line:

```python
    ("space",    "search result row",         "toggle item in selection"),
    ("a",        "page list, search results", "select or deselect all"),
    ("space",    "Bundle row",                "remove page or volume's pages"),
```

- [ ] **Step 4: Run test to verify it passes, then refresh the snapshot**

Run: `uv run pytest tests/tui/test_help_dialog.py::test_help_lists_select_all_binding -v`
Expected: PASS

The help-dialog snapshot now has an extra row, so update the baseline:

Run: `uv run pytest tests/tui/test_help_dialog.py --snapshot-update`
Expected: snapshot tests report as updated; re-run without the flag to confirm green:

Run: `uv run pytest tests/tui/test_help_dialog.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/tui/dialogs/help.py tests/tui/test_help_dialog.py \
        tests/tui/__snapshots__/test_help_dialog
git commit -m "docs(vtbrowse): document 'a' select/deselect-all in help dialog"
```

---

### Task 4: Full suite regression check

**Files:** none (verification only)

- [ ] **Step 1: Run the TUI suite**

Run: `uv run pytest tests/tui/ -v`
Expected: PASS (all, including the new tests and the refreshed snapshot)

- [ ] **Step 2: Run the full suite**

Run: `uv run pytest`
Expected: PASS — confirms nothing else (e.g. binding-collision assumptions) regressed.

No commit; this task only verifies.

---

## Notes for the implementer

- The flip condition `all_selected == in_bundle` is deliberate: it touches only
  the rows that must change in either direction, so it works for both the
  select-all and deselect-all branches.
- Do **not** add `a` to `VolumesScreen` or to the app-level `BINDINGS` — it is a
  per-list binding by design (spec "Out of scope").
- `PageRef` is already imported in `results.py` and `pages.py`; only the test
  files may need the import added.
