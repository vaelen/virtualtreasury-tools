# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Header

from vtextract.tui.bundle import Bundle
from vtextract.tui.index_client import IndexClient
from vtextract.tui.panes.bundle_pane import BundlePane
from vtextract.tui.panes.document_pane import DocumentPane
from vtextract.tui.screens.pages import PagesScreen
from vtextract.tui.screens.volumes import VolumesScreen


class VtBrowseApp(App):
    TITLE = "vtbrowse"
    CSS = """
    Screen { layout: vertical; }
    Horizontal { height: 1fr; }
    """

    BINDINGS = [
        Binding("ctrl+x", "request_quit", "exit"),
        Binding("tab", "focus_next", "switch pane"),
    ]

    def __init__(self, *, archive: Path) -> None:
        super().__init__()
        self.archive = archive
        self.index = IndexClient(archive)
        self.bundle = Bundle()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal():
            yield BundlePane(self.bundle)
            yield DocumentPane()
        yield Footer()

    def on_mount(self) -> None:
        self.open_volumes()

    def open_volumes(self) -> None:
        pane = self.query_one(DocumentPane)
        pane.remove_children()
        screen = VolumesScreen(self.index)
        pane.mount(screen)
        self.call_after_refresh(screen.focus)

    def open_pages(self, root_id: str) -> None:
        pane = self.query_one(DocumentPane)
        pane.remove_children()
        screen = PagesScreen(index=self.index, bundle=self.bundle, root_id=root_id)
        pane.mount(screen)
        self.call_after_refresh(screen.focus)

    def open_transcription(self, root_id: str, page_key: str,
                           *, query: str | None = None) -> None:
        # Task 17 implements the real TranscriptionScreen. Stub for now.
        self.notify(f"open_transcription({root_id!r}, {page_key!r}) — Task 17",
                    severity="information")

    def bundle_changed(self) -> None:
        self.query_one(BundlePane).refresh_content()

    def action_request_quit(self) -> None:
        # Placeholder — Task 24 replaces this with the exit-confirm dialog.
        self.exit()
