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
    """Neutralize the startup splash for every full-app TUI test.

    Production defers the slow startup work to after the splash paints
    (``SPLASH_DEFER_STARTUP``), so when ``run_test`` yields, the splash is still
    up and startup is mid-flight — which would collide with tests that drive the
    app immediately. Run startup inline instead so the screen stack is settled
    (splash dismissed, volumes loaded) before the test interacts, and zero the
    minimum-display time. The end state is identical to production; only the
    timing differs. The deferred path keeps its own coverage in
    test_splash_shown_on_real_startup_path, and the render in
    test_splash_visible_on_startup."""
    monkeypatch.setattr(VtBrowseApp, "SPLASH_MIN_SECONDS", 0.0)
    monkeypatch.setattr(VtBrowseApp, "SPLASH_DEFER_STARTUP", False)
