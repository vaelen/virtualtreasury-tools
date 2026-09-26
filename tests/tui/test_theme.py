# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

"""vtbrowse restores a saved theme on launch and ignores an unknown one."""

from __future__ import annotations

import pytest

from vtextract.tui.app import VtBrowseApp


@pytest.mark.asyncio
async def test_initial_theme_is_applied(tmp_archive):
    app = VtBrowseApp(archive=tmp_archive, initial_theme="nord")
    async with app.run_test():
        assert app.theme == "nord"


@pytest.mark.asyncio
async def test_unknown_initial_theme_falls_back_to_default(tmp_archive):
    app = VtBrowseApp(archive=tmp_archive, initial_theme="no-such-theme")
    async with app.run_test():
        # An unregistered name would raise InvalidThemeError if set blindly;
        # it must be ignored, leaving Textual's default in place.
        assert app.theme == "textual-dark"


@pytest.mark.asyncio
async def test_no_initial_theme_keeps_default(tmp_archive):
    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test():
        assert app.theme == "textual-dark"
