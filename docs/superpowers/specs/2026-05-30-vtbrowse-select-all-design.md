# vtbrowse: select / deselect all (`a`)

Date: 2026-05-30

## Goal

Add a single keystroke, `a`, that selects or deselects **every row** in the
current list, so a user can bulk-add a whole search result set or a whole
volume's pages to the bundle without pressing `space` row by row.

## Scope

- Applies to **`ResultsScreen`** (catalog items) and **`PagesScreen`**
  (physical pages) only.
- **`VolumesScreen` is out of scope.** It has no per-row selection concept
  today (no "Sel" column, no `space` binding), so `a` is not bound there.

## Behavior — smart toggle

Pressing `a` inspects whether *every* row in the list is already in the bundle:

- All rows selected → **deselect all**.
- Any row unselected → **select all**.

An empty list is a no-op.

The implementation reuses the existing per-row toggle methods
(`Bundle.toggle_item` / `Bundle.toggle_page`), so the bundle's
include/exclude override semantics and the count footer remain correct with
**no new model logic**.

### ResultsScreen — `action_toggle_all`

- All-selected test:
  `all(r["isadg_id"] in self.bundle.selected_items for r in self.results)`.
- Select all: for each result whose `isadg_id` is **not** in
  `selected_items`, call `self.bundle.toggle_item(id, refs)` with the same
  `PageRef` list built in `action_toggle_item`
  (`[PageRef(p["root_id"], p["page_key"]) for p in r.get("matched_pages", [])]`).
- Deselect all: for each result whose `isadg_id` **is** in `selected_items`,
  call `self.bundle.toggle_item(id, refs)` to remove it.
- After mutating, refresh the "Sel" cell (column 0) for every row
  (`"[x]"` / `"[ ]"`) and call `self.app.bundle_changed()` **once**.

### PagesScreen — `action_toggle_all`

- All-selected test:
  `all(self.bundle.is_in_bundle(PageRef(self.root_id, p["page_key"])) for p in self._pages)`.
- Select all: for each page where `is_in_bundle` is false, call
  `self.bundle.toggle_page(ref)` (sets `include`).
- Deselect all: for each page where `is_in_bundle` is true, call
  `self.bundle.toggle_page(ref)` (sets `exclude`).
- After mutating, refresh the "Sel" cell (column 4) for every row
  (`"*"` / `""`) and call `self.app.bundle_changed()` **once**.

## Bindings

Add to each screen's `BINDINGS`:

```python
Binding("a", "toggle_all", "all")
```

`a` does not collide with any existing app-level (`q f r v i s o x b e`) or
screen-level (`enter space escape`) binding.

## Help dialog

Add an entry to `dialogs/help.py`'s `_BINDINGS` tuple:

```python
("a", "page list, search results", "select or deselect all"),
```

placed near the other `space` selection rows.

## Testing (TDD)

Per-screen Textual tests (following `tests/tui/` patterns):

- **Results:** from an empty selection, `a` selects every result; pressing `a`
  again deselects all; a partial selection → `a` selects all (not deselect);
  empty results list is a no-op; `bundle_changed` is fired.
- **Pages:** same matrix against `toggle_page`, asserting `is_in_bundle` for
  every page flips, and that a page implicitly included via a selected item is
  treated as "selected" by the all-selected test.
- **Help dialog:** assert the new `a` row is present (content check or snapshot
  update under `tests/tui/__snapshots__/`).

## Out of scope

- Volume-level selection on `VolumesScreen`.
- Any change to bundle persistence, export, or the count footer.
