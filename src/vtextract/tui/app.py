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

    def action_request_quit(self) -> None:
        # Placeholder — Task 24 replaces this with the exit-confirm dialog.
        self.exit()
