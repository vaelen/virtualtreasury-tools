# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""Snapshot tests for Task 23: startup index prompt, no-index landing screen,
and in-session stale chip."""

from __future__ import annotations

from pathlib import Path


# Deterministic path used in snapshots — overrides the tmp_path the
# ``tmp_archive`` fixture produces so the prompt + no-index landing render
# the same text on every run.
_FAKE_ARCHIVE = Path("/tmp/archive")
_FAKE_INDEX = _FAKE_ARCHIVE / "index" / "vtindex.sqlite3"


def test_index_prompt_dialog_missing(snap_compare, tmp_archive):
    """Force the startup state to ``missing``; the IndexPromptDialog appears."""
    from vtextract.tui.app import VtBrowseApp

    class _PromptApp(VtBrowseApp):
        async def _detect_index_state(self):
            return "missing"

        def _index_path(self):
            return _FAKE_INDEX

        def action_build_index(self) -> None:  # no-op for snapshot stability
            pass

        def _start_stale_poll(self) -> None:  # avoid timer-driven snapshots
            pass

    app = _PromptApp(archive=tmp_archive)
    # Spoof the visible archive path so the snapshot is deterministic.
    app.archive = _FAKE_ARCHIVE

    async def before(pilot):
        await pilot.pause()
    assert snap_compare(app, run_before=before)


def test_no_index_screen(snap_compare, tmp_archive):
    """Decline the missing-index prompt → the NoIndexScreen lands in the pane."""
    from vtextract.tui.app import VtBrowseApp

    class _PromptApp(VtBrowseApp):
        async def _detect_index_state(self):
            return "missing"

        def _index_path(self):
            return _FAKE_INDEX

        def action_build_index(self) -> None:
            pass

        def _start_stale_poll(self) -> None:
            pass

    app = _PromptApp(archive=tmp_archive)
    app.archive = _FAKE_ARCHIVE

    async def before(pilot):
        await pilot.pause()
        # Click "No" on the IndexPromptDialog: focus is on Yes by default,
        # so Tab moves to No, Enter activates it.
        await pilot.press("tab")
        await pilot.press("enter")
        await pilot.pause()
    assert snap_compare(app, run_before=before)


def test_stale_chip_visible(snap_compare, tmp_archive):
    """A forced stale flag makes the header chip render on the home screen."""
    from vtextract.tui.app import VtBrowseApp

    class _PromptApp(VtBrowseApp):
        async def _detect_index_state(self):
            # OK so the prompt doesn't appear; we force the chip on after
            # mount via the run_before hook.
            return "ok"

        def action_build_index(self) -> None:
            pass

        def _start_stale_poll(self) -> None:
            pass

    async def before(pilot):
        await pilot.pause()
        app = pilot.app
        app._stale_chip_visible = True
        app._refresh_header_chip()
        await pilot.pause()
    assert snap_compare(_PromptApp(archive=tmp_archive), run_before=before)
