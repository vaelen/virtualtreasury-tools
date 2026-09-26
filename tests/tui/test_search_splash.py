# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

"""The search-in-progress loading splash: a slow search shows a centered modal
(same design as the startup splash) instead of appearing hung."""

from __future__ import annotations

import asyncio

from vtextract.tui.app import VtBrowseApp
from vtextract.tui.dialogs.splash import SplashScreen


async def _submit_search(pilot) -> None:
    await pilot.press("f")  # open the search dialog
    await pilot.pause()
    for ch in "houston":
        await pilot.press(ch)
    await pilot.press("enter")  # submit -> _on_search_submitted
    await pilot.pause()


def test_splash_shows_during_search_and_clears_after(tmp_archive):
    gate = asyncio.Event()

    async def gated_search(**_kwargs):
        await gate.wait()
        return []

    async def runner():
        app = VtBrowseApp(archive=tmp_archive)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.index.search = gated_search
            await _submit_search(pilot)
            assert isinstance(app.screen, SplashScreen), (
                f"expected the search splash, got {type(app.screen).__name__}")
            gate.set()  # let the search complete
            await pilot.pause()
            await pilot.pause()
            assert not isinstance(app.screen, SplashScreen)

    asyncio.run(runner())


def test_search_splash_visible(snap_compare, tmp_archive):
    """Snapshot: the 'Searching the archive…' splash renders centered over the
    main screen. The search is gated open so the modal stays up for the shot."""
    gate = asyncio.Event()

    async def gated_search(**_kwargs):
        await gate.wait()
        return []

    async def before(pilot):
        await pilot.pause()
        pilot.app.index.search = gated_search
        await _submit_search(pilot)

    assert snap_compare(VtBrowseApp(archive=tmp_archive), run_before=before)
