# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""The single subprocess choke point for `vtextract`.

The TUI uses this for: Step 1 of the Extract dialog (vtextract search)
and image backfill at Export time (vtextract get --refresh --images)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from vtextract.tui.progress_events import ProgressEvent, parse_event


@dataclass
class ExtractClient:
    archive: Path
    binary: str = "vtextract"

    async def search_stream(self, *, argv: list[str]) -> AsyncIterator[ProgressEvent]:
        # argv comes from vtextract.search_spec.build_search_argv(...)
        # and starts with ["search", ...]; we tack on --json-progress and
        # --out <archive>.
        full = [self.binary, *argv, "--out", str(self.archive),
                "--json-progress"]
        async for event in self._stream(full):
            yield event

    async def get_images_stream(self, isadg_ids: list[int]) -> AsyncIterator[ProgressEvent]:
        full = [self.binary, "get", *map(str, isadg_ids),
                "--refresh", "--images",
                "--out", str(self.archive), "--json-progress"]
        async for event in self._stream(full):
            yield event

    async def _stream(self, full_argv: list[str]) -> AsyncIterator[ProgressEvent]:
        proc = await asyncio.create_subprocess_exec(
            *full_argv, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert proc.stdout is not None
        async for line in proc.stdout:
            text = line.decode().strip()
            if text:
                yield parse_event(text)
        await proc.wait()
