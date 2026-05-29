# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from textual.binding import Binding
from textual.containers import ScrollableContainer
from textual.widgets import Static

from vtextract.tui.archive_reader import ArchiveReader
from vtextract.tui.bundle import Bundle, PageRef
from vtextract.tui.index_client import IndexClient


class TranscriptionScreen(ScrollableContainer):
    BINDINGS = [
        Binding("left", "prev_page", "prev"),
        Binding("right", "next_page", "next"),
        Binding("space", "toggle_select", "select"),
        Binding("escape", "back", "back"),
    ]

    can_focus = True

    def __init__(self, *, index: IndexClient, reader: ArchiveReader,
                 bundle: Bundle, root_id: str, page_key: str,
                 query: str | None = None) -> None:
        super().__init__()
        self.index = index
        self.reader = reader
        self.bundle = bundle
        self.root_id = root_id
        self.page_key = page_key
        self.query = query

    def compose(self):
        text = self.reader.read_transcription(self.root_id, self.page_key) or \
            "(no transcription available for this page)"
        yield Static(text, id="transcription-body")

    def _current_ref(self) -> PageRef:
        return PageRef(self.root_id, self.page_key)

    def action_prev_page(self) -> None:
        nav = self.index.page(self.root_id, self.page_key)
        if nav and nav.get("previous"):
            self.app.open_transcription(  # type: ignore[attr-defined]
                self.root_id, nav["previous"]["page_key"])

    def action_next_page(self) -> None:
        nav = self.index.page(self.root_id, self.page_key)
        if nav and nav.get("next"):
            self.app.open_transcription(  # type: ignore[attr-defined]
                self.root_id, nav["next"]["page_key"])

    def action_toggle_select(self) -> None:
        self.bundle.toggle_page(self._current_ref())
        self.app.bundle_changed()  # type: ignore[attr-defined]

    def action_back(self) -> None:
        self.app.open_pages(self.root_id)  # type: ignore[attr-defined]
