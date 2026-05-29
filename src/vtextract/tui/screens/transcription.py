# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from typing import Literal

from textual.binding import Binding
from textual.containers import ScrollableContainer
from textual.widgets import Static

# Imported at module top (not lazily) on purpose: textual-image queries the
# terminal for the best rendering protocol at import time, which must happen
# before the Textual app starts. This module is imported via app.py at startup.
from textual_image.widget import Image

from vtextract.theme import THEMES, highlight_terms
from vtextract.tui.archive_reader import ArchiveReader
from vtextract.tui.bundle import Bundle, PageRef
from vtextract.tui.index_client import IndexClient

_NO_IMAGE_MESSAGE = (
    "No image on disk for this page — re-run vtextract with --images to "
    "download it."
)


class TranscriptionScreen(ScrollableContainer):
    DEFAULT_CSS = """
    TranscriptionScreen #page-image {
        width: 100%;
        height: 100%;
    }
    """

    BINDINGS = [
        Binding("left", "prev_page", "prev"),
        Binding("right", "next_page", "next"),
        Binding("enter", "toggle_view", "image"),
        Binding("space", "toggle_select", "select"),
        Binding("escape", "back", "back"),
    ]

    can_focus = True

    def __init__(self, *, index: IndexClient, reader: ArchiveReader,
                 bundle: Bundle, root_id: str, page_key: str,
                 query: str | None = None, origin: str = "pages",
                 view: Literal["text", "image"] = "text", base_title: str | None = None) -> None:
        super().__init__()
        self.index = index
        self.reader = reader
        self.bundle = bundle
        self.root_id = root_id
        self.page_key = page_key
        self.query = query
        # Where this view was opened from, so ``esc`` (action_back) returns
        # there: "results" → the search results screen, "pages" → the volume's
        # page list. Preserved across prev/next page navigation.
        self.origin = origin
        # "text" shows the transcription; "image" shows the page scan. Toggled
        # with enter and preserved across prev/next paging.
        self.view = view
        # Pane title without the mode suffix; used to re-derive the title when
        # toggling between the text and image views.
        self.base_title = base_title or page_key

    def compose(self):
        yield self._build_body()

    def _build_body(self):
        if self.view == "image":
            if self.reader.image_exists(self.root_id, self.page_key):
                return Image(
                    self.reader.image_path(self.root_id, self.page_key),
                    id="page-image",
                )
            return Static(_NO_IMAGE_MESSAGE, id="page-image-missing")
        text = self.reader.read_transcription(self.root_id, self.page_key) or \
            "(no transcription available for this page)"
        styled = highlight_terms(text, self.query, THEMES["dark"].match_style)
        return Static(styled, id="transcription-body")

    def _current_ref(self) -> PageRef:
        return PageRef(self.root_id, self.page_key)

    async def action_toggle_view(self) -> None:
        self.view = "image" if self.view == "text" else "text"
        await self.remove_children()
        await self.mount(self._build_body())
        suffix = " [image]" if self.view == "image" else ""
        self.app.set_pane_title(self.base_title + suffix)  # type: ignore[attr-defined]

    async def action_prev_page(self) -> None:
        nav = await self.index.page(self.root_id, self.page_key)
        if nav and nav.get("previous"):
            self.app.open_transcription(  # type: ignore[attr-defined]
                self.root_id, nav["previous"]["page_key"],
                query=self.query, origin=self.origin, view=self.view)

    async def action_next_page(self) -> None:
        nav = await self.index.page(self.root_id, self.page_key)
        if nav and nav.get("next"):
            self.app.open_transcription(  # type: ignore[attr-defined]
                self.root_id, nav["next"]["page_key"],
                query=self.query, origin=self.origin, view=self.view)

    def action_toggle_select(self) -> None:
        self.bundle.toggle_page(self._current_ref())
        self.app.bundle_changed()  # type: ignore[attr-defined]

    def action_back(self) -> None:
        if self.origin == "results":
            self.app.action_open_results()  # type: ignore[attr-defined]
        else:
            self.app.open_pages(self.root_id)  # type: ignore[attr-defined]

    def selected_context(self) -> tuple | None:
        return ("page", self.root_id, self.page_key)
