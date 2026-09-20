# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved


def test_help_dialog_via_question(snap_compare, tmp_archive):
    """Pressing ``?`` opens the Help dialog."""
    from vtextract.tui.app import VtBrowseApp

    async def before(pilot):
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
    assert snap_compare(VtBrowseApp(archive=tmp_archive), run_before=before)


def test_help_dialog_via_f1(tmp_archive):
    """Pressing F1 also opens the Help dialog (same screen type)."""
    import asyncio
    from vtextract.tui.app import VtBrowseApp
    from vtextract.tui.dialogs.help import HelpDialog

    app = VtBrowseApp(archive=tmp_archive)

    async def runner():
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f1")
            await pilot.pause()
            assert isinstance(app.screen, HelpDialog)

    asyncio.run(runner())


def test_help_lists_select_all_binding():
    """The Help dialog documents the 'a' select/deselect-all shortcut."""
    from vtextract.tui.dialogs.help import _BINDINGS

    keys = {key for key, _ctx, _action in _BINDINGS}
    assert "a" in keys
    row = next(r for r in _BINDINGS if r[0] == "a" and "page list" in r[1])
    assert "select" in row[2].lower()
