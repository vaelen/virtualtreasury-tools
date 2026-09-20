# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from textual.binding import Binding
from textual.widgets import DataTable

from vtextract.tui.panes.sidebar import Sidebar


class PeopleTable(DataTable):
    """Read-only view of a page's ``<page_key>.names.json`` people."""

    DEFAULT_CSS = """
    PeopleTable { border: solid $accent; }
    """

    BINDINGS = [
        Binding("escape", "close", "close people"),
        Binding("p", "close", "close people"),
    ]

    def __init__(self, people: list[list[str]]) -> None:
        super().__init__(cursor_type="row", zebra_stripes=True)
        self.people = people
        self.border_title = "People"

    def on_mount(self) -> None:
        self.add_columns("Name", "As written")
        for forms in self.people:
            self.add_row(forms[0], ", ".join(forms[1:]))

    def action_close(self) -> None:
        pane = self.parent.parent if self.parent else None
        Sidebar.close(self)
        if pane is not None and pane.children:
            pane.children[0].focus()
