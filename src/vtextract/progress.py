# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

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

    def advance(self) -> None:
        if self._overall is not None:
            self.progress.advance(self._overall)


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

    def finish(
        self, *, added: int, updated: int, removed: int, unchanged: int, skipped: int
    ) -> None:
        self._say(
            f"indexed: {added} added, {updated} updated, {removed} removed, "
            f"{unchanged} unchanged, {skipped} skipped"
        )
