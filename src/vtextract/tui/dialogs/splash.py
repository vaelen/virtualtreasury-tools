# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

"""Centered loading splash shown while vtbrowse is busy with slow work.

A centered, app-dismissed modal with a single live status line. It traps no
keys and returns no result. Used at startup (``VtBrowseApp.on_mount`` pushes it
while the index opens + volumes load) and reused, with different text, as the
"Searching…" modal so a slow search shows feedback instead of appearing hung.
"""

from __future__ import annotations

from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


class SplashScreen(ModalScreen[None]):
    def __init__(self, *, title: str = "vtbrowse",
                 subtitle: str = "Virtual Record Treasury browser",
                 status: str = "Opening index…") -> None:
        super().__init__()
        self._title = title
        self._subtitle = subtitle
        self._status = status

    def compose(self):
        with Vertical(id="splash-dialog"):
            yield Static(self._title, id="splash-title")
            yield Static(self._subtitle, id="splash-subtitle")
            yield Static(self._status, id="splash-status")

    def set_status(self, text: str) -> None:
        self.query_one("#splash-status", Static).update(text)
