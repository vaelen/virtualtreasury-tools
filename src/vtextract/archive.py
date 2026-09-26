# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from vtextract.models import Record


class Archive:
    """Owns the on-disk archive: shared page store, resource records, resume state."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._state_path = self.root / "_state.json"
        if self._state_path.exists():
            self._state = json.loads(self._state_path.read_text())
        else:
            self._state = {"resources": {}, "pages": {}}

    # --- resume state ---

    def is_resource_complete(self, isadg_id: int, *, want_images: bool = False) -> bool:
        """True if the resource was archived to completion.

        With ``want_images=True``, a resource archived in metadata-only mode is
        treated as incomplete (caller needs to backfill image bytes). Legacy
        entries that predate the flag default to "images downloaded" since the
        old behaviour was always-on.
        """
        entry = self._state["resources"].get(str(isadg_id))
        if not entry or entry.get("status") != "complete":
            return False
        if want_images and not entry.get("images_downloaded", True):
            return False
        return True

    def mark_resource_complete(
        self, isadg_id: int, *, pages: list, search_id: str, images_downloaded: bool,
    ) -> None:
        entry = self._state["resources"].setdefault(str(isadg_id), {"searches": []})
        entry["status"] = "complete"
        entry["pages"] = pages
        entry["images_downloaded"] = images_downloaded
        if search_id and search_id not in entry["searches"]:
            entry["searches"].append(search_id)

    def mark_resource_failed(self, isadg_id: int, *, reason: str) -> None:
        entry = self._state["resources"].setdefault(str(isadg_id), {"searches": []})
        entry["status"] = "failed"
        entry["reason"] = reason

    def has_page_image(self, root_id: str, page_key: str) -> bool:
        entry = self._state["pages"].get(f"{root_id}/{page_key}")
        if not entry:
            return False
        path = self.root / "pages" / root_id / page_key
        if not path.exists():
            return False
        return hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]

    def has_page_transcription(self, root_id: str, page_key: str) -> bool:
        return (self.root / "pages" / root_id / f"{page_key}.txt").exists()

    def save_state(self) -> None:
        self._state_path.write_text(json.dumps(self._state, indent=2))

    # --- shared page store ---

    def _page_dir(self, root_id: str) -> Path:
        path = self.root / "pages" / root_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def page_relative_path(self, root_id: str, page_key: str) -> str:
        return f"pages/{root_id}/{page_key}"

    def page_checksum(self, root_id: str, page_key: str) -> str | None:
        entry = self._state["pages"].get(f"{root_id}/{page_key}")
        return entry["sha256"] if entry else None

    def page_size(self, root_id: str, page_key: str) -> int | None:
        """Byte size of a stored page image on disk, or None if absent."""
        path = self.root / "pages" / root_id / page_key
        return path.stat().st_size if path.exists() else None

    def store_page(
        self,
        *,
        root_id: str,
        page_key: str,
        image_bytes: bytes | None,
        text: str | None,
        annotations: dict | None,
    ) -> None:
        page_dir = self._page_dir(root_id)
        if image_bytes is not None:
            (page_dir / page_key).write_bytes(image_bytes)
            self._state["pages"][f"{root_id}/{page_key}"] = {
                "sha256": hashlib.sha256(image_bytes).hexdigest(),
                "bytes": len(image_bytes),
            }
        if text is not None:
            (page_dir / f"{page_key}.txt").write_text(text)
        if annotations is not None:
            (page_dir / f"{page_key}.json").write_text(json.dumps(annotations, indent=2))

    def write_volume_info(self, root_id: str, info: dict) -> None:
        (self._page_dir(root_id) / "volume.json").write_text(json.dumps(info, indent=2))

    # --- resource records ---

    def write_resource(self, record: Record, *, manifest: dict | None) -> None:
        item_dir = self.root / "items" / str(record.isadg_id)
        item_dir.mkdir(parents=True, exist_ok=True)
        metadata = {
            "isadgID": record.isadg_id,
            "referenceCode": record.reference_code,
            "title": record.title,
            "pages": [asdict(ref) for ref in record.pages],
            "detail": record.detail,
        }
        (item_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))
        if manifest is not None:
            (item_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
