# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from textual.binding import Binding
from textual.widgets import DataTable

from vtextract.tui.index_client import IndexClient


class VolumesScreen(DataTable):
    BINDINGS = [Binding("enter", "open_volume", "open volume")]

    def __init__(self, index: IndexClient) -> None:
        super().__init__(cursor_type="row")
        self.index = index
        self._row_root_ids: list[str] = []

    def on_mount(self) -> None:
        self.add_columns("Root ID", "Items", "Title", "Reference")
        for v in self.index.volumes():
            self.add_row(
                v["root_id"],
                str(v["item_count"]),
                v.get("title") or v.get("label") or "-",
                v.get("reference_code") or "-",
            )
            self._row_root_ids.append(v["root_id"])
        if self._row_root_ids:
            self.move_cursor(row=0)

    def action_open_volume(self) -> None:
        if not self._row_root_ids:
            return
        root_id = self._row_root_ids[self.cursor_row]
        self.app.open_pages(root_id)  # type: ignore[attr-defined]
