# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from textual.binding import Binding
from textual.widgets import DataTable

from vtextract.tui.bundle import Bundle, PageRef
from vtextract.tui.count_footer import CountFooterMixin
from vtextract.tui.index_client import IndexClient


class PagesScreen(CountFooterMixin, DataTable):
    BINDINGS = [
        Binding("enter", "view_page", "view"),
        Binding("space", "toggle_select", "select"),
        Binding("a", "toggle_all", "all"),
        Binding("escape", "back", "back"),
    ]

    def __init__(self, *, index: IndexClient, bundle: Bundle, root_id: str,
                 initial_row: int = 0) -> None:
        super().__init__(cursor_type="row")
        self.index = index
        self.bundle = bundle
        self.root_id = root_id
        self.initial_row = initial_row
        self._pages: list = []

    async def on_mount(self) -> None:
        self.add_columns("#", "Page key", "Txt", "Img", "Sel")
        self._pages = await self.index.pages(self.root_id)
        for p in self._pages:
            self._add(p)
        if self._pages:
            self.move_cursor(row=min(self.initial_row, len(self._pages) - 1))
        self._wire_count_footer()

    def on_data_table_row_highlighted(self, _ev) -> None:
        # Remember the user's place so reopening this volume's list restores it.
        self.app.last_pages_root = self.root_id
        self.app.last_pages_row = self.cursor_row

    def _add(self, p) -> None:
        ref = PageRef(self.root_id, p.page_key)
        self.add_row(
            str(p.ordinal),
            p.page_key,
            "•" if p.transcription else "",
            "•" if p.image else "",
            "*" if self.bundle.is_in_bundle(ref) else "",
        )

    def action_view_page(self) -> None:
        if not self._pages:
            return
        p = self._pages[self.cursor_row]
        self.app.open_transcription(self.root_id, p.page_key)  # type: ignore[attr-defined]

    def action_toggle_select(self) -> None:
        if not self._pages:
            return
        p = self._pages[self.cursor_row]
        ref = PageRef(self.root_id, p.page_key)
        self.bundle.toggle_page(ref)
        self.app.bundle_changed()  # type: ignore[attr-defined]
        self.update_cell_at(
            (self.cursor_row, 4),
            "*" if self.bundle.is_in_bundle(ref) else "",
        )

    def action_toggle_all(self) -> None:
        if not self._pages:
            return
        refs = [PageRef(self.root_id, p.page_key) for p in self._pages]
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

    def action_back(self) -> None:
        self.app.open_volumes()  # type: ignore[attr-defined]

    def selected_context(self) -> tuple | None:
        if not self._pages:
            return None
        p = self._pages[self.cursor_row]
        return ("page", self.root_id, p.page_key)
