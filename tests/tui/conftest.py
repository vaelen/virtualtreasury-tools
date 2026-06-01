# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""Shared fixtures for vtbrowse TUI tests."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from vtextract.tui.app import VtBrowseApp


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


@pytest.fixture(autouse=True)
def _instant_splash(monkeypatch):
    """Every full-app TUI test mounts the startup splash (a modal pushed first
    in on_mount). With the production 0.5s minimum it would still be on top
    when a test interacts or screenshots. Force a zero minimum so the splash is
    pushed and dismissed within on_mount, leaving the main screen active and
    existing baselines unchanged. The dedicated splash render test overrides
    on_mount to keep the splash up regardless."""
    monkeypatch.setattr(VtBrowseApp, "SPLASH_MIN_SECONDS", 0.0)
