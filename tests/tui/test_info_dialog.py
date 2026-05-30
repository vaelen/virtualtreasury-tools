# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import pytest


@pytest.mark.asyncio
async def test_item_info_body_shows_all_three_dates():
    # The item info panel surfaces content, created and estimated dates (with
    # the estimate's source), so the user can see which date drove a match.
    from vtextract.tui.bundle import Bundle
    from vtextract.tui.dialogs.info import ItemInfoDialog

    class _FakeIndex:
        async def item(self, isadg_id):
            return {
                "isadg_id": isadg_id, "title": "T", "reference_code": "R",
                "repository": "Repo",
                "content_begin": None, "content_end": None,
                "created_begin": "1737-01-18", "created_end": "1737-01-18",
                "estimated_begin": "1776-01-01", "estimated_end": "1793-12-31",
                "estimated_source": "volume",
                "pages": [],
            }

    dialog = ItemInfoDialog(index=_FakeIndex(), bundle=Bundle(), isadg_id=521)
    body = await dialog._body()
    assert "Content date" in body
    assert "Created date" in body
    assert "Estimated" in body
    assert "1737-01-18" in body
    assert "1776-01-01" in body and "1793-12-31" in body
    assert "volume" in body  # the estimate's source is shown


def test_volume_info_dialog(snap_compare, tmp_archive):
    from vtextract.tui.app import VtBrowseApp

    async def before(pilot):
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()
    assert snap_compare(VtBrowseApp(archive=tmp_archive), run_before=before)


def test_page_info_dialog(snap_compare, tmp_archive):
    from vtextract.tui.app import VtBrowseApp

    async def before(pilot):
        await pilot.pause()
        await pilot.press("enter")  # drill into first volume → pages
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()
    assert snap_compare(VtBrowseApp(archive=tmp_archive), run_before=before)


def test_item_info_dialog(snap_compare, tmp_archive):
    from vtextract.tui.app import VtBrowseApp

    async def before(pilot):
        await pilot.pause()
        await pilot.press("f")
        await pilot.pause()
        for ch in "houston":
            await pilot.press(ch)
        await pilot.pause()
        await pilot.press("enter")  # submit search → results
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()
    assert snap_compare(VtBrowseApp(archive=tmp_archive), run_before=before)
