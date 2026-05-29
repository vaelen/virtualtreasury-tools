# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""Generic progress modal driven by an async iterator of ProgressEvent.

Backs ``b`` (single step) and the export-time image backfill (single step);
Task 22's Extract dialog reuses it to chain vtextract search → vtindex
build."""

from __future__ import annotations

import asyncio
import inspect
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

    Backs ``b`` (single step) and ``e`` (two steps wired in Task 22).

    Cancellation: pressing Escape (or the Cancel button) sets
    ``self._cancel_event``. The stream factory may accept a
    ``cancel_event=`` keyword; when set, the underlying subprocess in
    ``IndexClient.build_stream`` / ``ExtractClient._stream`` SIGTERMs the
    child (then SIGKILLs after a 2s grace period) instead of waiting for
    natural EOF. Stream factories without that keyword still get the
    "stop reading" behaviour from the local break below.
    """

    BINDINGS = [Binding("escape", "request_cancel", "cancel")]

    def __init__(
        self,
        *,
        title: str,
        stream_factory: Callable[..., AsyncIterator[ProgressEvent]],
    ) -> None:
        super().__init__()
        self._title = title
        self._stream_factory = stream_factory
        self._cancel_event = asyncio.Event()
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
        stream = self._open_stream()
        async for ev in stream:
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

    def _open_stream(self) -> AsyncIterator[ProgressEvent]:
        """Call the stream factory, passing ``cancel_event`` when supported.

        Factories built from ``IndexClient`` / ``ExtractClient`` accept a
        ``cancel_event`` keyword; lambdas in tests typically don't. We
        introspect to stay backwards-compatible with both.
        """
        try:
            sig = inspect.signature(self._stream_factory)
        except (TypeError, ValueError):
            return self._stream_factory()
        if "cancel_event" in sig.parameters or any(
            p.kind == inspect.Parameter.VAR_KEYWORD
            for p in sig.parameters.values()
        ):
            return self._stream_factory(cancel_event=self._cancel_event)
        return self._stream_factory()

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
        self._cancel_event.set()

    def on_button_pressed(self, _: Button.Pressed) -> None:
        if self._done_ok is None:
            self.action_request_cancel()
        else:
            self.dismiss(self._done_ok)
