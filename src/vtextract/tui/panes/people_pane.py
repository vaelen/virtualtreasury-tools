# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from textual.binding import Binding
from textual.widgets import DataTable

from vtextract.tui.archive_reader import ArchiveReader
from vtextract.tui.panes.sidebar import Sidebar


class PeopleTable(DataTable):
    """Read-only view of a page's ``<page_key>.names.json`` people.

    Polls the sidecar's mtime and reloads when it changes, so a re-extraction
    (P here, or `vtextract names` in another terminal) shows up by itself.
    """

    DEFAULT_CSS = """
    PeopleTable { border: solid $accent; }
    """

    BINDINGS = [
        Binding("escape", "close", "close people"),
        Binding("p", "close", "close people"),
        Binding("n", "toggle_notes", "notes"),
    ]

    POLL_SECONDS = 1.0  # ponytail: mtime poll; an fs watcher if this ever shows up in profiles

    def __init__(self, *, reader: ArchiveReader, root_id: str, page_key: str) -> None:
        super().__init__(cursor_type="row", zebra_stripes=True)
        self.reader = reader
        self.root_id = root_id
        self.page_key = page_key
        self.border_title = "People"
        self._mtime = self._current_mtime()

    def _current_mtime(self) -> float | None:
        path = self.reader.names_path(self.root_id, self.page_key)
        return path.stat().st_mtime if path.exists() else None

    def _load(self) -> None:
        self.clear()
        for forms in self.reader.read_names(self.root_id, self.page_key):
            self.add_row(forms[0], ", ".join(forms[1:]))

    def _poll(self) -> None:
        mtime = self._current_mtime()
        if mtime != self._mtime:
            self._mtime = mtime
            self._load()

    def on_mount(self) -> None:
        self.add_columns("Name", "As written")
        self._load()
        self.set_interval(self.POLL_SECONDS, self._poll)

    async def action_toggle_notes(self) -> None:
        # Delegate to the page view (sidebar's sibling) so 'n' means the same
        # thing here as it does there.
        pane = self.parent.parent if self.parent else None
        if pane is not None and pane.children:
            await pane.children[0].action_toggle_notes()

    def action_close(self) -> None:
        pane = self.parent.parent if self.parent else None
        Sidebar.close(self)
        if pane is not None and pane.children:
            pane.children[0].focus()
