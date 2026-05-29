# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from textual.binding import Binding
from textual.widgets import DataTable

from vtextract.tui.bundle import Bundle, PageRef


class ResultsScreen(DataTable):
    BINDINGS = [
        Binding("enter", "view_first_match", "view"),
        Binding("space", "toggle_item", "toggle"),
        Binding("escape", "back", "back"),
    ]

    def __init__(self, *, bundle: Bundle, results: list[dict], query: str) -> None:
        super().__init__(cursor_type="row")
        self.bundle = bundle
        self.results = results
        self.query = query

    def on_mount(self) -> None:
        self.add_columns("Sel", "ID", "Date", "Est.", "Reference", "Title")
        for r in self.results:
            in_bundle = r["isadg_id"] in self.bundle.selected_items
            self.add_row(
                "[x]" if in_bundle else "[ ]",
                str(r["isadg_id"]),
                r.get("content_date") or "-",
                r.get("estimated_date") or "-",
                r.get("reference_code") or "-",
                r.get("title") or "-",
            )
        if self.results:
            self.move_cursor(row=0)

    def action_view_first_match(self) -> None:
        if not self.results:
            return
        r = self.results[self.cursor_row]
        pages = r.get("matched_pages") or []
        if not pages:
            return
        target = next((p for p in pages if p.get("role") == "primary"), pages[0])
        self.app.open_transcription(  # type: ignore[attr-defined]
            target["root_id"], target["page_key"], query=self.query)

    def action_toggle_item(self) -> None:
        if not self.results:
            return
        r = self.results[self.cursor_row]
        refs = [PageRef(p["root_id"], p["page_key"])
                for p in r.get("matched_pages", [])]
        self.bundle.toggle_item(r["isadg_id"], refs)
        in_bundle = r["isadg_id"] in self.bundle.selected_items
        self.update_cell_at((self.cursor_row, 0),
                            "[x]" if in_bundle else "[ ]")
        self.app.bundle_changed()  # type: ignore[attr-defined]

    def action_back(self) -> None:
        self.app.open_volumes()  # type: ignore[attr-defined]
