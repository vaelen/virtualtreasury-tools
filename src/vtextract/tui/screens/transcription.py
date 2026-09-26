# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

from __future__ import annotations

import asyncio
import re
from typing import Literal

from rich.markup import escape
from textual.binding import Binding
from textual.containers import ScrollableContainer
from textual.widgets import Markdown, Static

# Imported at module top (not lazily) on purpose: textual-image queries the
# terminal for the best rendering protocol at import time, which must happen
# before the Textual app starts. This module is imported via app.py at startup.
from textual_image.widget import Image

from vtextract.ask import PageContext, build_messages, transcript_markdown
from vtextract.theme import THEMES, highlight_phrases, highlight_terms
from vtextract.tui.archive_reader import ArchiveReader
from vtextract.tui.bundle import Bundle, PageRef
from vtextract.tui.dialogs.ask import AskDialog
from vtextract.tui.dialogs.file import FileDialog, FileResult
from vtextract.tui.index_client import IndexClient
from vtextract.tui.panes.notes_pane import NotesEditor
from vtextract.tui.panes.people_pane import PeopleTable
from vtextract.tui.panes.sidebar import Sidebar

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
        width: 1fr;
    }
    TranscriptionScreen #page-image {
        width: auto;
        height: auto;
    }
    """

    BINDINGS = [
        Binding("left", "prev_page", "prev"),
        Binding("right", "next_page", "next"),
        Binding("enter", "toggle_view", "view"),
        Binding("n", "toggle_notes", "notes"),
        Binding("p", "toggle_people", "people"),
        Binding("a", "ask", "ask"),
        Binding("w", "write_answers", "write answers", show=False),
        Binding("P", "reextract", "re-extract names", show=False),
        Binding("space", "toggle_select", "select"),
        Binding("escape", "back", "back"),
    ]

    can_focus = True

    def __init__(self, *, index: IndexClient, reader: ArchiveReader,
                 bundle: Bundle, root_id: str, page_key: str,
                 query: str | None = None, person: str | None = None,
                 origin: str = "pages",
                 view: Literal["text", "image", "ask"] = "text",
                 base_title: str | None = None) -> None:
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
        # "text" shows the transcription; "image" the page scan; "ask" the
        # page's LLM Q&A transcript (only offered once a question was asked).
        # Cycled with enter and preserved across prev/next paging.
        self.view = view
        # Question in flight (shown with a "thinking" marker in the ask view).
        self._pending: str | None = None
        # Pane title without the mode suffix; used to re-derive the title when
        # toggling between the text and image views.
        self.base_title = base_title or page_key

    def compose(self):
        yield self._build_body()

    # ---------- views ----------

    def title_for_view(self) -> str:
        # Escaped: a bare "[image]" reads as a Rich markup tag and vanishes.
        suffix = {"image": " [image]", "ask": " [ask]"}.get(self.view, "")
        return self.base_title + escape(suffix)

    def _history_key(self) -> tuple[str, str]:
        return (self.root_id, self.page_key)

    def _history(self) -> list[tuple[str, str]]:
        return self.app.ask_history.get(self._history_key(), [])  # type: ignore[attr-defined]

    def _ask_markdown(self) -> str:
        md = transcript_markdown(self.page_key, self._history())
        if self._pending:
            md += f"\n## {self._pending.strip()}\n\n_Thinking…_\n"
        return md

    def _build_body(self):
        if self.view == "ask":
            return Markdown(self._ask_markdown(), id="ask-body")
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

    async def _show_view(self, view: str) -> None:
        self.view = view  # type: ignore[assignment]
        await self.remove_children()
        await self.mount(self._build_body())
        self.app.set_pane_title(self.title_for_view())  # type: ignore[attr-defined]

    async def action_toggle_view(self) -> None:
        order = ["text", "image"] + (["ask"] if self._history() or self._pending else [])
        nxt = order[(order.index(self.view) + 1) % len(order)] if self.view in order else "text"
        await self._show_view(nxt)

    # ---------- ask (a) / write answers (w) ----------

    def action_ask(self) -> None:
        def on_question(question: str | None) -> None:
            if question:
                self.run_worker(self._run_ask(question), group="ask")
        self.app.push_screen(AskDialog(), on_question)

    async def _gather_context(self) -> tuple[PageContext, bytes | None]:
        nav = await self.index.page(self.root_id, self.page_key)
        vol = self.reader.read_volume_meta(self.root_id) or {}
        ctx = PageContext(
            root_id=self.root_id, page_key=self.page_key,
            volume_label=vol.get("label"), volume_title=vol.get("title"),
            reference_code=vol.get("reference_code"),
            ordinal=nav.current.ordinal if nav else None,
            label=nav.current.label if nav else None,
            transcription=self.reader.read_transcription(self.root_id, self.page_key),
            notes=self.reader.read_notes(self.root_id, self.page_key) or None,
            people=self.reader.read_names(self.root_id, self.page_key),
        )
        image = None
        if self.reader.image_exists(self.root_id, self.page_key):
            image = self.reader.image_path(self.root_id, self.page_key).read_bytes()
        return ctx, image

    async def _run_ask(self, question: str) -> None:
        app = self.app
        self._pending = question
        await self._show_view("ask")
        ctx, image = await self._gather_context()
        messages = build_messages(ctx, history=list(self._history()),
                                  question=question, image=image)
        loop = asyncio.get_running_loop()
        try:
            answer = await loop.run_in_executor(
                None, lambda: app.ask_fn(messages, app.ask_model, app.ask_api_base))  # type: ignore[attr-defined]
        except Exception as exc:
            from vtextract.names.llm import friendly_error  # lazy: litellm import
            answer = f"**Error:** {friendly_error(exc, app.ask_model, app.ask_api_base)}"  # type: ignore[attr-defined]
        app.ask_history.setdefault(self._history_key(), []).append((question, answer))  # type: ignore[attr-defined]
        self._pending = None
        if self.is_attached and self.view == "ask":
            await self.query_one("#ask-body", Markdown).update(self._ask_markdown())

    # ---------- re-extract names (P) ----------

    def action_reextract(self) -> None:
        self.run_worker(self._run_reextract(), group="reextract")

    async def _run_reextract(self) -> None:
        app = self.app
        cfg = app.names_config  # type: ignore[attr-defined]
        page = f"{self.root_id}/{self.page_key}"
        app.notify(f"Extracting names for {page} with {cfg.model}…")

        def run():
            from vtextract.names import extractor  # lazy: pulls in litellm
            return extractor.extract(
                app.archive, model=cfg.model, api_base=cfg.api_base,  # type: ignore[attr-defined]
                chunk_size=cfg.chunk_size, overlap=cfg.overlap,
                dense_threshold=cfg.dense_threshold,
                dense_chunk_size=cfg.dense_chunk_size,
                max_output_tokens=cfg.max_output_tokens,
                scope_pages={(self.root_id, self.page_key)},
                force=True, show_progress=False)

        try:
            stats = await asyncio.get_running_loop().run_in_executor(None, run)
        except Exception as exc:
            app.notify(f"Names extraction failed for {page}: {exc}", severity="error")
            return
        if not stats.extracted:
            app.notify(f"Names extraction failed for {page} "
                       "(the page's .names.error.json has details if it was parked).",
                       severity="error")
            return
        # Re-index so people search sees the new sidecar.
        async for _ev in self.index.build_stream():
            pass
        app.notify(f"Extracted {stats.people} people for {page}")
        # An open people table reloads itself (it polls the sidecar's mtime).

    def action_write_answers(self) -> None:
        if not self._history():
            self.app.notify("Nothing to write: ask a question first (a).", severity="warning")
            return
        page_dir = self.reader.notes_path(self.root_id, self.page_key).parent
        self.app.push_screen(
            FileDialog(mode="save", start_dir=page_dir, title="Write answers",
                       default_name=f"{self.page_key}.ask", suffix=".md"),
            self._on_write_chosen)

    def _on_write_chosen(self, result: FileResult | None) -> None:
        if result is None:
            return
        result.path.write_text(transcript_markdown(self.page_key, self._history()))
        self.app.notify(f"Wrote {result.path}")

    async def action_toggle_notes(self) -> None:
        """Open the page's notes.md beside this view, or close (and save) it."""
        open_editors = self.parent.query(NotesEditor)
        if open_editors:
            open_editors.first().action_close()
            return
        editor = NotesEditor(reader=self.reader, root_id=self.root_id,
                             page_key=self.page_key)
        await Sidebar.open(self.parent, editor, on_top=True)
        editor.focus()

    async def action_toggle_people(self) -> None:
        """Show the page's names.json people below the notes, or close them."""
        open_tables = self.parent.query(PeopleTable)
        if open_tables:
            open_tables.first().action_close()
            return
        if not self.reader.names_path(self.root_id, self.page_key).exists():
            self.app.notify("Names have not been extracted from this document yet "
                            "(run vtextract names).", severity="warning")
            return
        table = PeopleTable(reader=self.reader, root_id=self.root_id,
                            page_key=self.page_key)
        await Sidebar.open(self.parent, table)
        table.focus()

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
        self.app.ask_history.clear()  # closing the document drops its Q&A  # type: ignore[attr-defined]
        if self.origin == "results":
            self.app.action_open_results()  # type: ignore[attr-defined]
        else:
            self.app.open_pages(self.root_id)  # type: ignore[attr-defined]

    def selected_context(self) -> tuple | None:
        return ("page", self.root_id, self.page_key)
