# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""Shared fixtures for vtbrowse TUI tests."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "archive"


@pytest.fixture
def tmp_archive(tmp_path) -> Path:
    """Copy the fixture archive into ``tmp_path`` and build its index.

    Returns the archive path. Mirrors ``tests/index/conftest.py``'s
    ``built_archive`` but yields only the path (the TUI tests don't need the
    extra known-id metadata).
    """
    archive = tmp_path / "archive"
    shutil.copytree(FIXTURE, archive)
    result = subprocess.run(
        ["uv", "run", "vtindex", "build", "--archive", str(archive)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    return archive
