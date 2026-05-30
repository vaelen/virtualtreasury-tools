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

    async def search_stream(
        self, *, argv: list[str],
        cancel_event: asyncio.Event | None = None,
    ) -> AsyncIterator[ProgressEvent]:
        # argv comes from vtextract.search_spec.build_search_argv(...)
        # and starts with ["search", ...]; we tack on --json-progress and
        # --out <archive>.
        full = [self.binary, *argv, "--out", str(self.archive),
                "--json-progress"]
        inner = self._stream(full, cancel_event=cancel_event)
        try:
            async for event in inner:
                yield event
        finally:
            # Forward GeneratorExit / cancellation to the inner generator so
            # its finally block (which SIGTERMs the subprocess) runs.
            await inner.aclose()

    async def get_images_stream(
        self, isadg_ids: list[int],
        page_keys: list[str] | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> AsyncIterator[ProgressEvent]:
        # page_keys restricts the download to just the bundle's selected pages
        # (a resource's manifest can cover an entire volume, so without this the
        # backfill would pull every page image).
        full = [self.binary, "get", *map(str, isadg_ids),
                "--refresh", "--images"]
        if page_keys:
            full += ["--only-image-pages", ",".join(sorted(set(page_keys)))]
        full += ["--out", str(self.archive), "--json-progress"]
        inner = self._stream(full, cancel_event=cancel_event)
        try:
            async for event in inner:
                yield event
        finally:
            await inner.aclose()

    async def _stream(
        self, full_argv: list[str], *,
        cancel_event: asyncio.Event | None = None,
    ) -> AsyncIterator[ProgressEvent]:
        proc = await asyncio.create_subprocess_exec(
            *full_argv, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert proc.stdout is not None
        try:
            async for line in proc.stdout:
                text = line.decode().strip()
                if text:
                    yield parse_event(text)
                if cancel_event is not None and cancel_event.is_set():
                    break
        finally:
            # GeneratorExit lands here when the consumer aclose()s us
            # (e.g. ProgressModal cancel). SIGTERM the child, then SIGKILL
            # after a 2-second grace period.
            if proc.returncode is None:
                try:
                    proc.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
                    await proc.wait()
            else:
                await proc.wait()
