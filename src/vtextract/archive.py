from __future__ import annotations

import json
from pathlib import Path


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
