# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""Verifies the SIGTERM-on-cancel contract for IndexClient.build_stream
and ExtractClient._stream — when the caller sets ``cancel_event``, the
streaming generator's ``finally`` block must terminate() the underlying
subprocess (not wait for natural EOF).
"""

from __future__ import annotations

import asyncio
import json

import pytest

from vtextract.tui.extract_client import ExtractClient
from vtextract.tui.index_client import IndexClient


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
async def test_index_build_stream_terminates_subprocess_on_cancel(
    monkeypatch, tmp_path,
):
    hang = asyncio.Event()
    fake = _FakeProc(hang_forever_event=hang)

    async def fake_exec(*argv, **kw):
        return fake

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    cancel_event = asyncio.Event()
    client = IndexClient(archive=tmp_path)
    stream = client.build_stream(cancel_event=cancel_event)

    # Pull one event, then signal cancel and close the generator.
    received = []
    async for ev in stream:
        received.append(ev)
        cancel_event.set()
        # Closing the stream triggers its finally block.
        await stream.aclose()
        break

    assert received, "stream should have yielded at least one event"
    assert fake.terminate_called == 1, \
        "build_stream's finally must terminate() the subprocess on close"


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
async def test_build_stream_kills_after_terminate_timeout(
    monkeypatch, tmp_path,
):
    """If terminate() doesn't make the subprocess exit within 2s, kill()."""

    class _StubbornProc(_FakeProc):
        def terminate(self):
            # Tally the call but do NOT flip _hang or returncode — simulate
            # a process that ignores SIGTERM.
            self.terminate_called += 1
            self._terminated = True
            # leave returncode = None and _hang unset

        async def wait(self):
            # Only return once kill() is called.
            await self._hang.wait()
            return self.returncode

    hang = asyncio.Event()
    fake = _StubbornProc(hang_forever_event=hang)

    async def fake_exec(*argv, **kw):
        return fake

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    # Patch wait_for to short-circuit (skip the real 2-second sleep).
    real_wait_for = asyncio.wait_for

    async def fast_wait_for(coro, timeout):
        # Close the coro to avoid "never awaited" warnings, then raise.
        coro.close()
        raise asyncio.TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", fast_wait_for)

    cancel_event = asyncio.Event()
    client = IndexClient(archive=tmp_path)
    stream = client.build_stream(cancel_event=cancel_event)

    received = []
    async for ev in stream:
        received.append(ev)
        cancel_event.set()
        await stream.aclose()
        break

    # restore for any teardown
    monkeypatch.setattr(asyncio, "wait_for", real_wait_for)

    assert fake.terminate_called == 1
    assert fake.kill_called == 1, \
        "kill() must run when terminate() doesn't exit within 2s"
