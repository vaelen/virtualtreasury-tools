# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

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


class ResultsScreen(CountFooterMixin, DataTable):
    BINDINGS = [
        Binding("enter", "view_first_match", "view"),
        Binding("space", "toggle_item", "toggle"),
        Binding("a", "toggle_all", "all"),
        Binding("escape", "back", "back"),
    ]

    def __init__(self, *, bundle: Bundle, results: list, query: str) -> None:
        super().__init__(cursor_type="row")
        self.bundle = bundle
        self.results = results
        self.query = query

    def on_mount(self) -> None:
        self.add_columns("Sel", "ID", "Date", "Reference", "Title")
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
        self._wire_count_footer()

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
            origin="results")

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

    def action_back(self) -> None:
        self.app.open_volumes()  # type: ignore[attr-defined]

    def selected_context(self) -> tuple | None:
        if not self.results:
            return None
        return ("item", self.results[self.cursor_row].isadg_id)
