# Re-sortable search results in `vtbrowse`

**Date:** 2026-06-01
**Status:** Approved (design)

## Problem

After running a search in the `vtbrowse` TUI, the results are shown in a fixed
order — relevance (bm25) when the search had keywords, content-date-ascending
when it was filter-only (see `index/query.py` and `index/db.py:filter_items`).
There is no way to re-order the already-rendered result set. A user who wants
to see the oldest or newest matching resources must mentally scan, because the
order is decided once at query time and never changes.

We want a key on the results screen that cycles the sort order in place,
without re-querying the index.

## Behavior

On the results screen (`screens/results.py`), the `d` key cycles the sort order
through three states:

1. **Relevance** (default) — bm25 `score`, best first (most-negative first).
   This is the order the index already returns.
2. **Date — oldest first** — sort key `content_date or estimated_date`,
   ascending, undated resources last.
3. **Date — newest first** — same key, descending, undated resources still last.

Pressing `d` from state 3 wraps back to state 1.

`d` is a free key: it is not bound at the app level (`q f r v i s o x b e f1
question_mark tab`) nor on the results screen (`enter space a escape`), so there
is no shadowing of any existing binding.

### Sort key semantics

- **Relevance:** `key = result.score`, ascending. bm25 is more-negative = better,
  so ascending puts the strongest matches first — identical to `query.search`'s
  existing `results.sort(key=lambda r: r.score)`. Python's stable sort preserves
  the incoming order for ties.
- **Date (both directions):** the displayed date — `content_date or
  estimated_date` — is the sort key. This is the same value `_date_cell` renders
  and the same `COALESCE(content_begin, estimated_begin)` rule that
  `db.filter_items` already orders by, so "date" means the same thing in the TUI
  as everywhere else in the tool. Undated resources (both fields `None`) sort
  **last** in both directions, matching `filter_items`'s `... IS NULL` clause.
  Dates are ISO-prefixed strings (`"1798"`, `"1798/1799"`), so lexicographic
  comparison orders them correctly; `isadg_id` is the final stable tiebreak.

### Visual indicator

The current mode is shown in the pane's top-border title (set via
`app.set_pane_title`). The results screen is mounted with title
`"Search Results"`; the screen appends the sort mode:

- `Search Results · sort: relevance`
- `Search Results · sort: date ↑`
- `Search Results · sort: date ↓`

The title is updated on mount (showing the default) and on every `d` press.

## Mechanism — re-sort in place, no re-query

Every `SearchResult` already carries `score`, `content_date`, and
`estimated_date`, so the screen re-orders its own `self.results` list and
rebuilds the table rows. There is **no** call back to `IndexClient` /
`IndexService`.

### Where the logic lives

- A pure, side-effect-free function in `screens/results.py`:

  ```
  def sort_results(results: list, mode: SortMode) -> list: ...
  ```

  Returns a new ordered list; testable without driving the UI.
- A `SortMode` enum (`RELEVANCE`, `DATE_ASC`, `DATE_DESC`) with a `next()`
  helper (or a module-level cycle list) and a human label for the title.
- `ResultsScreen` holds the current `SortMode` (initialised to `RELEVANCE`) and
  gains `Binding("d", "cycle_sort", "sort")` plus `action_cycle_sort`.

### Re-render on cycle

`action_cycle_sort`:

1. Advance the mode to its successor.
2. Remember the `isadg_id` currently under the cursor (if any).
3. `self.results = sort_results(self.results, mode)`.
4. Clear the table and re-add every row, re-deriving each selection marker
   (`_sel_cell`) from `self.bundle.selected_items` so bundle membership stays
   correct after the reorder.
5. Move the cursor back to the remembered `isadg_id` if it is still present,
   else to row 0.
6. Update the pane title via `app.set_pane_title`.

The count footer (`CountFooterMixin`) re-publishes automatically on the
resulting scroll/layout; no extra wiring needed.

## Scope / non-goals (YAGNI)

- **Transient, per-screen state.** Each new search resets the sort to
  Relevance. The choice is **not** persisted to config (unlike `[browse].theme`).
- **Filter-only searches** have all-equal `score` (0.0), so "Relevance" there is
  just the index's natural date-ascending input order (stable sort preserves it).
  The cycle still works; Relevance simply coincides with Date-oldest in that
  case. No special-casing.
- **No new sort dimensions** — only relevance + content/estimated date. Not
  created-date, title, or reference code.
- **No re-query** — sorting never touches the index or changes the result set,
  only its order.

## Testing

1. **Unit tests** on `sort_results`, covering:
   - Relevance: ascending by score; stable for ties.
   - Date ascending: oldest first; undated last.
   - Date descending: newest first; undated still last.
   - Date ranges (`"1798/1799"`) and estimated-only dates order sensibly.
2. **TUI interaction/snapshot test** (`tests/tui/`): press `d` and assert the
   row order and the title-bar indicator cycle through the three states and
   wrap. Snapshot baselines under `tests/tui/__snapshots__/`, regenerated with
   `--snapshot-update`.

## Architectural fit

- Stays inside the `tui/` boundary: no new imports of
  `index.{db,query,builder}` — the screen sorts data it already has in memory.
- Follows the existing pattern of pure helpers in `screens/results.py`
  (`_sel_cell`, `_date_cell`) by adding `sort_results` alongside them.
- Reuses `app.set_pane_title` and `CountFooterMixin` rather than introducing new
  footer plumbing.
