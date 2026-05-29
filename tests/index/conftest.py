# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""Shared fixtures for vtindex CLI tests."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "archive"


@pytest.fixture
def built_archive(tmp_path) -> dict:
    """Copy the fixture archive into ``tmp_path`` and build its index.

    Returns a dict with at least ``path``, ``root_id`` (a known volume root id),
    and ``isadg_id`` (a known item id). The fixture is the same one used by
    ``test_cli.py``; ``volA`` and item ``100`` are stable picks.
    """
    archive = tmp_path / "archive"
    shutil.copytree(FIXTURE, archive)
    # Build via the installed entry point so subprocess-based tests work.
    result = subprocess.run(
        ["uv", "run", "vtindex", "build", "--archive", str(archive)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    return {"path": archive, "root_id": "volA", "isadg_id": 100}
