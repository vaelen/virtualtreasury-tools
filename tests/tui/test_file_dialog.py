# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from pathlib import Path


def _make_app_subclass(tmp_archive, mode: str):
    """Return a VtBrowseApp subclass whose Save/Open/Export bindings target
    a deterministic ``start_dir`` (the fixture archive) and a fixed
    ``default_name``, so snapshots don't drift on Path.home() / wall clock.
    """
    from vtextract.tui.app import VtBrowseApp
    from vtextract.tui.dialogs.file import FileDialog

    class _DeterministicApp(VtBrowseApp):
        def action_save_bundle(self):
            self.push_screen(FileDialog(
                mode="save", start_dir=tmp_archive,
                default_name="bundle_fixed.json",
            ))

        def action_open_bundle(self):
            self.push_screen(FileDialog(
                mode="open", start_dir=tmp_archive,
                default_name="bundle_fixed",
            ))

        def action_export_bundle(self):
            self.push_screen(FileDialog(
                mode="export", start_dir=tmp_archive,
                default_name="bundle_fixed",
            ))

    return _DeterministicApp


def test_save_dialog_opens_on_ctrl_s(snap_compare, tmp_archive):
    cls = _make_app_subclass(tmp_archive, "save")

    async def before(pilot):
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
    assert snap_compare(cls(archive=tmp_archive), run_before=before)


def test_open_dialog_opens_on_ctrl_o(snap_compare, tmp_archive):
    cls = _make_app_subclass(tmp_archive, "open")

    async def before(pilot):
        await pilot.pause()
        await pilot.press("ctrl+o")
        await pilot.pause()
    assert snap_compare(cls(archive=tmp_archive), run_before=before)


def test_export_dialog_opens_on_ctrl_w(snap_compare, tmp_archive):
    cls = _make_app_subclass(tmp_archive, "export")

    async def before(pilot):
        await pilot.pause()
        await pilot.press("ctrl+w")
        await pilot.pause()
    assert snap_compare(cls(archive=tmp_archive), run_before=before)
