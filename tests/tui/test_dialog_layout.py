# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""Modal dialogs render as smaller, centred boxes over the main screen (not
full-screen), and both date inputs fit on screen side by side."""

from __future__ import annotations

import pytest
from textual.widgets import Input

from vtextract.tui.app import VtBrowseApp


async def _open(pilot, *keys):
    await pilot.pause()
    for k in keys:
        await pilot.press(k)
    await pilot.pause()


@pytest.mark.asyncio
@pytest.mark.parametrize("open_key, box_id", [
    ("ctrl+f", "#search-dialog"),
    ("ctrl+e", "#extract-dialog"),
])
async def test_date_inputs_both_on_screen(tmp_archive, open_key, box_id):
    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, open_key)
        screen = app.screen
        for which in ("#from", "#to"):
            inp = screen.query_one(which, Input)
            r = inp.region
            assert inp.display and r.width > 0, f"{which} not visible"
            assert r.right <= app.size.width, (
                f"{which} extends off-screen: right={r.right} "
                f"width={app.size.width}"
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("open_key, box_id", [
    ("ctrl+f", "#search-dialog"),
    ("ctrl+e", "#extract-dialog"),
])
async def test_dialog_is_a_centred_box_not_fullscreen(tmp_archive, open_key, box_id):
    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, open_key)
        box = app.screen.query_one(box_id)
        r = box.region
        assert r.width < app.size.width, (
            f"dialog spans full width ({r.width} of {app.size.width})"
        )
        assert r.height < app.size.height, (
            f"dialog spans full height ({r.height} of {app.size.height})"
        )
        assert r.x > 0, "dialog not horizontally centred (flush to left edge)"
