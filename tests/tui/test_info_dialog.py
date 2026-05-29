# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved


def test_volume_info_dialog(snap_compare, tmp_archive):
    from vtextract.tui.app import VtBrowseApp

    async def before(pilot):
        await pilot.pause()
        await pilot.press("ctrl+i")
        await pilot.pause()
    assert snap_compare(VtBrowseApp(archive=tmp_archive), run_before=before)


def test_page_info_dialog(snap_compare, tmp_archive):
    from vtextract.tui.app import VtBrowseApp

    async def before(pilot):
        await pilot.pause()
        await pilot.press("enter")  # drill into first volume → pages
        await pilot.pause()
        await pilot.press("ctrl+i")
        await pilot.pause()
    assert snap_compare(VtBrowseApp(archive=tmp_archive), run_before=before)


def test_item_info_dialog(snap_compare, tmp_archive):
    from vtextract.tui.app import VtBrowseApp

    async def before(pilot):
        await pilot.pause()
        await pilot.press("ctrl+f")
        await pilot.pause()
        for ch in "houston":
            await pilot.press(ch)
        await pilot.pause()
        await pilot.press("enter")  # submit search → results
        await pilot.pause()
        await pilot.press("ctrl+i")
        await pilot.pause()
    assert snap_compare(VtBrowseApp(archive=tmp_archive), run_before=before)
