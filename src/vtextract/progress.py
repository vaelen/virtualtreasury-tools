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


class Reporter:
    """Live progress + status output for the fetch loop.

    The only module that knows about ``rich``. It renders two bars — overall
    progress across resources and per-page progress within the current
    resource — and prints the fetching/done/skipping/failed status lines above
    them. When ``enabled`` is false (the default off a TTY) the live bars are
    disabled and only the plain status lines are emitted, so piped output stays
    clean. Used as a context manager around the loop::

        with reporter:
            ...
        reporter.finish(completed, failed)

    ``console`` and ``enabled`` are injectable for testing.
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
        self._item: int | None = None

    def __enter__(self) -> "Reporter":
        self.progress.__enter__()
        return self

    def __exit__(self, *exc) -> None:
        self.progress.__exit__(*exc)

    def _say(self, message: str) -> None:
        # Literal output: don't let ids or exception reprs be read as markup.
        self.console.print(message, markup=False, highlight=False)

    def set_total(self, n: int, noun: str = "matches") -> None:
        """Announce the count and size the overall bar."""
        self._say(f"Found {n} {noun}.")
        if self._overall is None:
            self._overall = self.progress.add_task("overall", total=n)
        else:
            self.progress.update(self._overall, total=n)

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
        self._advance_overall()

    def skip(self, label) -> None:
        self._say(f"skipping {label}, already archived")
        self._advance_overall()

    def fail(self, label, exc: BaseException) -> None:
        self._say(f"FAILED {label}: {exc!r}")
        self._advance_overall()

    def finish(self, completed: int, failed: int) -> None:
        self._say(f"finished: {completed} archived, {failed} failed")

    def _advance_overall(self) -> None:
        if self._overall is not None:
            self.progress.advance(self._overall)
