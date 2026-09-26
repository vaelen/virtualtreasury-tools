# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

from __future__ import annotations

from enum import Enum

from rich.text import Text
from textual.binding import Binding
from textual.widgets import DataTable

from vtextract.tui.bundle import Bundle, PageRef
from vtextract.tui.count_footer import CountFooterMixin


def _sel_cell(selected: bool) -> Text:
    """The selection marker for a row. Built as ``Text`` rather than a plain
    string because Textual renders str cells through Rich markup, which would
    parse ``[x]`` as a style tag and drop it (leaving the cell blank). A ``Text``
    is shown verbatim."""
    return Text("[x]" if selected else "[ ]")


def _date_cell(result) -> str:
    """The catalog's single date: the content date, else the estimated date in
    square brackets (the ISAD(G) convention for a supplied/estimated date)."""
    content = result.content_date
    if content:
        return content
    estimated = result.estimated_date
    return f"[{estimated}]" if estimated else "-"


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


class ResultsScreen(CountFooterMixin, DataTable):
    BINDINGS = [
        Binding("enter", "view_first_match", "view"),
        Binding("space", "toggle_item", "toggle"),
        Binding("a", "toggle_all", "all"),
        Binding("d", "cycle_sort", "sort"),
        Binding("escape", "back", "back"),
    ]

    def __init__(self, *, bundle: Bundle, results: list, query: str,
                 person: str | None = None,
                 sort_mode: SortMode = SortMode.RELEVANCE,
                 initial_row: int = 0) -> None:
        super().__init__(cursor_type="row")
        self.bundle = bundle
        self.results = results
        self.query = query
        self.person = person
        self.sort_mode = sort_mode
        self.initial_row = initial_row

    def on_mount(self) -> None:
        self.add_columns("Sel", "ID", "Date", "Reference", "Title")
        self.results = sort_results(self.results, self.sort_mode)
        self._populate()
        if self.results:
            self.move_cursor(row=min(self.initial_row, len(self.results) - 1))
        self._update_title()
        self._wire_count_footer()

    def on_data_table_row_highlighted(self, _ev) -> None:
        # Remember the user's place so reopening the results restores it.
        self.app.last_results_row = self.cursor_row

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

    def action_view_first_match(self) -> None:
        if not self.results:
            return
        r = self.results[self.cursor_row]
        pages = r.matched_pages or []
        if not pages:
            return
        target = next((p for p in pages if p.role == "primary"), pages[0])
        self.app.open_transcription(  # type: ignore[attr-defined]
            target.root_id, target.page_key, query=self.query,
            person=self.person, origin="results")

    def action_toggle_item(self) -> None:
        if not self.results:
            return
        r = self.results[self.cursor_row]
        refs = [PageRef(p.root_id, p.page_key) for p in r.matched_pages]
        self.bundle.toggle_item(r.isadg_id, refs)
        in_bundle = r.isadg_id in self.bundle.selected_items
        self.update_cell_at((self.cursor_row, 0), _sel_cell(in_bundle))
        self.app.bundle_changed()  # type: ignore[attr-defined]

    def action_toggle_all(self) -> None:
        if not self.results:
            return
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

    def action_cycle_sort(self) -> None:
        if not self.results:
            return
        current_id = self.results[self.cursor_row].isadg_id
        self.sort_mode = self.sort_mode.next()
        self.app.last_results_sort = self.sort_mode
        self.results = sort_results(self.results, self.sort_mode)
        self._populate()
        for i, r in enumerate(self.results):
            if r.isadg_id == current_id:
                self.move_cursor(row=i)
                break
        self._update_title()

    def action_back(self) -> None:
        self.app.open_volumes()  # type: ignore[attr-defined]

    def selected_context(self) -> tuple | None:
        if not self.results:
            return None
        return ("item", self.results[self.cursor_row].isadg_id)
