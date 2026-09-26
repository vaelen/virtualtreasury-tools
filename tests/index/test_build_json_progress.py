# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

import json
import shutil
import subprocess
from pathlib import Path

import pytest


FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "archive"


@pytest.fixture
def tmp_archive(tmp_path) -> Path:
    """Copy the fixture archive into ``tmp_path`` without building the index."""
    archive = tmp_path / "archive"
    shutil.copytree(FIXTURE, archive)
    return archive


def test_build_json_progress_emits_start_and_done(tmp_archive):
    result = subprocess.run(
        ["uv", "run", "vtindex", "build", "--archive", str(tmp_archive),
         "--json-progress"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    events = [json.loads(line) for line in result.stdout.splitlines() if line]
    kinds = [e["event"] for e in events]
    assert kinds[0] == "start"
    assert kinds[-1] == "done"
    assert events[0]["tool"] == "vtindex build"
    done = events[-1]
    assert "elapsed_seconds" in done
    assert {"added", "updated", "removed", "unchanged", "skipped"} <= set(done["counters"])
