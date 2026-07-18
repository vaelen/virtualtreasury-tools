# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from typing import Literal

from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

Choice = Literal["save_and_exit", "exit", "cancel"]


class ExitDialog(ModalScreen[Choice]):
    BINDINGS = [Binding("escape", "dismiss('cancel')", "cancel")]

    def __init__(self, *, page_count: int, item_count: int,
                 dirty: bool = True) -> None:
        super().__init__()
        self.page_count = page_count
        self.item_count = item_count
        # Clean bundle: plain quit confirmation — no save option, no
        # unsaved-changes warning (there is nothing to save).
        self.dirty = dirty

    def compose(self):
        with Vertical(id="exit-dialog"):
            yield Static("Quit vtbrowse")
            if self.dirty:
                yield Static(f"Bundle has {self.page_count} pages from "
                             f"{self.item_count} items.")
                yield Static("Unsaved changes will be lost.")
            with Horizontal():
                if self.dirty:
                    yield Button("Save & quit", id="save_and_exit",
                                 variant="primary")
                yield Button("Quit",   id="exit")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, ev: Button.Pressed) -> None:
        self.dismiss(ev.button.id)  # type: ignore[arg-type]
