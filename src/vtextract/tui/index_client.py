# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""The single subprocess choke point for `vtindex`.

Nothing else in vtextract/tui/ may invoke vtindex — every consumer goes
through `IndexClient`. The contract is the vtindex CLI's JSON output,
not its Python API."""

from __future__ import annotations

import asyncio
import json
import subprocess
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vtextract.tui.progress_events import ProgressEvent, parse_event


class IndexError(RuntimeError):
    """vtindex exited with a non-handled status (typically 2 = misconfig)."""


@dataclass
class IndexClient:
    archive: Path
    binary: str = "vtindex"

    # ---------- one-shot JSON queries ----------

    def volumes(self) -> list[dict]:
        return self._json(["volumes"])

    def search(self, *, query: str | None = None,
               fields: tuple[str, ...] | None = None,
               date_from: str | None = None, date_to: str | None = None,
               date_type: str = "content", volume: str | None = None,
               limit: int = 50, offset: int = 0) -> list[dict]:
        argv = ["search"]
        if query:
            argv.append(query)
        if fields:
            argv += ["--in", ",".join(fields)]
        if date_from:
            argv += ["--from", date_from]
        if date_to:
            argv += ["--to", date_to]
        argv += ["--date-type", date_type]
        if volume:
            argv += ["--volume", volume]
        argv += ["--limit", str(limit), "--offset", str(offset)]
        return self._json(argv, empty_on_exit_1=True) or []

    def page(self, root_id: str, page_key: str) -> dict | None:
        return self._json(["page", f"{root_id}/{page_key}"],
                          empty_on_exit_1=True)

    def pages(self, root_id: str) -> list[dict]:
        return self._json(["pages", root_id], empty_on_exit_1=True) or []

    def item(self, isadg_id: int) -> dict | None:
        return self._json(["item", str(isadg_id)], empty_on_exit_1=True)

    def stats(self) -> dict:
        return self._json(["stats"])

    # ---------- internal: one-shot subprocess + JSON parse ----------

    def _json(self, sub_argv: list[str], *,
              empty_on_exit_1: bool = False) -> Any:
        argv = [self.binary, *sub_argv,
                "--archive", str(self.archive), "--json"]
        result = subprocess.run(
            argv, capture_output=True, text=True, check=False,
        )
        if result.returncode == 0:
            stdout = result.stdout.strip()
            if not stdout:
                return None
            return json.loads(stdout)
        if result.returncode == 1 and empty_on_exit_1:
            return None
        raise IndexError(result.stderr.strip() or f"vtindex exit {result.returncode}")

    # ---------- streaming build ----------

    async def build_stream(
        self, *, rebuild: bool = False,
    ) -> AsyncIterator[ProgressEvent]:
        argv = [self.binary, "build", "--archive", str(self.archive),
                "--json-progress"]
        if rebuild:
            argv.append("--rebuild")
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert proc.stdout is not None
        try:
            async for line in proc.stdout:
                text = line.decode().strip()
                if not text:
                    continue
                yield parse_event(text)
        finally:
            rc = await proc.wait()
            if rc not in (0, 1):
                stderr = (await proc.stderr.read()).decode() if proc.stderr else ""
                yield parse_event(json.dumps({
                    "event": "error", "message": stderr or f"exit {rc}",
                    "exit_code": rc,
                }))
