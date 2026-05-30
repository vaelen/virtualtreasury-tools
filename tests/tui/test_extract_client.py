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


@pytest.mark.asyncio
async def test_get_images_stream_passes_page_allowlist(monkeypatch, tmp_path):
    captured = {}

    async def fake_exec(*argv, **kw):
        captured["argv"] = list(argv)
        return _fake_proc([])

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    client = ExtractClient(archive=tmp_path)
    _ = [e async for e in client.get_images_stream(
        [474234], page_keys=["b.jpg", "a.jpg"])]

    argv = captured["argv"]
    assert argv[:3] == ["vtextract", "get", "474234"]
    assert "--images" in argv and "--refresh" in argv
    i = argv.index("--only-image-pages")
    # page keys are passed sorted and comma-joined as a single token
    assert argv[i + 1] == "a.jpg,b.jpg"


@pytest.mark.asyncio
async def test_get_images_stream_without_page_keys_omits_allowlist(monkeypatch, tmp_path):
    captured = {}

    async def fake_exec(*argv, **kw):
        captured["argv"] = list(argv)
        return _fake_proc([])

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    client = ExtractClient(archive=tmp_path)
    _ = [e async for e in client.get_images_stream([474234])]

    assert "--only-image-pages" not in captured["argv"]
