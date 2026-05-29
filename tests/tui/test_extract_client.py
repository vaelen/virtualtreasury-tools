# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import asyncio
import json

import pytest

from vtextract.tui.extract_client import ExtractClient


def _fake_proc(stdout_lines: list[str]):
    class P:
        returncode = 0
        class _S:
            def __init__(self, lines): self._lines = list(lines)
            def __aiter__(self): return self
            async def __anext__(self):
                if not self._lines: raise StopAsyncIteration
                return (self._lines.pop(0) + "\n").encode()
        stdout = _S(stdout_lines)
        stderr = None
        async def wait(self): return self.returncode
    return P()


@pytest.mark.asyncio
async def test_search_stream_yields_events(monkeypatch, tmp_path):
    events = [json.dumps({"event": "start", "tool": "vtextract fetch", "argv": []}),
              json.dumps({"event": "done", "elapsed_seconds": 0.5, "counters": {}})]

    async def fake_exec(*argv, **kw): return _fake_proc(events)
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    client = ExtractClient(archive=tmp_path)
    received = [type(e).__name__ async for e in client.search_stream(
        argv=["search", "--all", "memorial"])]
    assert received == ["StartEvent", "DoneEvent"]
