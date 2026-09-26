# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

"""Startup-time prompt: index is missing or stale → build/rebuild now?"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


State = Literal["missing", "stale"]


class IndexPromptDialog(ModalScreen[bool]):
    BINDINGS = [Binding("escape", "dismiss(False)", "cancel")]

    def __init__(self, *, state: State, archive: Path, index_path: Path) -> None:
        super().__init__()
        self.state = state
        self.archive = archive
        self.index_path = index_path

    def compose(self):
        head = ("The search index for this archive is out of date."
                if self.state == "stale"
                else "No search index exists for this archive yet.")
        question = ("Rebuild it now? (recommended)"
                    if self.state == "stale"
                    else "Build it now? (recommended)")
        with Vertical(id="index-prompt"):
            yield Static("vtbrowse", id="prompt-title")
            yield Static(head)
            yield Static(f"Archive    {self.archive}")
            yield Static(f"Index      {self.index_path}")
            yield Static(question)
            with Horizontal():
                yield Button("Yes", id="yes", variant="primary")
                yield Button("No", id="no")

    def on_button_pressed(self, ev: Button.Pressed) -> None:
        self.dismiss(ev.button.id == "yes")
