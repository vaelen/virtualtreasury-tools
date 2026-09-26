# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT


def test_exit_dialog_when_dirty(snap_compare, tmp_archive):
    """When the bundle has unsaved changes, q shows the exit-confirm dialog."""
    from vtextract.tui.app import VtBrowseApp
    from vtextract.tui.bundle import PageRef

    class _DirtyApp(VtBrowseApp):
        async def on_mount(self) -> None:
            # Populate bundle with stub data so page/item counts are non-zero
            # and mark dirty so q triggers the confirm dialog.
            self.bundle.selected_items[1] = [
                PageRef("stub-root", "stub-page-1"),
                PageRef("stub-root", "stub-page-2"),
            ]
            self._bundle_dirty = True
            await super().on_mount()

    async def before(pilot):
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()
    assert snap_compare(_DirtyApp(archive=tmp_archive), run_before=before)


def test_q_confirms_when_clean(tmp_archive):
    """Even with a clean bundle, q asks before quitting — but without the
    save-and-quit option or the unsaved-changes warning, which only apply
    when there is something to save."""
    import asyncio
    from textual.widgets import Button
    from vtextract.tui.app import VtBrowseApp
    from vtextract.tui.dialogs.exit import ExitDialog

    app = VtBrowseApp(archive=tmp_archive)

    async def runner():
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._bundle_dirty is False
            await pilot.press("q")
            await pilot.pause()
            assert isinstance(app.screen, ExitDialog)
            ids = {b.id for b in app.screen.query(Button)}
            assert ids == {"exit", "cancel"}
            # Escape cancels; the app is still running.
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, ExitDialog)

    asyncio.run(runner())


def test_clean_quit_confirm_exits(tmp_archive):
    """Choosing Quit in the clean-bundle confirm actually exits the app."""
    import asyncio
    from vtextract.tui.app import VtBrowseApp
    from vtextract.tui.dialogs.exit import ExitDialog

    app = VtBrowseApp(archive=tmp_archive)

    async def runner():
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("q")
            await pilot.pause()
            assert isinstance(app.screen, ExitDialog)
            await pilot.click("#exit")
            await pilot.pause()
        # Reaching here means run_test finished: the app exited.

    asyncio.run(runner())
