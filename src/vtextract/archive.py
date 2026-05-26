# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

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

    def is_resource_complete(self, isadg_id: int) -> bool:
        entry = self._state["resources"].get(str(isadg_id))
        return bool(entry) and entry.get("status") == "complete"

    def mark_resource_complete(self, isadg_id: int, *, pages: list, search_id: str) -> None:
        entry = self._state["resources"].setdefault(str(isadg_id), {"searches": []})
        entry["status"] = "complete"
        entry["pages"] = pages
        if search_id and search_id not in entry["searches"]:
            entry["searches"].append(search_id)

    def mark_resource_failed(self, isadg_id: int, *, reason: str) -> None:
        entry = self._state["resources"].setdefault(str(isadg_id), {"searches": []})
        entry["status"] = "failed"
        entry["reason"] = reason

    def has_page(self, root_id: str, page_key: str) -> bool:
        return f"{root_id}/{page_key}" in self._state["pages"]

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

    def store_page(
        self,
        *,
        root_id: str,
        page_key: str,
        image_bytes: bytes,
        text: str | None,
        annotations: dict | None,
    ) -> None:
        page_dir = self._page_dir(root_id)
        (page_dir / page_key).write_bytes(image_bytes)
        if text is not None:
            (page_dir / f"{page_key}.txt").write_text(text)
        if annotations is not None:
            (page_dir / f"{page_key}.json").write_text(json.dumps(annotations, indent=2))
        self._state["pages"][f"{root_id}/{page_key}"] = {
            "sha256": hashlib.sha256(image_bytes).hexdigest(),
            "bytes": len(image_bytes),
        }

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
            "searchHit": record.search_hit,
            "detail": record.detail,
        }
        (item_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))
        if manifest is not None:
            (item_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
