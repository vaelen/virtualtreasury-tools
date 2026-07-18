# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

import re
from typing import Literal

from textual.binding import Binding
from textual.containers import ScrollableContainer
from textual.widgets import Static

# Imported at module top (not lazily) on purpose: textual-image queries the
# terminal for the best rendering protocol at import time, which must happen
# before the Textual app starts. This module is imported via app.py at startup.
from textual_image.widget import Image

from vtextract.theme import THEMES, highlight_phrases, highlight_terms
from vtextract.tui.archive_reader import ArchiveReader
from vtextract.tui.bundle import Bundle, PageRef
from vtextract.tui.index_client import IndexClient

_NO_IMAGE_MESSAGE = (
    "No image on disk for this page — re-run vtextract with --images to "
    "download it."
)

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def person_surface_forms(query: str | None, people: list[list[str]]) -> list[str]:
    """Surface-form phrases to highlight for a person search on one page.

    ``people`` is the page's names-sidecar persons, each a
    ``[canonical, *surface_forms]`` list. Returns the distinct forms of every
    person whose combined forms contain ALL of ``query``'s words — mirroring
    the index's person FTS match (implicit AND over canonical + aliases) — so
    searching "John Smith" picks up that person's on-page "Jno. Smith" variant
    without also lighting up a same-first-name neighbour like "John Doe". Each
    form is returned whole (not split into words) so callers can highlight it
    as an exact multi-word phrase. Empty when the searched person isn't on
    this page.
    """
    qwords = {m.group(0).lower() for m in _WORD_RE.finditer(query or "")}
    if not qwords:
        return []
    out: list[str] = []
    for forms in people:
        words = {w.lower() for f in forms for w in _WORD_RE.findall(f)}
        if qwords <= words:
            out.extend(f for f in forms if f not in out)
    return out


class TranscriptionScreen(ScrollableContainer):
    DEFAULT_CSS = """
    TranscriptionScreen {
        align-horizontal: center;
    }
    TranscriptionScreen #page-image {
        width: auto;
        height: auto;
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
                 query: str | None = None, person: str | None = None,
                 origin: str = "pages",
                 view: Literal["text", "image"] = "text", base_title: str | None = None) -> None:
        super().__init__()
        self.index = index
        self.reader = reader
        self.bundle = bundle
        self.root_id = root_id
        self.page_key = page_key
        self.query = query
        # The searched-for person (from a person-filter search), if any. Its
        # on-page surface forms get highlighted alongside the free-text query.
        self.person = person
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
        match_style = THEMES["dark"].match_style
        # Free-text query highlights word-by-word; a searched person's surface
        # forms highlight as exact multi-word phrases (line-break tolerant).
        styled = highlight_terms(text, self.query, match_style)
        if self.person:
            forms = person_surface_forms(
                self.person, self.reader.read_names(self.root_id, self.page_key))
            highlight_phrases(styled, forms, match_style)
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
        if nav and nav.previous:
            self.app.open_transcription(  # type: ignore[attr-defined]
                self.root_id, nav.previous.page_key,
                query=self.query, person=self.person,
                origin=self.origin, view=self.view)

    async def action_next_page(self) -> None:
        nav = await self.index.page(self.root_id, self.page_key)
        if nav and nav.next:
            self.app.open_transcription(  # type: ignore[attr-defined]
                self.root_id, nav.next.page_key,
                query=self.query, person=self.person,
                origin=self.origin, view=self.view)

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
