# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""⌃E Extract dialog — a single-clause ``vtextract search`` form.

Submit dismisses with the argv that ``vtextract.search_spec.build_search_argv``
produced (a list starting with ``"search"``); cancel/Esc dismisses with
``None``. The app drives ``ExtractClient.search_stream`` then
``IndexClient.build_stream`` on the result so newly extracted records become
searchable immediately."""

from __future__ import annotations

from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, RadioButton, RadioSet, Static

from vtextract.search_spec import (
    OPERANDS_FOR_SINGLE_CLAUSE,
    build_search_argv,
)

_FIELDS: tuple[tuple[str, str], ...] = (
    ("keyword",       "keyword (all fields)"),
    ("title",         "title"),
    ("transcription", "transcription"),
    ("creator",       "creator"),
    ("ref",           "reference"),
    ("person",        "person"),
    ("place",         "place"),
)


class ExtractDialog(ModalScreen[list[str] | None]):
    BINDINGS = [Binding("escape", "dismiss(None)", "cancel")]

    def compose(self):
        with Vertical(id="extract-dialog"):
            yield Label("Extract from Virtual Treasury (Ctrl+E)")
            yield Input(placeholder="Keywords", id="keywords")
            yield Label("Match")
            with RadioSet(id="operand"):
                for i, name in enumerate(OPERANDS_FOR_SINGLE_CLAUSE):
                    yield RadioButton(name, value=(i == 0), id=f"op-{name}")
            yield Label("Field")
            with RadioSet(id="field"):
                for i, (key, label) in enumerate(_FIELDS):
                    yield RadioButton(label, value=(i == 0), id=f"fl-{key}")
            with Horizontal():
                yield Input(placeholder="From (YYYY-MM-DD)", id="from")
                yield Input(placeholder="To",                 id="to")
            yield Static("", id="preview")
            with Horizontal():
                yield Button("Extract", id="submit", variant="primary")
                yield Button("Cancel",  id="cancel")

    def on_mount(self) -> None:
        self._update_preview()

    def on_input_changed(self, _: Input.Changed) -> None:
        self._update_preview()

    def on_radio_set_changed(self, _: RadioSet.Changed) -> None:
        self._update_preview()

    def _update_preview(self) -> None:
        try:
            argv = self._argv()
        except ValueError:
            argv = []
        self.query_one("#preview", Static).update(
            "Will run: vtextract " + " ".join(argv) if argv else " "
        )

    def _argv(self) -> list[str]:
        keywords = self.query_one("#keywords", Input).value.strip()
        if not keywords:
            raise ValueError("empty")
        operand = next(
            name for name in OPERANDS_FOR_SINGLE_CLAUSE
            if self.query_one(f"#op-{name}", RadioButton).value
        )
        field = next(
            key for key, _label in _FIELDS
            if self.query_one(f"#fl-{key}", RadioButton).value
        )
        return build_search_argv(
            field=field,
            operand=operand,
            keywords=keywords,
            start=self.query_one("#from", Input).value.strip() or None,
            end=self.query_one("#to", Input).value.strip() or None,
        )

    def on_button_pressed(self, ev: Button.Pressed) -> None:
        if ev.button.id == "cancel":
            self.dismiss(None)
            return
        try:
            self.dismiss(self._argv())
        except ValueError:
            self.query_one("#preview", Static).update(
                "Enter at least one keyword."
            )
