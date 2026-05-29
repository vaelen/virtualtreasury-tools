# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import json
import subprocess
from unittest import mock

import pytest

from vtextract.tui.index_client import IndexClient, IndexError


@pytest.fixture
def archive(tmp_path):
    return tmp_path / "archive"


def _cp(stdout: str, returncode: int = 0, stderr: str = ""):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr,
    )


def test_volumes_invokes_vtindex_with_archive_and_json(archive):
    payload = [{"root_id": "0007", "label": "L", "reference_code": "R",
                "item_count": 9, "title": "T"}]
    with mock.patch("subprocess.run", return_value=_cp(json.dumps(payload))) as run:
        out = IndexClient(archive).volumes()
    assert out == payload
    argv = run.call_args.args[0]
    assert argv[0] == "vtindex" and "volumes" in argv
    assert "--archive" in argv and str(archive) in argv
    assert "--json" in argv


def test_search_builds_expected_argv(archive):
    with mock.patch("subprocess.run", return_value=_cp("[]")) as run:
        IndexClient(archive).search(
            query="pirate Dublin", fields=("title", "transcription"),
            date_from="1640", date_to="1660", date_type="content",
            volume="0007", limit=25, offset=0,
        )
    argv = run.call_args.args[0]
    assert argv[:2] == ["vtindex", "search"]
    for fragment in ("pirate Dublin", "--in", "title,transcription",
                     "--from", "1640", "--to", "1660",
                     "--date-type", "content",
                     "--volume", "0007", "--limit", "25",
                     "--archive", str(archive), "--json"):
        assert fragment in argv


def test_stats_returns_dict(archive):
    payload = {"items": 100, "volumes": 5, "pages": 800,
               "schema_version": "5", "stale": False}
    with mock.patch("subprocess.run", return_value=_cp(json.dumps(payload))):
        assert IndexClient(archive).stats() == payload


def test_index_error_when_vtindex_returns_2(archive):
    with mock.patch("subprocess.run",
                    return_value=_cp("", returncode=2, stderr="missing index")):
        with pytest.raises(IndexError, match="missing index"):
            IndexClient(archive).volumes()


def test_search_returns_empty_list_on_exit_1(archive):
    with mock.patch("subprocess.run", return_value=_cp("[]", returncode=1)):
        assert IndexClient(archive).search(query="zzz") == []
