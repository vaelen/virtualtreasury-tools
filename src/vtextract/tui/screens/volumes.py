# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

from __future__ import annotations

from textual.binding import Binding
from textual.widgets import DataTable

from vtextract.tui.count_footer import CountFooterMixin
from vtextract.tui.index_client import IndexClient


class VolumesScreen(CountFooterMixin, DataTable):
    BINDINGS = [Binding("enter", "open_volume", "open volume")]

    def __init__(self, index: IndexClient) -> None:
        super().__init__(cursor_type="row")
        self.index = index
        self._row_root_ids: list[str] = []
        self._row_titles: list[str] = []

    async def on_mount(self) -> None:
        self.add_columns("Root ID", "Items", "Title", "Reference")
        for v in await self.index.volumes():
            title = v.title or v.label or v.root_id
            self.add_row(
                v.root_id,
                str(v.item_count),
                title,
                v.reference_code or "-",
            )
            self._row_root_ids.append(v.root_id)
            self._row_titles.append(title)
        if self._row_root_ids:
            self.move_cursor(row=0)
        self._wire_count_footer()

    def action_open_volume(self) -> None:
        if not self._row_root_ids:
            return
        root_id = self._row_root_ids[self.cursor_row]
        title = self._row_titles[self.cursor_row]
        self.app.open_pages(root_id, title=title)  # type: ignore[attr-defined]

    def selected_context(self) -> tuple | None:
        if not self._row_root_ids:
            return None
        return ("volume", self._row_root_ids[self.cursor_row])
