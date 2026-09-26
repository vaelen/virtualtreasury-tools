# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

from __future__ import annotations

from textual.containers import Container
from textual.widgets import Static


class DocumentPane(Container):
    """Holds the currently-active screen widget (volumes / pages / etc.)."""

    # horizontal so a NotesEditor can sit beside the active screen widget
    DEFAULT_CSS = "DocumentPane { border: solid $accent; layout: horizontal; }"

    def __init__(self) -> None:
        super().__init__()
        self.border_title = "Volumes"

    def compose(self):
        yield Static("loading...", id="doc-placeholder")
