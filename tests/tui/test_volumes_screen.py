# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved


def test_volumes_screen_lists_indexed_volumes(snap_compare, tmp_archive):
    from vtextract.tui.app import VtBrowseApp

    async def before(pilot):
        await pilot.pause()
    assert snap_compare(VtBrowseApp(archive=tmp_archive), run_before=before)
