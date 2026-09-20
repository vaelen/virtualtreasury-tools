# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from textual.binding import Binding
from textual.widgets import TextArea

from vtextract.tui.archive_reader import ArchiveReader


class NotesEditor(TextArea):
    """Markdown editor for a page's ``<page_key>.notes.md``.

    Saves on unmount, so every way the pane can go away (n, esc, paging,
    navigating elsewhere, quitting) persists the text. Whitespace-only text
    removes the file instead (see ``ArchiveReader.write_notes``).
    """

    DEFAULT_CSS = """
    NotesEditor { width: 1fr; border: solid $accent; }
    """

    BINDINGS = [Binding("escape", "close", "close notes")]

    def __init__(self, *, reader: ArchiveReader, root_id: str, page_key: str) -> None:
        super().__init__(reader.read_notes(root_id, page_key), language="markdown")
        self.reader = reader
        self.root_id = root_id
        self.page_key = page_key
        self.border_title = "Notes"

    def on_unmount(self) -> None:
        self.reader.write_notes(self.root_id, self.page_key, self.text)

    def action_close(self) -> None:
        # Hand focus back to the transcription before we go, so its bindings
        # (n, arrows, esc) keep working.
        prev = self.parent.children[0] if self.parent else None
        self.remove()
        if prev is not None:
            prev.focus()
