# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from pathlib import Path


class VtBrowseApp:
    """Stub — full Textual App subclass lands in Task 14."""

    def __init__(self, *, archive: Path) -> None:
        self.archive = archive

    def run(self) -> int:
        raise NotImplementedError("vtbrowse UI lands in Task 14")
