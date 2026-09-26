# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

"""The export-with-images flow must show a responsive backfill ProgressModal.

Regression: with 'include images' checked and missing images on disk, the
modal's on_mount awaited the whole vtextract stream to completion, blocking
the screen's message pump. The modal couldn't be cancelled and (depending on
paint timing) looked frozen for the entire — slow — download."""

from __future__ import annotations

import asyncio

import pytest

from vtextract.tui.app import VtBrowseApp
from vtextract.tui.bundle import PageRef
from vtextract.tui.dialogs.build import ProgressModal
from vtextract.tui.dialogs.file import FileDialog, FileResult
from vtextract.tui.extract_client import ExtractClient
from vtextract.tui.progress_events import DoneEvent, StartEvent


async def _open_export_with_images(app, pilot, tmp_path):
    app.bundle.toggle_item(100, [PageRef("volA", "volA_p1.jpg")])
    result = FileResult(path=tmp_path / "out", fmt="folder",
                        include_images=True)
    app.push_screen(FileDialog(mode="export", start_dir=tmp_path),
                    app._on_export_chosen)
    await pilot.pause()
    app.screen.dismiss(result)


@pytest.mark.asyncio
async def test_export_with_images_shows_progress_modal(tmp_archive, tmp_path,
                                                       monkeypatch):
    async def stub(self, ids, page_keys=None, cancel_event=None):
        yield StartEvent(tool="vtextract fetch", argv=[])
        yield DoneEvent(elapsed_seconds=0.1, counters={"completed": 1})

    monkeypatch.setattr(ExtractClient, "get_images_stream", stub)

    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test() as pilot:
        await _open_export_with_images(app, pilot, tmp_path)
        await pilot.pause()
        assert isinstance(app.screen, ProgressModal), (
            f"expected ProgressModal, got {type(app.screen).__name__}"
        )
        await app.workers.wait_for_complete()


@pytest.mark.asyncio
async def test_backfill_passes_only_selected_missing_page_keys(
        tmp_archive, tmp_path, monkeypatch):
    """Regression: the backfill must restrict the download to the bundle's
    selected pages, not the whole resource/volume. The page-key allowlist is
    what carries that restriction across the subprocess boundary."""
    captured = {}

    async def stub(self, ids, page_keys=None, cancel_event=None):
        captured["ids"] = list(ids)
        captured["page_keys"] = page_keys
        yield StartEvent(tool="vtextract fetch", argv=[])
        yield DoneEvent(elapsed_seconds=0.1, counters={"completed": 1})

    monkeypatch.setattr(ExtractClient, "get_images_stream", stub)

    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test() as pilot:
        # Two pages selected under item 100; neither has an image on disk.
        app.bundle.toggle_item(100, [PageRef("volA", "volA_p1.jpg"),
                                     PageRef("volA", "volA_p2.jpg")])
        result = FileResult(path=tmp_path / "out", fmt="folder",
                            include_images=True)
        app.push_screen(FileDialog(mode="export", start_dir=tmp_path),
                        app._on_export_chosen)
        await pilot.pause()
        app.screen.dismiss(result)
        await pilot.pause()
        await app.workers.wait_for_complete()

    assert captured["ids"] == [100]
    assert sorted(captured["page_keys"]) == ["volA_p1.jpg", "volA_p2.jpg"]


@pytest.mark.asyncio
async def test_modal_stays_responsive_while_stream_runs(tmp_archive, tmp_path,
                                                        monkeypatch):
    """While the backfill stream is still producing, the modal must paint and
    process input (Escape→cancel). If on_mount blocks the pump, the screen is
    frozen until the subprocess ends — the user's 'locked up' symptom."""
    started = asyncio.Event()
    release = asyncio.Event()

    async def stub(self, ids, page_keys=None, cancel_event=None):
        yield StartEvent(tool="vtextract fetch", argv=[])
        started.set()
        await release.wait()  # stream still in progress until released
        yield DoneEvent(elapsed_seconds=0.1, counters={"completed": 1})

    monkeypatch.setattr(ExtractClient, "get_images_stream", stub)

    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test() as pilot:
        await _open_export_with_images(app, pilot, tmp_path)
        # Wait for the stream to start without requiring the app to go idle.
        await asyncio.wait_for(started.wait(), timeout=5)
        await asyncio.sleep(0.05)

        modal = app.screen
        assert isinstance(modal, ProgressModal)
        # The modal must actually be laid out (painted), not zero-size.
        title = modal.query_one("#title")
        assert title.region.width > 0 and title.region.height > 0, (
            f"modal title not painted: region={title.region!r}"
        )

        # And it must process input while the stream is mid-flight: a real
        # key press routes through the screen's message pump. If on_mount
        # blocked the pump, this Escape would be ignored (and pilot.press
        # itself would hang waiting for idle).
        await pilot.press("escape")
        assert modal._cancel_requested, (
            "Escape/Cancel ignored while stream running — pump is blocked"
        )

        release.set()
