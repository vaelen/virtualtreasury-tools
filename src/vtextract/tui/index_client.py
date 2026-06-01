# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""In-process gateway to the archive index for the vtbrowse TUI.

This is the ONLY place in vtextract/tui/ that holds an ``IndexService``. It runs
the (synchronous) service on a dedicated single-thread executor so the Textual
event loop stays responsive and the SQLite connection stays confined to one
thread. Builds run on a worker thread with a queue-backed progress reporter and
cooperative cancellation. Read methods return the service's typed DTOs.

Per the architectural boundary (tests/test_no_direct_db.py) tui/ never imports
vtextract.index.{db,query,builder}; it goes through vtextract.index.service.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from vtextract.index.models import SearchQuery
from vtextract.index.service import IndexService, IndexUnavailable
from vtextract.tui.progress_events import (
    DoneEvent,
    ErrorEvent,
    LogEvent,
    ProgressEvent,
    ProgressUpdate,
    StartEvent,
)


class IndexError(RuntimeError):
    """The index is unavailable (missing or incompatible). Mirrors the old
    subprocess exit-2 condition so callers (App._detect_index_state) are
    unchanged."""


class _QueueBuildReporter:
    """A ``builder.build()``-compatible reporter that turns build progress into
    ``ProgressEvent``s, handed to a thread-safe ``emit`` callback (the build runs
    on a worker thread, so ``emit`` marshals back onto the event loop)."""

    def __init__(self, emit) -> None:
        self._emit = emit
        self._total = 0
        self._current = 0
        self._started = time.monotonic()

    def start(self, total: int) -> None:
        self._total = total
        self._current = 0
        self._emit(LogEvent(message=f"Indexing {total} files."))
        self._emit(ProgressUpdate(phase="indexing", current=0, total=total))

    def advance(self, n: int = 1) -> None:
        self._current += n
        self._emit(ProgressUpdate(phase="indexing", current=self._current,
                                  total=self._total))

    def finish(self, *, added: int, updated: int, removed: int,
               unchanged: int, skipped: int) -> None:
        self._emit(DoneEvent(
            elapsed_seconds=round(time.monotonic() - self._started, 2),
            counters={"added": added, "updated": updated, "removed": removed,
                      "unchanged": unchanged, "skipped": skipped},
        ))


class IndexClient:
    """In-process gateway holding an ``IndexService`` on a single executor thread."""

    def __init__(self, archive: Path) -> None:
        self.archive = Path(archive)
        self._service: IndexService | None = None
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vtindex-read")

    # ---------- read dispatch (single dedicated thread) ----------

    def _run(self, fn):
        try:
            if self._service is None:
                self._service = IndexService(self.archive)
            return fn(self._service)
        except IndexUnavailable as exc:
            raise IndexError(str(exc)) from exc

    async def _call(self, fn):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._pool, self._run, fn)

    async def volumes(self):
        return await self._call(lambda s: s.volumes())

    async def search(self, *, query: str | None = None,
                     fields: tuple[str, ...] | None = None,
                     date_from: str | None = None, date_to: str | None = None,
                     date_type: str = "content", volume: str | None = None,
                     limit: int = 50, offset: int = 0):
        q = SearchQuery(
            text=query or None,
            fields=fields or ("title", "description", "transcription"),
            date_from=date_from, date_to=date_to, date_type=date_type,
            volume=volume, limit=limit, offset=offset,
        )
        return await self._call(lambda s: s.search(q))

    async def page(self, root_id: str, page_key: str):
        return await self._call(lambda s: s.page(root_id, page_key))

    async def pages(self, root_id: str):
        return await self._call(lambda s: s.pages(root_id))

    async def item(self, isadg_id: int):
        return await self._call(lambda s: s.item(isadg_id))

    async def stats(self):
        return await self._call(lambda s: s.stats())

    # ---------- lifecycle ----------

    def _reset_service(self) -> None:
        """Runs on the read thread: drop the service so the next read reopens it."""
        if self._service is not None:
            self._service.close()
            self._service = None

    def close(self) -> None:
        self._pool.shutdown(wait=False)

    # ---------- in-process build ----------

    async def build_stream(
        self, *, rebuild: bool = False,
        cancel_event: asyncio.Event | None = None,
    ) -> AsyncIterator[ProgressEvent]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        cancel = threading.Event()
        sentinel = object()

        def emit(ev: ProgressEvent) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, ev)

        reporter = _QueueBuildReporter(emit)

        def run_build() -> None:
            emit(StartEvent(tool="vtindex build", argv=[]))
            try:
                IndexService.build(self.archive, rebuild=rebuild,
                                   reporter=reporter, cancel=cancel)
            except Exception as exc:  # noqa: BLE001 — surface as a stream event
                emit(ErrorEvent(message=str(exc), exit_code=1))
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, sentinel)

        fut = loop.run_in_executor(None, run_build)
        try:
            while True:
                ev = await queue.get()
                if ev is sentinel:
                    break
                yield ev
                if cancel_event is not None and cancel_event.is_set():
                    cancel.set()
        finally:
            cancel.set()
            await fut
            await loop.run_in_executor(self._pool, self._reset_service)
