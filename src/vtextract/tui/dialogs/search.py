# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from dataclasses import dataclass

from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, RadioButton, RadioSet


@dataclass
class SearchSpec:
    query: str
    fields: tuple[str, ...]
    date_from: str | None
    date_to: str | None
    date_type: str
    volume: str | None


class SearchDialog(ModalScreen[SearchSpec | None]):
    BINDINGS = [Binding("escape", "dismiss(None)", "cancel")]

    def __init__(self, *, default_volume: str | None = None) -> None:
        super().__init__()
        self.default_volume = default_volume

    def compose(self):
        with Container(id="search-dialog"):
            yield Label("Search")
            yield Input(placeholder="Query", id="query")
            yield Label("Search in:")
            yield Horizontal(
                Checkbox("Title", value=True, id="f-title"),
                Checkbox("Description", value=True, id="f-description"),
                Checkbox("Transcription", value=True, id="f-transcription"),
            )
            yield Label("Date type")
            yield RadioSet(
                RadioButton("Content", value=True, id="dt-content"),
                RadioButton("Created", id="dt-created"),
                id="date-type",
            )
            yield Horizontal(
                Input(placeholder="From (YYYY or YYYY-MM-DD)", id="from"),
                Input(placeholder="To", id="to"),
            )
            yield Input(placeholder="Volume (root id, optional)",
                        id="volume", value=self.default_volume or "")
            yield Horizontal(
                Button("Search", id="submit", variant="primary"),
                Button("Cancel", id="cancel"),
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit":
            self.dismiss(self._collect())
        elif event.button.id == "cancel":
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(self._collect())

    def _collect(self) -> SearchSpec:
        def field(cb_id: str) -> bool:
            return self.query_one(f"#{cb_id}", Checkbox).value
        fields = tuple(name for name, present in (
            ("title", field("f-title")),
            ("description", field("f-description")),
            ("transcription", field("f-transcription")),
        ) if present)
        date_type = "created" if self.query_one(
            "#dt-created", RadioButton).value else "content"
        return SearchSpec(
            query=self.query_one("#query", Input).value.strip(),
            fields=fields,
            date_from=self.query_one("#from", Input).value.strip() or None,
            date_to=self.query_one("#to", Input).value.strip() or None,
            date_type=date_type,
            volume=self.query_one("#volume", Input).value.strip() or None,
        )
