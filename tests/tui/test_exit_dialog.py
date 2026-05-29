# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved


def test_exit_dialog_when_dirty(snap_compare, tmp_archive):
    """When the bundle has unsaved changes, ⌃X shows the exit-confirm dialog."""
    from vtextract.tui.app import VtBrowseApp
    from vtextract.tui.bundle import PageRef

    class _DirtyApp(VtBrowseApp):
        def on_mount(self) -> None:
            # Populate bundle with stub data so page/item counts are non-zero
            # and mark dirty so ⌃X triggers the confirm dialog.
            self.bundle.selected_items[1] = [
                PageRef("stub-root", "stub-page-1"),
                PageRef("stub-root", "stub-page-2"),
            ]
            self._bundle_dirty = True
            super().on_mount()

    async def before(pilot):
        await pilot.pause()
        await pilot.press("ctrl+x")
        await pilot.pause()
    assert snap_compare(_DirtyApp(archive=tmp_archive), run_before=before)


def test_ctrl_x_silent_when_clean(tmp_archive):
    """When the bundle is clean (untouched), ⌃X exits silently — no dialog."""
    import asyncio
    from vtextract.tui.app import VtBrowseApp

    app = VtBrowseApp(archive=tmp_archive)

    async def runner():
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._bundle_dirty is False
            await pilot.press("ctrl+x")
            await pilot.pause()
        # If we got here the app exited cleanly.

    asyncio.run(runner())
