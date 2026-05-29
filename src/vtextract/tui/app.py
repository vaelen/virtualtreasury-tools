# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Header

from vtextract.tui.archive_reader import ArchiveReader
from vtextract.tui.bundle import Bundle
from vtextract.tui.dialogs.info import (
    ItemInfoDialog,
    PageInfoDialog,
    VolumeInfoDialog,
)
from vtextract.tui.dialogs.search import SearchDialog, SearchSpec
from vtextract.tui.index_client import IndexClient
from vtextract.tui.panes.bundle_pane import BundlePane
from vtextract.tui.panes.document_pane import DocumentPane
from vtextract.tui.screens.pages import PagesScreen
from vtextract.tui.screens.results import ResultsScreen
from vtextract.tui.screens.transcription import TranscriptionScreen
from vtextract.tui.screens.volumes import VolumesScreen


class VtBrowseApp(App):
    TITLE = "vtbrowse"
    CSS = """
    Screen { layout: vertical; }
    Horizontal { height: 1fr; }
    """

    BINDINGS = [
        Binding("ctrl+x", "request_quit", "exit"),
        Binding("ctrl+f", "open_search", "search"),
        Binding("ctrl+r", "open_results", "results"),
        Binding("ctrl+v", "open_volumes", "volumes"),
        Binding("ctrl+i", "open_info", "info"),
        Binding("tab", "focus_next", "switch pane"),
    ]

    def __init__(self, *, archive: Path) -> None:
        super().__init__()
        self.archive = archive
        self.index = IndexClient(archive)
        self.bundle = Bundle()
        self.last_results: list[dict] = []
        self.last_query: str | None = None
        self.current_root_id: str | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal():
            yield BundlePane(self.bundle)
            yield DocumentPane()
        yield Footer()

    def on_mount(self) -> None:
        self.open_volumes()

    def open_volumes(self) -> None:
        self.current_root_id = None
        pane = self.query_one(DocumentPane)
        pane.remove_children()
        screen = VolumesScreen(self.index)
        pane.mount(screen)
        self.call_after_refresh(screen.focus)

    def open_pages(self, root_id: str) -> None:
        self.current_root_id = root_id
        pane = self.query_one(DocumentPane)
        pane.remove_children()
        screen = PagesScreen(index=self.index, bundle=self.bundle, root_id=root_id)
        pane.mount(screen)
        self.call_after_refresh(screen.focus)

    def open_transcription(self, root_id: str, page_key: str,
                           *, query: str | None = None) -> None:
        pane = self.query_one(DocumentPane)
        pane.remove_children()
        screen = TranscriptionScreen(
            index=self.index, reader=ArchiveReader(self.archive),
            bundle=self.bundle, root_id=root_id, page_key=page_key,
            query=query,
        )
        pane.mount(screen)
        self.call_after_refresh(screen.focus)

    def bundle_changed(self) -> None:
        self.query_one(BundlePane).refresh_content()

    def action_request_quit(self) -> None:
        # Placeholder — Task 24 replaces this with the exit-confirm dialog.
        self.exit()

    # ---------- search flow ----------

    def action_open_search(self) -> None:
        self.push_screen(SearchDialog(default_volume=self.current_root_id),
                         self._on_search_submitted)

    def _on_search_submitted(self, spec: SearchSpec | None) -> None:
        if spec is None:
            return
        rows = self.index.search(
            query=spec.query, fields=spec.fields,
            date_from=spec.date_from, date_to=spec.date_to,
            date_type=spec.date_type, volume=spec.volume,
        )
        self.last_results = rows
        self.last_query = spec.query
        self.action_open_results()

    def action_open_results(self) -> None:
        if not self.last_results:
            return
        pane = self.query_one(DocumentPane)
        pane.remove_children()
        screen = ResultsScreen(
            bundle=self.bundle,
            results=self.last_results,
            query=self.last_query or "",
        )
        pane.mount(screen)
        self.call_after_refresh(screen.focus)

    def action_open_volumes(self) -> None:
        self.open_volumes()

    # ---------- info dispatch ----------

    def action_open_info(self) -> None:
        pane = self.query_one(DocumentPane)
        if not pane.children:
            return
        screen_widget = pane.children[0]
        ctx = getattr(screen_widget, "selected_context", lambda: None)()
        if ctx is None:
            return
        if ctx[0] == "volume":
            dialog = VolumeInfoDialog(index=self.index, bundle=self.bundle,
                                      root_id=ctx[1])
        elif ctx[0] == "item":
            dialog = ItemInfoDialog(index=self.index, bundle=self.bundle,
                                    isadg_id=ctx[1])
        elif ctx[0] == "page":
            dialog = PageInfoDialog(index=self.index,
                                    reader=ArchiveReader(self.archive),
                                    bundle=self.bundle,
                                    root_id=ctx[1], page_key=ctx[2])
        else:
            return
        self.push_screen(dialog)
