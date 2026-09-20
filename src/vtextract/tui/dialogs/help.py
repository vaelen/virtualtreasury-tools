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
    ("⏎",        "transcription view",        "swap text ⇄ page image"),
    ("n",        "transcription view",        "open / close page notes editor"),
    ("esc",      "notes editor",              "close and save notes"),
    ("p",        "transcription view",        "open / close extracted people table"),
    ("esc / p",  "people table",              "close people table"),
    ("space",    "page row, transcription",   "toggle page user state"),
    ("space",    "search result row",         "toggle item in selection"),
    ("a",        "page list, search results", "select or deselect all"),
    ("d",        "search results",            "cycle sort order"),
    ("space",    "Bundle row",                "remove page or volume's pages"),
    ("esc",      "any",                       "back one level"),
    ("tab",      "any",                       "swap focus between panes"),
    ("f",        "any",                       "Find dialog"),
    ("o",        "any",                       "Open bundle"),
    ("s",        "any",                       "Save bundle"),
    ("x",        "any",                       "Export bundle"),
    ("e",        "any",                       "Extract from Virtual Treasury"),
    ("b",        "any",                       "Build / rebuild the vtindex index"),
    ("i",        "any",                       "Info dialog"),
    ("v",        "any",                       "jump to Volumes"),
    ("r",        "any",                       "jump to last results"),
    ("q",        "any",                       "Quit (confirm if unsaved)"),
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
