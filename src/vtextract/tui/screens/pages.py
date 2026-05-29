# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from textual.binding import Binding
from textual.widgets import DataTable

from vtextract.tui.bundle import Bundle, PageRef
from vtextract.tui.index_client import IndexClient


class PagesScreen(DataTable):
    BINDINGS = [
        Binding("enter", "view_page", "view"),
        Binding("space", "toggle_select", "select"),
        Binding("escape", "back", "back"),
    ]

    def __init__(self, *, index: IndexClient, bundle: Bundle, root_id: str) -> None:
        super().__init__(cursor_type="row")
        self.index = index
        self.bundle = bundle
        self.root_id = root_id
        self._pages: list[dict] = []

    def on_mount(self) -> None:
        self.add_columns("#", "Page key", "Txt", "Img", "Sel")
        self._pages = self.index.pages(self.root_id)
        for p in self._pages:
            self._add(p)
        if self._pages:
            self.move_cursor(row=0)

    def _add(self, p: dict) -> None:
        ref = PageRef(self.root_id, p["page_key"])
        self.add_row(
            str(p["ordinal"]),
            p["page_key"],
            "•" if p.get("transcription") else "",
            "•" if p.get("image") else "",
            "*" if self.bundle.is_in_bundle(ref) else "",
        )

    def action_view_page(self) -> None:
        if not self._pages:
            return
        p = self._pages[self.cursor_row]
        self.app.open_transcription(self.root_id, p["page_key"])  # type: ignore[attr-defined]

    def action_toggle_select(self) -> None:
        if not self._pages:
            return
        p = self._pages[self.cursor_row]
        ref = PageRef(self.root_id, p["page_key"])
        self.bundle.toggle_page(ref)
        self.app.bundle_changed()  # type: ignore[attr-defined]
        self.update_cell_at(
            (self.cursor_row, 4),
            "*" if self.bundle.is_in_bundle(ref) else "",
        )

    def action_back(self) -> None:
        self.app.open_volumes()  # type: ignore[attr-defined]

    def selected_context(self) -> tuple | None:
        if not self._pages:
            return None
        p = self._pages[self.cursor_row]
        return ("page", self.root_id, p["page_key"])
