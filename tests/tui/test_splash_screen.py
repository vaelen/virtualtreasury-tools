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


def test_splash_visible_on_startup(snap_compare, tmp_archive):
    """The branded splash (title, subtitle, 'Opening index…' status) renders
    centered over the main screen. on_mount is overridden to push the splash
    and stop, so it stays up for a deterministic screenshot regardless of the
    minimum-display timing."""
    from vtextract.tui.app import VtBrowseApp
    from vtextract.tui.dialogs.splash import SplashScreen

    class _FrozenApp(VtBrowseApp):
        async def on_mount(self) -> None:
            if self._initial_theme in self.available_themes:
                self.theme = self._initial_theme
            self._splash = SplashScreen()
            self.push_screen(self._splash)

    async def before(pilot):
        await pilot.pause()

    assert snap_compare(_FrozenApp(archive=tmp_archive), run_before=before)


def test_splash_shown_on_real_startup_path(tmp_archive):
    """Regression: on the REAL startup path (the production ``on_mount``, not an
    override) the splash must actually reach the screen.

    Textual dispatches the initial ``events.Mount`` — and therefore
    ``App.on_mount`` — inside ``with self.batch_update()``, which suspends all
    repaints until the batch ends. If ``on_mount`` does the slow index-open and
    dismisses the splash before returning, the splash is created and destroyed
    entirely within that no-paint window and never reaches the terminal. The
    fix defers the startup work (via ``call_after_refresh``) so ``on_mount``
    returns, the batch ends, the splash paints, and only then does the work run.

    We slow index-state detection so the splash stays up long enough to observe
    it as the current screen. On the buggy (blocking) code ``run_test`` only
    becomes ready after ``on_mount`` has already dismissed the splash, so the
    current screen is the main/volumes screen and the assertion fails.
    """
    from vtextract.tui.app import VtBrowseApp
    from vtextract.tui.dialogs.splash import SplashScreen

    class _SlowApp(VtBrowseApp):
        SPLASH_MIN_SECONDS = 0.0
        SPLASH_DEFER_STARTUP = True  # exercise the real deferred path, not the
        #                              fixture's inline test path

        async def _detect_index_state(self):
            await asyncio.sleep(0.3)
            return await super()._detect_index_state()

    async def runner():
        app = _SlowApp(archive=tmp_archive)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, SplashScreen), (
                "expected the splash to be the visible screen during startup, "
                f"got {type(app.screen).__name__}"
            )

    asyncio.run(runner())


def test_deferred_startup_missing_index_shows_prompt(tmp_archive):
    """Deferred (production) path with a missing index: the splash is dismissed
    and the IndexPromptDialog is shown. Covers the deferred branch that pushes a
    screen *with a result-callback* from inside a call_after_refresh callback —
    the place most likely to diverge from the inline test path."""
    from vtextract.tui.app import VtBrowseApp
    from vtextract.tui.dialogs.index_prompt import IndexPromptDialog

    class _MissingApp(VtBrowseApp):
        SPLASH_MIN_SECONDS = 0.0
        SPLASH_DEFER_STARTUP = True

        async def _detect_index_state(self):
            return "missing"

        def action_build_index(self) -> None:  # no-op: keep the prompt up
            pass

        def _start_stale_poll(self) -> None:  # avoid timer-driven nondeterminism
            pass

    async def runner():
        app = _MissingApp(archive=tmp_archive)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()
            assert isinstance(app.screen, IndexPromptDialog), (
                f"expected IndexPromptDialog, got {type(app.screen).__name__}"
            )
            assert app._splash is None  # splash dismissed, not stranded

    asyncio.run(runner())


def test_deferred_startup_dismisses_splash_on_error(tmp_archive):
    """Deferred (production) path: if startup work raises, _run_startup's
    leak-guard dismisses the splash rather than stranding it over a
    half-initialized app. Asserts the splash reference is cleared regardless of
    how Textual surfaces the callback error."""
    from vtextract.tui.app import VtBrowseApp

    class _BoomApp(VtBrowseApp):
        SPLASH_MIN_SECONDS = 0.0
        SPLASH_DEFER_STARTUP = True

        async def _detect_index_state(self):
            raise RuntimeError("boom")

    app = _BoomApp(archive=tmp_archive)

    async def runner():
        try:
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.pause()
        except RuntimeError:
            pass  # Textual may re-raise the callback error on teardown

    asyncio.run(runner())
    assert app._splash is None  # leak-guard ran; splash not stranded
