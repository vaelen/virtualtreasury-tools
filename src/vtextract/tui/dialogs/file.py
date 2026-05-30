# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""One ``FileDialog`` parametrized by mode: save / open / export.

See ``docs/superpowers/specs/2026-05-29-vtbrowse-tui-design.md`` §Save/Open/
Export.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button, Checkbox, DirectoryTree, Input, Label, RadioButton, RadioSet,
    Static,
)

Mode = Literal["save", "open", "export"]


@dataclass
class FileResult:
    path: Path
    fmt: str = "folder"           # 'folder' | 'zip' | 'targz' (export only)
    include_images: bool = False  # export only


class FileDialog(ModalScreen[FileResult | None]):
    BINDINGS = [Binding("escape", "dismiss(None)", "cancel")]

    def __init__(self, *, mode: Mode, start_dir: Path,
                 default_name: str | None = None) -> None:
        super().__init__()
        self.mode = mode
        self.start_dir = start_dir
        self.default_name = default_name or self._suggested_name()

    def _suggested_name(self) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"bundle_{ts}" + (".json" if self.mode == "save" else "")

    def compose(self):
        with Vertical(id="file-dialog"):
            yield Label({"save": "Save bundle", "open": "Open bundle",
                         "export": "Export bundle"}[self.mode])
            yield DirectoryTree(str(self.start_dir), id="tree")
            yield Static("", id="hover-summary")  # filled on Open hover
            yield Input(value=self.default_name, placeholder="Name", id="name")
            if self.mode == "export":
                with RadioSet(id="fmt"):
                    yield RadioButton("Folder", value=True, id="fmt-folder")
                    yield RadioButton(".zip", id="fmt-zip")
                    yield RadioButton(".tar.gz", id="fmt-targz")
                yield Checkbox(
                    "Include images (vtextract get --refresh --images)",
                    id="include-images",
                )
            with Horizontal():
                yield Button({"save": "Save", "open": "Open",
                              "export": "Export"}[self.mode],
                             id="submit", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_directory_tree_file_selected(
            self, ev: DirectoryTree.FileSelected) -> None:
        if self.mode == "open":
            # Open mode keeps the full name (extension and all) so the value
            # resolves to a real file, and peeks a JSON header into the summary.
            self.query_one("#name", Input).value = ev.path.name
            if ev.path.suffix == ".json":
                try:
                    data = json.loads(ev.path.read_text())
                    items = len(data.get("selected_items", []))
                    pages = len({(p["root_id"], p["page_key"])
                                 for d in data.get("selected_items", [])
                                 for p in d.get("matched_pages", [])})
                    self.query_one("#hover-summary", Static).update(
                        f"{items} items, {pages} pages"
                    )
                except Exception:
                    self.query_one("#hover-summary", Static).update(
                        "(unreadable)")
        else:
            # Save / Export use a base name; the suffix is added on submit.
            self.query_one("#name", Input).value = ev.path.stem

    def on_button_pressed(self, ev: Button.Pressed) -> None:
        if ev.button.id == "cancel":
            self.dismiss(None)
            return
        name = self.query_one("#name", Input).value.strip()
        if not name:
            return
        # An absolute or ~-relative name wins outright; a bare name resolves
        # against the directory currently shown in the tree.
        typed = Path(name).expanduser()
        path = typed if typed.is_absolute() else self._current_dir() / typed
        if self.mode == "save" and not str(path).endswith(".json"):
            path = path.with_suffix(".json")
        fmt = "folder"
        include_images = False
        if self.mode == "export":
            fmt = ("folder" if self.query_one("#fmt-folder", RadioButton).value
                   else "zip" if self.query_one("#fmt-zip", RadioButton).value
                   else "targz")
            include_images = self.query_one("#include-images", Checkbox).value
        self.dismiss(FileResult(path=path, fmt=fmt,
                                include_images=include_images))

    def _current_dir(self) -> Path:
        tree = self.query_one("#tree", DirectoryTree)
        node = tree.cursor_node
        if node is None or not node.data:
            return self.start_dir
        candidate = Path(node.data.path)
        return candidate if candidate.is_dir() else candidate.parent
