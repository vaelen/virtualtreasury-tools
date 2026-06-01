# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""Tests for the vtbrowse startup splash screen."""

from __future__ import annotations

import asyncio

from textual.app import App
from textual.widgets import Static

from vtextract.tui.dialogs.splash import SplashScreen


def test_splash_set_status_updates_line():
    """set_status replaces the visible status text; the default is the
    'Opening index…' phase shown while the DB connection is opening."""

    class _Host(App):
        async def on_mount(self) -> None:
            self.splash = SplashScreen()
            self.push_screen(self.splash)

    app = _Host()

    async def runner():
        async with app.run_test() as pilot:
            await pilot.pause()
            status = app.splash.query_one("#splash-status", Static)
            assert "Opening index" in str(status.content)
            app.splash.set_status("Loading volumes…")
            await pilot.pause()
            assert "Loading volumes" in str(status.content)

    asyncio.run(runner())
