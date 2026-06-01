# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""Startup splash shown while vtbrowse opens the index and loads volumes.

A centered, app-dismissed modal with a single live status line. It traps no
keys and returns no result: ``VtBrowseApp.on_mount`` pushes it first thing and
dismisses it once startup work (index open + volumes load) is done, after a
minimum display interval so a fast load does not flash it.
"""

from __future__ import annotations

from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


class SplashScreen(ModalScreen[None]):
    def compose(self):
        with Vertical(id="splash-dialog"):
            yield Static("vtbrowse", id="splash-title")
            yield Static("Virtual Record Treasury browser", id="splash-subtitle")
            yield Static("Opening index…", id="splash-status")

    def set_status(self, text: str) -> None:
        self.query_one("#splash-status", Static).update(text)
