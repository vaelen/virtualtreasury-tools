# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

"""Behavioural tests for the Save/Open/Export FileDialog and the open flow.

Covers four reported bugs:
1. dialogs should start in the current working dir, not Path.home();
2. selecting a file in Open mode populates the name input;
3. a typed name (or absolute path) resolves correctly on submit;
4. opening a bundle repopulates the live BundlePane (not a stale object).
"""

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest
from textual.app import App
from textual.widgets import Button, Input

from vtextract.tui.dialogs.file import FileDialog, FileResult


def _bundle_json(isadg_id: int = 100) -> str:
    return json.dumps({
        "version": 1,
        "created_at": "2026-05-30T00:00:00+00:00",
        "selected_items": [
            {"isadg_id": isadg_id,
             "matched_pages": [{"root_id": "volA", "page_key": "volA_p0.jpg"}]},
        ],
        "page_state": [],
    })


class _Host(App):
    """Minimal host that pushes one FileDialog and captures its result."""

    def __init__(self, dialog: FileDialog) -> None:
        super().__init__()
        self._dialog = dialog
        self.result: object = "UNSET"

    def on_mount(self) -> None:
        self.push_screen(self._dialog, lambda r: setattr(self, "result", r))


# ---------- Bug 1: dialogs start in the current folder, not home ----------

@pytest.mark.asyncio
async def test_open_action_uses_cwd_not_home(tmp_archive, monkeypatch):
    import vtextract.tui.app as appmod

    captured: list[dict] = []

    class _Spy(FileDialog):
        def __init__(self, **kw):
            captured.append(kw)
            super().__init__(**kw)

    monkeypatch.setattr(appmod, "FileDialog", _Spy)
    app = appmod.VtBrowseApp(archive=tmp_archive)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.action_open_bundle()
        await pilot.pause()
    assert captured, "FileDialog was never constructed"
    assert captured[0]["start_dir"] == Path.cwd()
    assert captured[0]["start_dir"] != Path.home()


# ---------- Bug 2: selecting a file in Open mode fills the name input ----------

@pytest.mark.asyncio
async def test_open_select_file_populates_name(tmp_path):
    f = tmp_path / "thing.json"
    f.write_text(_bundle_json())
    dialog = FileDialog(mode="open", start_dir=tmp_path)
    host = _Host(dialog)
    async with host.run_test() as pilot:
        await pilot.pause()
        dialog.on_directory_tree_file_selected(
            types.SimpleNamespace(path=f))
        await pilot.pause()
        assert dialog.query_one("#name", Input).value == "thing.json"


# ---------- Bug 3: a typed bare name resolves against the current dir ----------

@pytest.mark.asyncio
async def test_open_typed_name_resolves_against_current_dir(tmp_path):
    f = tmp_path / "mybundle.json"
    f.write_text(_bundle_json())
    dialog = FileDialog(mode="open", start_dir=tmp_path)
    host = _Host(dialog)
    async with host.run_test() as pilot:
        await pilot.pause()
        dialog.query_one("#name", Input).value = "mybundle.json"
        await pilot.pause()
        dialog.on_button_pressed(
            types.SimpleNamespace(button=dialog.query_one("#submit", Button)))
        await pilot.pause()
    assert isinstance(host.result, FileResult)
    assert host.result.path == f


@pytest.mark.asyncio
async def test_open_absolute_path_is_honored(tmp_path):
    """Pasting a full path into the name box resolves to that exact file."""
    f = tmp_path / "elsewhere" / "deep.json"
    f.parent.mkdir()
    f.write_text(_bundle_json())
    dialog = FileDialog(mode="open", start_dir=tmp_path)
    host = _Host(dialog)
    async with host.run_test() as pilot:
        await pilot.pause()
        dialog.query_one("#name", Input).value = str(f)
        await pilot.pause()
        dialog.on_button_pressed(
            types.SimpleNamespace(button=dialog.query_one("#submit", Button)))
        await pilot.pause()
    assert isinstance(host.result, FileResult)
    assert host.result.path == f


# ---------- Bug 4: opening a bundle repopulates the live BundlePane ----------

@pytest.mark.asyncio
async def test_open_chosen_repopulates_bundle_pane(tmp_archive, tmp_path):
    from vtextract.tui.app import VtBrowseApp
    from vtextract.tui.panes.bundle_pane import BundlePane

    f = tmp_path / "b.json"
    f.write_text(_bundle_json())
    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test() as pilot:
        await pilot.pause()
        app._on_open_chosen(FileResult(path=f))
        await pilot.pause()
        pane = app.query_one(BundlePane)
        # The pane must observe the loaded selections, not a stale object.
        assert pane.bundle is app.bundle
        assert app.bundle.effective_pages()
        assert "no selections" not in str(pane.root.label)
