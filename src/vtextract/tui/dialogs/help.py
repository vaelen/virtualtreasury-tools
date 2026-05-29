# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Static

_BINDINGS = (
    ("↑ ↓",      "any list",                  "move row cursor"),
    ("← →",      "transcription view",        "previous / next page"),
    ("← →",      "Bundle pane",               "collapse / expand volume"),
    ("⏎",        "volume row",                "open page list"),
    ("⏎",        "page row",                  "open transcription"),
    ("⏎",        "search result row",         "open first matched page"),
    ("space",    "page row, transcription",   "toggle page user state"),
    ("space",    "search result row",         "toggle item in selection"),
    ("space",    "Bundle row",                "remove page or volume's pages"),
    ("esc",      "any",                       "back one level"),
    ("tab",      "any",                       "swap focus between panes"),
    ("⌃F",       "any",                       "Search dialog"),
    ("⌃O",       "any",                       "Open bundle"),
    ("⌃S",       "any",                       "Save bundle"),
    ("⌃⇧S",      "any",                       "Export bundle"),
    ("⌃E",       "any",                       "Extract from Virtual Treasury"),
    ("⌃B",       "any",                       "Build / rebuild the vtindex index"),
    ("⌃I",       "any",                       "Info dialog"),
    ("⌃V",       "any",                       "jump to Volumes"),
    ("⌃R",       "any",                       "jump to last results"),
    ("⌃X",       "any",                       "Exit (confirm if unsaved)"),
    ("F1 / ?",   "any",                       "this dialog"),
)


class HelpDialog(ModalScreen[None]):
    BINDINGS = [Binding("escape", "dismiss(None)", "close")]

    def compose(self):
        with Vertical(id="help-dialog"):
            yield Static("Keyboard shortcuts")
            table = DataTable()
            table.add_columns("Key", "Context", "Action")
            for key, ctx, action in _BINDINGS:
                table.add_row(key, ctx, action)
            yield table
            yield Button("Close", id="close")

    def on_button_pressed(self, _: Button.Pressed) -> None:
        self.dismiss(None)
