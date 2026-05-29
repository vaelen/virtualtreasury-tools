# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""The single subprocess choke point for `vtindex`.

Nothing else in vtextract/tui/ may invoke vtindex — every consumer goes
through `IndexClient`. The contract is the vtindex CLI's JSON output,
not its Python API."""

from __future__ import annotations

import asyncio
import json
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

    async def volumes(self) -> list[dict]:
        return await self._json(["volumes"])

    async def search(self, *, query: str | None = None,
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
        return await self._json(argv, empty_on_exit_1=True) or []

    async def page(self, root_id: str, page_key: str) -> dict | None:
        return await self._json(["page", f"{root_id}/{page_key}"],
                                empty_on_exit_1=True)

    async def pages(self, root_id: str) -> list[dict]:
        return await self._json(["pages", root_id], empty_on_exit_1=True) or []

    async def item(self, isadg_id: int) -> dict | None:
        return await self._json(["item", str(isadg_id)], empty_on_exit_1=True)

    async def stats(self) -> dict:
        return await self._json(["stats"])

    # ---------- internal: one-shot subprocess + JSON parse ----------

    async def _json(self, sub_argv: list[str], *,
                    empty_on_exit_1: bool = False) -> Any:
        argv = [self.binary, *sub_argv,
                "--archive", str(self.archive), "--json"]
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        rc = proc.returncode
        if rc == 0:
            text = stdout.decode().strip()
            if not text:
                return None
            return json.loads(text)
        if rc == 1 and empty_on_exit_1:
            return None
        raise IndexError(stderr.decode().strip() or f"vtindex exit {rc}")

    # ---------- streaming build ----------

    async def build_stream(
        self, *, rebuild: bool = False,
        cancel_event: asyncio.Event | None = None,
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
            rc = proc.returncode
            # Only emit the synthetic error event on natural-EOF failures —
            # cancellation (the consumer aclose'd us) and SIGTERM/SIGKILL
            # exit codes should NOT yield, because yielding during
            # GeneratorExit is a RuntimeError.
            cancelled = bool(cancel_event and cancel_event.is_set())
            terminated = rc is not None and rc < 0  # negative = killed by signal
            if rc not in (0, 1) and not cancelled and not terminated:
                stderr = (await proc.stderr.read()).decode() if proc.stderr else ""
                yield parse_event(json.dumps({
                    "event": "error", "message": stderr or f"exit {rc}",
                    "exit_code": rc,
                }))
