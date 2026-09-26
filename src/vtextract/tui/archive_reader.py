# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

"""Direct on-disk reads against the archive layout. No HTTP, no SQL.

The archive layout is part of the public design spec, so reading it
directly here does not violate the architectural boundary — only the
SQLite index is off-limits."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ArchiveReader:
    archive: Path

    def _page_dir(self, root_id: str) -> Path:
        return self.archive / "pages" / root_id

    def read_transcription(self, root_id: str, page_key: str) -> str | None:
        f = self._page_dir(root_id) / f"{page_key}.txt"
        return f.read_text() if f.exists() else None

    def names_path(self, root_id: str, page_key: str) -> Path:
        return self._page_dir(root_id) / f"{page_key}.names.json"

    def notes_path(self, root_id: str, page_key: str) -> Path:
        return self._page_dir(root_id) / f"{page_key}.notes.md"

    def read_notes(self, root_id: str, page_key: str) -> str:
        f = self.notes_path(root_id, page_key)
        return f.read_text() if f.exists() else ""

    def write_notes(self, root_id: str, page_key: str, text: str) -> None:
        """Write the page's notes.md; whitespace-only text removes it instead."""
        f = self.notes_path(root_id, page_key)
        if text.strip():
            f.write_text(text)
        else:
            f.unlink(missing_ok=True)

    def read_names(self, root_id: str, page_key: str) -> list[list[str]]:
        """The page's names-sidecar persons, each a ``[canonical, *surface_forms]``
        list (schema 2). Empty list when no sidecar exists (names never run)."""
        f = self.names_path(root_id, page_key)
        if not f.exists():
            return []
        people = json.loads(f.read_text()).get("people") or []
        return [list(p) for p in people if p]

    def read_page_meta(self, root_id: str, page_key: str) -> dict | None:
        f = self._page_dir(root_id) / f"{page_key}.json"
        return json.loads(f.read_text()) if f.exists() else None

    def read_volume_meta(self, root_id: str) -> dict | None:
        f = self._page_dir(root_id) / "volume.json"
        return json.loads(f.read_text()) if f.exists() else None

    def image_path(self, root_id: str, page_key: str) -> Path:
        return self._page_dir(root_id) / page_key

    def image_exists(self, root_id: str, page_key: str) -> bool:
        return self.image_path(root_id, page_key).exists()
