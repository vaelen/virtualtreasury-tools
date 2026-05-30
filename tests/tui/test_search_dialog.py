# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import pytest


def test_search_dialog_opens_on_f(snap_compare, tmp_archive):
    from vtextract.tui.app import VtBrowseApp

    async def before(pilot):
        await pilot.pause()
        await pilot.press("f")
        await pilot.pause()
    assert snap_compare(VtBrowseApp(archive=tmp_archive), run_before=before)


@pytest.mark.asyncio
async def test_search_dialog_has_no_date_type_selector(tmp_archive):
    # The created-date option is gone: vtbrowse always searches the content
    # date, falling back to the estimated date.
    from vtextract.tui.app import VtBrowseApp
    from vtextract.tui.dialogs.search import SearchDialog

    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("f")
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, SearchDialog)
        assert not dialog.query("#date-type")
        assert dialog._collect().date_type == "content"
