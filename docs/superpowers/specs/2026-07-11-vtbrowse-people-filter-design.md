# vtbrowse people filter — design

Date: 2026-07-11

## What this is

Add a **People** field to the `vtbrowse` search dialog. When it is filled,
search results are narrowed to items that reference a page where that person
appears, intersected (AND) with the existing text / date / volume filters.

The person index already exists (`vtextract names` → `person` / `person_alias`
tables, searched via `people_search()` / `IndexService.people()`). This feature
wires that index into the interactive search dialog as one more filter.

## Combine semantics (decided)

**AND / narrow.** With a text query and/or a date range also set, results must
match those filters *and* reference a page mentioning the person. A person-only
search (blank query field) returns every item mentioning that person, filtered
by date/volume if set. This mirrors how the existing date and volume filters
already narrow the candidate set — the person field is one more narrowing
filter, not a second ranked query.

## Where the filter lives

In `query.search()`, alongside the date/volume filters. The index layer
(`vtextract.index`) is the single composition point that both the `vtindex` CLI
and the `vtbrowse` TUI go through (`IndexService`). The filter does **not** live
in the TUI layer — putting it in `query.py` keeps all item filtering in one
place, keeps it testable against the committed fixtures, and leaves the door
open for the CLI to reuse it later.

It reuses two things that already exist:

- `people_search(db, name)` — FTS match over canonical names + aliases,
  returning `PersonHit`s. Each hit carries `items` (the isadg_ids that reference
  the page the person was found on).
- `db.filter_items(candidate_ids, ...)` — the existing intersection path. It
  already treats `ids=None` as "all items" and an empty set as "no items"
  (`if not ids: return []`), so an unmatched name correctly yields zero results.

## The change, end to end

All changes are small and additive.

1. **`src/vtextract/index/models.py`** — add `person: str | None = None` to
   `SearchQuery`. Defaulted, so every existing caller is unaffected.

2. **`src/vtextract/index/query.py`** — after the text-candidate block, before
   `filter_items`, add:

   ```python
   if q.person:
       person_ids = {i for hit in people_search(db, q.person) for i in hit.items}
       candidate_ids = (
           person_ids if candidate_ids is None else candidate_ids & person_ids
       )
   ```

   `people_search` is imported from `vtextract.index.people` (same subpackage).
   Ordering is unchanged: score-sorted when `q.text` is present, otherwise the
   date-ascending order from `filter_items`.

3. **`src/vtextract/tui/dialogs/search.py`** — add `person: str | None` to the
   `SearchSpec` dataclass; add `Input(placeholder="People (name)", id="person")`
   to the form; read it in `_collect()`
   (`self.query_one("#person", Input).value.strip() or None`).

4. **`src/vtextract/tui/index_client.py`** — add a `person: str | None = None`
   parameter to `IndexClient.search()` and pass it into the `SearchQuery`.

5. **`src/vtextract/tui/app.py`** — pass `person=spec.person` in
   `_on_search_submitted`.

## Edge cases

- **Unmatched name** → `people_search` returns no hits → `person_ids` is empty →
  `candidate_ids` becomes empty (or intersects to empty) → `filter_items`
  returns `[]`. Zero results, as intended.
- **Person-only (blank query)** → `candidate_ids` starts `None`, becomes the
  person's item set → all items mentioning the person, date/volume applied.
- **Blank person field** → `q.person` is `None`/empty, block is skipped,
  behaviour identical to today.

## Out of scope (YAGNI)

- Exposing the person filter on the `vtindex` CLI.
- Multi-name or boolean people queries (single free-text name only; the
  underlying FTS still matches multi-word names like "John Smith").
- Showing *which* person matched in the results rows.
- Autocomplete / suggestions of known names.

## Testing

Tests run against the committed fixtures, no network (per repo convention).

- **`query.py`**: person-only returns items mentioning the person; person + text
  returns the intersection; an unmatched name returns `[]`; blank person leaves
  results unchanged.
- **`dialogs/search.py`**: `_collect()` includes the person value (and `None`
  when blank).
- **`index_client.py`**: the `person` argument is threaded into the
  `SearchQuery`.

## Convention notes

- TDD: failing test → minimal implementation → passing test, per feature commit.
- Conventional commits (`feat:`).
- The `tui/` → index boundary is preserved: the TUI still goes through
  `IndexService` (via `IndexClient`); no new direct `db`/`query` imports in
  `tui/`.
