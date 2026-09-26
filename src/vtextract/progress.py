# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import sys
import time
from typing import IO, Any

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)


class ProgressReporter:
    """Shared progress plumbing: a single 'overall' bar plus plain status lines.

    The only place that knows about ``rich``. When ``enabled`` is false (the
    default off a TTY) the live bar is disabled and only the plain status lines
    are emitted, so piped output stays clean. ``console`` and ``enabled`` are
    injectable for testing. Used as a context manager around a loop.
    """

    def __init__(self, *, console: Console | None = None, enabled: bool | None = None) -> None:
        self.console = console or Console(stderr=True)
        self.enabled = self.console.is_terminal if enabled is None else enabled
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=self.console,
            disable=not self.enabled,
        )
        self._overall: int | None = None

    def __enter__(self):
        self.progress.__enter__()
        return self

    def __exit__(self, *exc) -> None:
        self.progress.__exit__(*exc)

    def _say(self, message: str) -> None:
        # Literal output: don't let ids or exception reprs be read as markup.
        self.console.print(message, markup=False, highlight=False)

    def _begin_overall(self, n: int, description: str = "overall") -> None:
        if self._overall is None:
            self._overall = self.progress.add_task(description, total=n)
        else:
            self.progress.update(self._overall, total=n)

    def advance(self, n: int = 1) -> None:
        if self._overall is not None:
            self.progress.advance(self._overall, n)


class Reporter(ProgressReporter):
    """Live progress + status output for the fetch loop.

    Renders two bars — overall progress across resources and per-page progress
    within the current resource — and prints fetching/done/skipping/failed
    status lines above them.
    """

    def __init__(self, *, console: Console | None = None, enabled: bool | None = None) -> None:
        super().__init__(console=console, enabled=enabled)
        self._item: int | None = None

    def set_total(self, n: int, noun: str = "matches") -> None:
        """Announce the count and size the overall bar."""
        self._say(f"Found {n} {noun}.")
        self._begin_overall(n)

    def start_item(self, label) -> None:
        self._say(f"fetching {label}...")
        if self._item is None:
            self._item = self.progress.add_task(str(label), total=None)
        else:
            self.progress.reset(self._item, total=None, description=str(label))

    def item_pages(self, n: int) -> None:
        if self._item is not None:
            self.progress.update(self._item, total=n, completed=0)

    def page_done(self) -> None:
        if self._item is not None:
            self.progress.advance(self._item)

    def item_done(self, label) -> None:
        self._say(f"done {label}")
        self.advance()

    def skip(self, label) -> None:
        self._say(f"skipping {label}, already archived")
        self.advance()

    def fail(self, label, exc: BaseException) -> None:
        self._say(f"FAILED {label}: {exc!r}")
        self.advance()

    def finish(self, completed: int, failed: int) -> None:
        self._say(f"finished: {completed} archived, {failed} failed")

    def verify_summary(self, counts: dict[str, int], flagged: list[str]) -> None:
        """Summarise a refresh run's image-verification outcomes."""
        self._say(
            f"verified images: {counts.get('ok', 0)} ok, "
            f"{counts.get('mismatch', 0)} re-downloaded, "
            f"{counts.get('missing', 0)} downloaded (missing), "
            f"{counts.get('unverified', 0)} unverified"
        )
        for path in flagged:
            self._say(f"  flagged: {path}")


class BuildReporter(ProgressReporter):
    """Live progress + status output for the index build loop (one bar)."""

    def start(self, total: int) -> None:
        self._say(f"Indexing {total} files.")
        self._begin_overall(total, description="indexing")

    def advance_overall(self, n: int = 1) -> None:
        for _ in range(n):
            self.advance()

    def finish(
        self, *, added: int, updated: int, removed: int, unchanged: int, skipped: int
    ) -> None:
        self._say(
            f"indexed: {added} added, {updated} updated, {removed} removed, "
            f"{unchanged} unchanged, {skipped} skipped"
        )


class JsonProgressReporter:
    """Sibling of `ProgressReporter` that emits one JSON object per line on a
    writable text stream (stdout by default). Used when callers pass
    ``--json-progress`` to ``vtindex build`` / ``vtextract search`` /
    ``vtextract get`` so a parent process (the vtbrowse TUI) can drain
    structured events.

    Subclasses override ``_tool_name`` and implement domain-specific methods
    (``start``, ``finish``, etc.) by calling ``_emit({...})``. The base
    provides a context-manager protocol and an ``emit_error`` helper that is
    safe to call from outside ``with``."""

    _tool_name: str = "unknown"

    def __init__(self, *, stream: IO[str] | None = None) -> None:
        self.stream = stream or sys.stdout
        self._started_at: float | None = None

    def __enter__(self):
        self._started_at = time.monotonic()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc is not None:
            self.emit_error(str(exc), exit_code=1)

    def _emit(self, event: dict[str, Any]) -> None:
        self.stream.write(json.dumps(event) + "\n")
        self.stream.flush()

    def _elapsed(self) -> float:
        return 0.0 if self._started_at is None else time.monotonic() - self._started_at

    def emit_start(self, argv: list[str] | None = None) -> None:
        self._emit({"event": "start", "tool": self._tool_name,
                    "argv": list(argv or [])})

    def emit_progress(self, *, phase: str, current: int,
                      total: int | None = None, **counters: int) -> None:
        evt: dict[str, Any] = {"event": "progress", "phase": phase,
                               "current": current, "total": total}
        if counters:
            evt["counters"] = counters
        self._emit(evt)

    def emit_log(self, message: str, *, level: str = "info") -> None:
        self._emit({"event": "log", "level": level, "message": message})

    def emit_done(self, **counters: int) -> None:
        self._emit({"event": "done", "elapsed_seconds": round(self._elapsed(), 2),
                    "counters": counters})

    def emit_error(self, message: str, *, exit_code: int = 1) -> None:
        self._emit({"event": "error", "message": message, "exit_code": exit_code})


class JsonBuildReporter(JsonProgressReporter):
    """JSON variant of ``BuildReporter`` — same call surface so
    ``vtindex.index.builder.build()`` can swap in without code changes."""

    _tool_name = "vtindex build"

    def __init__(self, *, stream: IO[str] | None = None) -> None:
        super().__init__(stream=stream)
        self._total = 0
        self._current = 0

    def __enter__(self):
        super().__enter__()
        self.emit_start()
        return self

    def start(self, total: int) -> None:
        self._total = total
        self._current = 0
        self.emit_log(f"Indexing {total} files.")
        self.emit_progress(phase="indexing", current=0, total=total)

    def advance(self, n: int = 1) -> None:
        """Mirror of ``ProgressReporter.advance`` — called by builder.build()."""
        self.advance_overall(n)

    def advance_overall(self, n: int = 1) -> None:
        self._current += n
        self.emit_progress(phase="indexing", current=self._current,
                           total=self._total)

    def status(self, message: str) -> None:
        self.emit_log(message)

    def finish(self, *, added: int, updated: int, removed: int,
               unchanged: int, skipped: int) -> None:
        self.emit_done(added=added, updated=updated, removed=removed,
                       unchanged=unchanged, skipped=skipped)


class JsonFetchReporter(JsonProgressReporter):
    """JSON variant of ``Reporter`` (vtextract fetch). Mirrors ``Reporter``'s
    method names so the fetcher can use either by dependency injection."""

    _tool_name = "vtextract fetch"

    def __init__(self, *, stream: IO[str] | None = None) -> None:
        super().__init__(stream=stream)
        self._total: int = 0
        self._current: int = 0
        self._item_pages: int = 0
        self._item_done: int = 0

    def __enter__(self):
        super().__enter__()
        self.emit_start()
        return self

    def set_total(self, n: int, noun: str = "matches") -> None:
        self._total = n
        self._current = 0
        self.emit_log(f"Found {n} {noun}.")
        self.emit_progress(phase="fetching", current=0, total=n)

    def start_item(self, label) -> None:
        self.emit_log(f"fetching {label}...")

    def item_pages(self, n: int) -> None:
        self._item_pages = n
        self._item_done = 0
        self.emit_log(f"{n} pages")

    def page_done(self) -> None:
        # Emit one event per page so a parent TUI shows live movement during
        # the slow per-image download of a single resource. Without this the
        # progress modal would sit silent for the whole item and look frozen.
        # The overall bar holds (current/total = resources), while the page
        # counters advance within the current item.
        self._item_done += 1
        self.emit_progress(
            phase="pages", current=self._current, total=self._total,
            page=self._item_done, pages=self._item_pages,
        )

    def item_done(self, isadg_id: int) -> None:
        self.emit_log(f"done {isadg_id}")
        self._current += 1
        self.emit_progress(phase="fetching", current=self._current, total=self._total)

    def skip(self, isadg_id: int) -> None:
        self.emit_log(f"skip {isadg_id}", level="debug")
        self._current += 1
        self.emit_progress(phase="fetching", current=self._current, total=self._total)

    def fail(self, label, exc: BaseException) -> None:
        self.emit_log(f"failed {label}: {exc}", level="error")
        self._current += 1
        self.emit_progress(phase="fetching", current=self._current, total=self._total)

    def verify_summary(self, counts, flagged) -> None:
        pass

    def finish(self, completed: int, failed: int) -> None:
        self.emit_done(completed=completed, failed=failed)
