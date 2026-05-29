# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""Landing widget shown after the user declines to build a missing index."""

from __future__ import annotations

from pathlib import Path

from textual.binding import Binding
from textual.widgets import Static


class NoIndexScreen(Static):
    BINDINGS = [Binding("ctrl+b", "build_index", "build")]

    def __init__(self, *, index_path: Path) -> None:
        super().__init__(
            f"No index found at {index_path}\n\n"
            "Press Ctrl+B to build the index for the current archive.\n\n"
            "Or relaunch with --config <path> to point at a different\n"
            "vt.toml whose top-level `archive` key points elsewhere."
        )

    def action_build_index(self) -> None:
        self.app.action_build_index()  # type: ignore[attr-defined]
