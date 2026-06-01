# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""Cancellation contracts for the progress streams.

ExtractClient._stream still drives a subprocess, so it must terminate() the
child on cancel (verified here with a fake process). IndexClient.build_stream is
now in-process: cancellation is cooperative — setting cancel_event stops the
build loop and the stream ends without a synthetic error event.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from vtextract.tui.extract_client import ExtractClient
from vtextract.tui.index_client import IndexClient
from vtextract.tui.progress_events import ErrorEvent

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "archive"


class _FakeProc:
    """Mimic asyncio.subprocess.Process for the streaming path.

    ``stdout`` yields lines forever (one start event, then blocks on the
    cancel_event); ``terminate`` flips ``returncode`` to simulate the
    child dying.
    """

    def __init__(self, *, hang_forever_event: asyncio.Event):
        self.returncode = None
        self._terminated = False
        self._killed = False
        self._hang = hang_forever_event
        self.terminate_called = 0
        self.kill_called = 0
        self.stdout = self._Stream(hang_forever_event)
        self.stderr = self._EmptyStream()

    class _Stream:
        def __init__(self, hang_event):
            self._yielded_first = False
            self._hang = hang_event

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self._yielded_first:
                self._yielded_first = True
                # Yield one start event so the consumer enters its loop body.
                import json
                return (json.dumps({
                    "event": "start", "tool": "vtindex build", "argv": [],
                }) + "\n").encode()
            # Block until terminate() flips _hang — simulates a real
            # subprocess that hasn't EOFed yet.
            await self._hang.wait()
            raise StopAsyncIteration

    class _EmptyStream:
        async def read(self):
            return b""

    def terminate(self):
        self.terminate_called += 1
        self._terminated = True
        self.returncode = -15
        self._hang.set()

    def kill(self):
        self.kill_called += 1
        self._killed = True
        self.returncode = -9
        self._hang.set()

    async def wait(self):
        await self._hang.wait()
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


@pytest.mark.asyncio
async def test_extract_stream_terminates_subprocess_on_cancel(
    monkeypatch, tmp_path,
):
    hang = asyncio.Event()
    fake = _FakeProc(hang_forever_event=hang)

    async def fake_exec(*argv, **kw):
        return fake

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    cancel_event = asyncio.Event()
    client = ExtractClient(archive=tmp_path)
    stream = client.search_stream(
        argv=["search", "--all", "x"], cancel_event=cancel_event,
    )

    received = []
    async for ev in stream:
        received.append(ev)
        cancel_event.set()
        await stream.aclose()
        break

    assert received
    assert fake.terminate_called == 1, \
        "_stream's finally must terminate() the subprocess on close"


@pytest.mark.asyncio
async def test_index_build_stream_cancel_is_cooperative_and_clean(tmp_path):
    archive = tmp_path / "archive"
    shutil.copytree(_FIXTURE, archive)

    cancel_event = asyncio.Event()
    client = IndexClient(archive=archive)
    try:
        stream = client.build_stream(cancel_event=cancel_event)
        received = []
        async for ev in stream:
            received.append(ev)
            # Cancel as soon as the first event arrives, then stop consuming.
            cancel_event.set()
            await stream.aclose()
            break
        assert received, "stream should have yielded at least one event"
        # Cancellation must not surface as an error event.
        assert not any(isinstance(e, ErrorEvent) for e in received)
    finally:
        client.close()
