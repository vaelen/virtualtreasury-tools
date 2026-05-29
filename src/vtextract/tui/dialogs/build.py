# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""Generic progress modal driven by an async iterator of ProgressEvent.

Backs ⌃B (single step) and the export-time image backfill (single step);
Task 22's Extract dialog reuses it to chain vtextract search → vtindex
build."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Callable

from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, ProgressBar, Static

from vtextract.tui.progress_events import (
    DoneEvent,
    ErrorEvent,
    LogEvent,
    ProgressEvent,
    ProgressUpdate,
    StartEvent,
)


class ProgressModal(ModalScreen[bool]):
    """Generic progress modal driven by an async iterator of ProgressEvent.

    Backs ⌃B (single step) and ⌃E (two steps wired in Task 22)."""

    BINDINGS = [Binding("escape", "request_cancel", "cancel")]

    def __init__(
        self,
        *,
        title: str,
        stream_factory: Callable[[], AsyncIterator[ProgressEvent]],
    ) -> None:
        super().__init__()
        self._title = title
        self._stream_factory = stream_factory
        self._cancel_requested = False
        self._done_ok: bool | None = None

    def compose(self):
        with Vertical(id="progress-modal"):
            yield Label(self._title, id="title")
            yield ProgressBar(id="bar", show_eta=False)
            yield Static("", id="counters")
            yield Static("", id="logline")
            yield Button("Cancel", id="cancel")

    async def on_mount(self) -> None:
        await self._drive()

    async def _drive(self) -> None:
        async for ev in self._stream_factory():
            if self._cancel_requested:
                break
            self._render_event(ev)
            if isinstance(ev, DoneEvent):
                self._done_ok = True
            elif isinstance(ev, ErrorEvent):
                self._done_ok = False
        if self._done_ok is None and self._cancel_requested:
            self._done_ok = False
        btn = self.query_one("#cancel", Button)
        btn.label = "Close"
        btn.variant = "primary"

    def _render_event(self, ev: ProgressEvent) -> None:
        bar = self.query_one("#bar", ProgressBar)
        counters = self.query_one("#counters", Static)
        log = self.query_one("#logline", Static)
        if isinstance(ev, StartEvent):
            log.update(f"running {ev.tool} {' '.join(ev.argv)}".rstrip())
        elif isinstance(ev, ProgressUpdate):
            if ev.total:
                bar.update(total=ev.total, progress=ev.current)
            if ev.counters:
                counters.update(
                    "   ".join(f"{k}: {v}" for k, v in ev.counters.items())
                )
        elif isinstance(ev, LogEvent):
            log.update(ev.message)
        elif isinstance(ev, DoneEvent):
            log.update(f"done ({ev.elapsed_seconds:.1f}s)")
            counters.update(
                "   ".join(f"{k}: {v}" for k, v in ev.counters.items())
            )
        elif isinstance(ev, ErrorEvent):
            log.update(f"FAILED: {ev.message}")

    def action_request_cancel(self) -> None:
        self._cancel_requested = True

    def on_button_pressed(self, _: Button.Pressed) -> None:
        if self._done_ok is None:
            self.action_request_cancel()
        else:
            self.dismiss(self._done_ok)
