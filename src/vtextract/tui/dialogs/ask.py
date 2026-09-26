# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

"""Ask dialog: one question for the LLM about the current page."""

from __future__ import annotations

from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label


class AskDialog(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "dismiss(None)", "cancel")]

    def compose(self):
        with Vertical(id="ask-dialog"):
            yield Label("Ask about this page")
            yield Input(placeholder="Question", id="question")
            with Horizontal():
                yield Button("Ask", id="submit", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#question", Input).focus()

    def _submit(self) -> None:
        text = self.query_one("#question", Input).value.strip()
        self.dismiss(text or None)

    def on_button_pressed(self, ev: Button.Pressed) -> None:
        if ev.button.id == "submit":
            self._submit()
        else:
            self.dismiss(None)

    def on_input_submitted(self, _ev: Input.Submitted) -> None:
        self._submit()
