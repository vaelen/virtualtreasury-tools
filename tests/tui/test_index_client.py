# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import json

import pytest

from vtextract.tui.index_client import IndexClient, IndexError


@pytest.fixture
def archive(tmp_path):
    return tmp_path / "archive"


def _fake_proc(stdout: str, returncode: int = 0, stderr: str = ""):
    """Fake the object returned by asyncio.create_subprocess_exec."""
    class P:
        def __init__(self):
            self.returncode = returncode
        async def communicate(self):
            return stdout.encode(), stderr.encode()
    return P()


def _patch_exec(monkeypatch, *, stdout: str, returncode: int = 0,
                stderr: str = "", capture: list | None = None):
    async def fake_exec(*argv, **kw):
        if capture is not None:
            capture.append(list(argv))
        return _fake_proc(stdout, returncode=returncode, stderr=stderr)
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)


@pytest.mark.asyncio
async def test_volumes_invokes_vtindex_with_archive_and_json(monkeypatch, archive):
    payload = [{"root_id": "0007", "label": "L", "reference_code": "R",
                "item_count": 9, "title": "T"}]
    captured: list[list] = []
    _patch_exec(monkeypatch, stdout=json.dumps(payload), capture=captured)
    out = await IndexClient(archive).volumes()
    assert out == payload
    argv = captured[0]
    assert argv[0] == "vtindex" and "volumes" in argv
    assert "--archive" in argv and str(archive) in argv
    assert "--json" in argv


@pytest.mark.asyncio
async def test_search_builds_expected_argv(monkeypatch, archive):
    captured: list[list] = []
    _patch_exec(monkeypatch, stdout="[]", capture=captured)
    await IndexClient(archive).search(
        query="pirate Dublin", fields=("title", "transcription"),
        date_from="1640", date_to="1660", date_type="content",
        volume="0007", limit=25, offset=0,
    )
    argv = captured[0]
    assert argv[:2] == ["vtindex", "search"]
    for fragment in ("pirate Dublin", "--in", "title,transcription",
                     "--from", "1640", "--to", "1660",
                     "--date-type", "content",
                     "--volume", "0007", "--limit", "25",
                     "--archive", str(archive), "--json"):
        assert fragment in argv


@pytest.mark.asyncio
async def test_stats_returns_dict(monkeypatch, archive):
    payload = {"items": 100, "volumes": 5, "pages": 800,
               "schema_version": "5", "stale": False}
    _patch_exec(monkeypatch, stdout=json.dumps(payload))
    assert await IndexClient(archive).stats() == payload


@pytest.mark.asyncio
async def test_index_error_when_vtindex_returns_2(monkeypatch, archive):
    _patch_exec(monkeypatch, stdout="", returncode=2, stderr="missing index")
    with pytest.raises(IndexError, match="missing index"):
        await IndexClient(archive).volumes()


@pytest.mark.asyncio
async def test_search_returns_empty_list_on_exit_1(monkeypatch, archive):
    _patch_exec(monkeypatch, stdout="[]", returncode=1)
    assert await IndexClient(archive).search(query="zzz") == []
