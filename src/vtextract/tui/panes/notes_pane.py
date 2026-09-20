# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from textual.binding import Binding
from textual.geometry import Region
from textual.strip import Strip
from textual.widgets import TextArea

from vtextract.tui.archive_reader import ArchiveReader
from vtextract.tui.panes.sidebar import Sidebar


class NotesEditor(TextArea):
    """Markdown editor for a page's ``<page_key>.notes.md``.

    Saves whenever focus leaves it and on unmount, so every way the pane can
    go away (n, esc, paging, navigating elsewhere, quitting) persists the
    text, and actions that read the notes from disk while the editor is still
    open (P re-extract, a ask -- both pressed from the page view) see the
    latest text. Whitespace-only text removes the file instead (see
    ``ArchiveReader.write_notes``).
    """

    DEFAULT_CSS = """
    NotesEditor { border: solid $accent; }
    """

    BINDINGS = [Binding("escape", "close", "close notes")]

    def __init__(self, *, reader: ArchiveReader, root_id: str, page_key: str) -> None:
        super().__init__(reader.read_notes(root_id, page_key), language="markdown")
        self.reader = reader
        self.root_id = root_id
        self.page_key = page_key
        self.border_title = "Notes"

    def render_lines(self, crop: Region) -> list[Strip]:
        # Textual #6208: a pruned TextArea has its component styles cleared but
        # can still be painted from the compositor's stale map (a mouse move
        # over its old area right after esc), and TextArea.render_lines applies
        # CSS first, so it raises KeyError. Paint nothing instead.
        if not self.is_attached:
            return [Strip.blank(crop.width)] * crop.height
        return super().render_lines(crop)

    def _save(self) -> None:
        self.reader.write_notes(self.root_id, self.page_key, self.text)

    def on_blur(self) -> None:
        self._save()

    def on_unmount(self) -> None:
        self._save()

    def action_close(self) -> None:
        # Hand focus back to the transcription before we go, so its bindings
        # (n, arrows, esc) keep working.
        pane = self.parent.parent if self.parent else None
        Sidebar.close(self)
        if pane is not None and pane.children:
            pane.children[0].focus()
