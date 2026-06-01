# vtbrowse Startup Splash Screen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a branded, status-updating splash screen while `vtbrowse` opens its SQLite index and loads volumes, so startup no longer shows a confusing blank pane.

**Architecture:** A `SplashScreen(ModalScreen[None])` is pushed at the very top of `VtBrowseApp.on_mount`, displays `"Opening index…"` then `"Loading volumes…"`, and is dismissed once startup work completes and a minimum display time (`SPLASH_MIN_SECONDS = 0.5`) has elapsed. The existing modal CSS centers it. Tests neutralize the delay with an autouse fixture that sets `SPLASH_MIN_SECONDS = 0`, so the splash flashes and is gone before any screenshot — existing baselines are unchanged.

**Tech Stack:** Python, Textual (`ModalScreen`, `Static`, `Vertical`), `pytest`, `pytest-textual-snapshot`, `uv`.

**Spec:** `docs/superpowers/specs/2026-06-01-vtbrowse-startup-splash-design.md`

---

## File Structure

- **Create** `src/vtextract/tui/dialogs/splash.py` — the `SplashScreen` widget (one responsibility: render the splash box + expose `set_status`).
- **Modify** `src/vtextract/tui/app.py` — `on_mount` rewrite, `_dismiss_splash` / `_focus_document_pane` helpers, `SPLASH_MIN_SECONDS` class attribute, `self._splash` init, `#splash-dialog` CSS, new imports.
- **Modify** `tests/tui/conftest.py` — autouse fixture forcing `SPLASH_MIN_SECONDS = 0` for all TUI tests.
- **Create** `tests/tui/test_splash_screen.py` — a behavioral `set_status` test and a snapshot test that the splash renders on startup.
- **Create** `tests/tui/__snapshots__/test_splash_screen/` — generated snapshot baseline.

A note on the test strategy (deviates from the spec's per-test edits for the better): rather than editing `test_app_layout.py` and `test_index_prompt.py` individually, a single autouse fixture in `tests/tui/conftest.py` sets `SPLASH_MIN_SECONDS = 0` for every TUI test. This is more robust — every full-app test (exit, bindings, navigation, etc.) is affected by a modal-on-top splash, not just those two, so neutralizing it in one place is correct and minimal.

---

## Task 1: `SplashScreen` widget

**Files:**
- Create: `src/vtextract/tui/dialogs/splash.py`
- Test: `tests/tui/test_splash_screen.py`

- [ ] **Step 1: Write the failing behavioral test**

Create `tests/tui/test_splash_screen.py`:

```python
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
            assert "Opening index" in str(status.renderable)
            app.splash.set_status("Loading volumes…")
            await pilot.pause()
            assert "Loading volumes" in str(status.renderable)

    asyncio.run(runner())
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/tui/test_splash_screen.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vtextract.tui.dialogs.splash'`.

- [ ] **Step 3: Write the minimal implementation**

Create `src/vtextract/tui/dialogs/splash.py`:

```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""Startup splash shown while vtbrowse opens the index and loads volumes.

A centered, app-dismissed modal with a single live status line. It traps no
keys and returns no result: ``VtBrowseApp.on_mount`` pushes it first thing and
dismisses it once startup work (index open + volumes load) is done, after a
minimum display interval so a fast load does not flash it.
"""

from __future__ import annotations

from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


class SplashScreen(ModalScreen[None]):
    def compose(self):
        with Vertical(id="splash-dialog"):
            yield Static("vtbrowse", id="splash-title")
            yield Static("Virtual Record Treasury browser", id="splash-subtitle")
            yield Static("Opening index…", id="splash-status")

    def set_status(self, text: str) -> None:
        self.query_one("#splash-status", Static).update(text)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/tui/test_splash_screen.py -v`
Expected: PASS (`test_splash_set_status_updates_line`).

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/tui/dialogs/splash.py tests/tui/test_splash_screen.py
git commit -m "feat(tui): add SplashScreen widget with live status line"
```

---

## Task 2: Wire the splash into startup

**Files:**
- Modify: `src/vtextract/tui/app.py`
- Modify: `tests/tui/conftest.py`

This task lands the wiring AND the test-neutralizing fixture in one commit, because a 0.5s modal-on-top splash would otherwise break every full-app TUI test. Validation is the full TUI suite staying green.

- [ ] **Step 1: Add the autouse fixture neutralizing the splash delay in tests**

In `tests/tui/conftest.py`, add these imports near the top (the file already imports `pytest` and `Path`):

```python
from vtextract.tui.app import VtBrowseApp
```

Then append this fixture at the end of the file:

```python
@pytest.fixture(autouse=True)
def _instant_splash(monkeypatch):
    """Every full-app TUI test mounts the startup splash (a modal pushed first
    in on_mount). With the production 0.5s minimum it would still be on top
    when a test interacts or screenshots. Force a zero minimum so the splash is
    pushed and dismissed within on_mount, leaving the main screen active and
    existing baselines unchanged. The dedicated splash render test overrides
    on_mount to keep the splash up regardless."""
    monkeypatch.setattr(VtBrowseApp, "SPLASH_MIN_SECONDS", 0.0)
```

- [ ] **Step 2: Run the full TUI suite to confirm the fixture is inert before wiring**

Run: `uv run pytest tests/tui/ -q`
Expected: PASS — the fixture sets an attribute that does not exist yet... which would error. So this step is expected to FAIL with `AttributeError: <class 'VtBrowseApp'> has no attribute 'SPLASH_MIN_SECONDS'`. That failure confirms the fixture is wired; Step 3 adds the attribute. (Do not commit between Step 1 and Step 4 — they land together.)

- [ ] **Step 3: Add imports, the class attribute, the splash field, and rewrite `on_mount`**

In `src/vtextract/tui/app.py`:

(a) Add to the stdlib imports block (currently `from pathlib import Path` / `from typing import Literal`):

```python
import asyncio
import time
```

(b) Add the splash import alongside the other dialog imports (e.g. after the `index_prompt` import):

```python
from vtextract.tui.dialogs.splash import SplashScreen
```

(c) Add a class attribute just below `TITLE = "vtbrowse"`:

```python
    # Minimum time the startup splash stays up, so a fast index open does not
    # flash it. Tests override this to 0 (see tests/tui/conftest.py).
    SPLASH_MIN_SECONDS = 0.5
```

(d) In `__init__`, add the splash field alongside the other instance attributes (e.g. after `self._bundle_dirty = False`):

```python
        self._splash: SplashScreen | None = None
```

(e) Replace the entire existing `on_mount` method:

```python
    async def on_mount(self) -> None:
        # Restore the saved theme. Guarded: an unregistered name (a typo, or a
        # theme dropped in a Textual upgrade) would raise InvalidThemeError, so
        # ignore it and let Textual's default stand.
        if self._initial_theme in self.available_themes:
            self.theme = self._initial_theme
        state = await self._detect_index_state()
        if state in ("missing", "stale"):
            self.push_screen(
                IndexPromptDialog(
                    state=state, archive=self.archive,
                    index_path=self._index_path()),
                lambda ok, s=state: self._on_index_prompt_dismissed(ok, s),
            )
            return
        self._finalize_startup(state)
```

with:

```python
    async def on_mount(self) -> None:
        # Restore the saved theme. Guarded: an unregistered name (a typo, or a
        # theme dropped in a Textual upgrade) would raise InvalidThemeError, so
        # ignore it and let Textual's default stand.
        if self._initial_theme in self.available_themes:
            self.theme = self._initial_theme
        # Push the splash first so the slow index open renders behind it
        # rather than over a blank pane. It defaults to the "Opening index…"
        # phase via its compose; we set later phases after the awaits below
        # (by which point the splash is mounted and queryable).
        self._splash = SplashScreen()
        self.push_screen(self._splash)
        start = time.monotonic()
        state = await self._detect_index_state()
        if state in ("missing", "stale"):
            await self._dismiss_splash(start)
            self.push_screen(
                IndexPromptDialog(
                    state=state, archive=self.archive,
                    index_path=self._index_path()),
                lambda ok, s=state: self._on_index_prompt_dismissed(ok, s),
            )
            return
        self._splash.set_status("Loading volumes…")
        self._finalize_startup(state)
        await self._dismiss_splash(start)
        self.call_after_refresh(self._focus_document_pane)
```

(f) Add the two helper methods immediately after `on_mount` (before `on_unmount`):

```python
    async def _dismiss_splash(self, start: float) -> None:
        # Keep the splash up for at least SPLASH_MIN_SECONDS so a fast load
        # does not flash it, then pop it. Guarded so a second call is a no-op.
        remaining = self.SPLASH_MIN_SECONDS - (time.monotonic() - start)
        if remaining > 0:
            await asyncio.sleep(remaining)
        if self._splash is not None:
            self._splash.dismiss()
            self._splash = None

    def _focus_document_pane(self) -> None:
        # After the modal splash pops, focus returns to nothing (the splash was
        # pushed before any screen was focused), so re-assert focus on the
        # revealed document-pane child (the VolumesScreen).
        children = self.query_one(DocumentPane).children
        if children:
            children[0].focus()
```

- [ ] **Step 4: Add the centering CSS for the splash box**

In `src/vtextract/tui/app.py`, in the `CSS` string, add `#splash-dialog,` to the shared modal selector group. Change:

```css
    #search-dialog, #extract-dialog, #file-dialog, #exit-dialog,
    #progress-modal, #help-dialog, #info-dialog, #index-prompt {
```

to:

```css
    #search-dialog, #extract-dialog, #file-dialog, #exit-dialog,
    #progress-modal, #help-dialog, #info-dialog, #index-prompt,
    #splash-dialog {
```

Then, immediately after that rule's closing `}`, add:

```css
    /* The splash centers its title + status within the box. */
    #splash-dialog { content-align: center middle; text-align: center; }
```

- [ ] **Step 5: Run the full TUI suite to confirm no regressions**

Run: `uv run pytest tests/tui/ -q`
Expected: PASS — all existing TUI tests green. The splash is pushed and immediately dismissed within `on_mount` (zero minimum under the fixture), so post-mount the main screen is active and all baselines render as before.

- [ ] **Step 6: Commit**

```bash
git add src/vtextract/tui/app.py tests/tui/conftest.py
git commit -m "feat(tui): show startup splash while index opens and volumes load"
```

---

## Task 3: Snapshot test — splash renders on startup

**Files:**
- Modify: `tests/tui/test_splash_screen.py`
- Create: `tests/tui/__snapshots__/test_splash_screen/` (generated baseline)

- [ ] **Step 1: Add the snapshot test**

Append to `tests/tui/test_splash_screen.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails (no baseline yet)**

Run: `uv run pytest tests/tui/test_splash_screen.py::test_splash_visible_on_startup -v`
Expected: FAIL — `pytest-textual-snapshot` reports a missing/!= snapshot because no baseline exists yet.

- [ ] **Step 3: Generate the snapshot baseline**

Run: `uv run pytest tests/tui/test_splash_screen.py::test_splash_visible_on_startup --snapshot-update -q`
Expected: the baseline is written under `tests/tui/__snapshots__/test_splash_screen/`.

- [ ] **Step 4: Inspect the generated snapshot**

Open the generated `.svg` under `tests/tui/__snapshots__/test_splash_screen/` (or the HTML report path printed on the failing run) and confirm it shows a centered box containing `vtbrowse`, `Virtual Record Treasury browser`, and `Opening index…`. If it does not, fix the widget/CSS before continuing.

- [ ] **Step 5: Re-run to verify the baseline matches**

Run: `uv run pytest tests/tui/test_splash_screen.py -v`
Expected: PASS (both `test_splash_set_status_updates_line` and `test_splash_visible_on_startup`).

- [ ] **Step 6: Commit**

```bash
git add tests/tui/test_splash_screen.py tests/tui/__snapshots__/test_splash_screen/
git commit -m "test(tui): snapshot the startup splash render"
```

---

## Task 4: Full-suite regression check

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `uv run pytest -q`
Expected: PASS — the whole suite (including non-TUI tests) is green. The autouse `_instant_splash` fixture is scoped to `tests/tui/` only, so non-TUI tests are unaffected.

- [ ] **Step 2: Manual smoke check (optional but recommended)**

Run: `uv run vtbrowse --archive ./archive` against a real archive and confirm the splash appears briefly with `Opening index…` / `Loading volumes…` and is replaced by the volumes list. Press `q` to quit.

- [ ] **Step 3: If anything changed in Step 2 debugging, re-commit**

```bash
git add -A
git commit -m "fix(tui): splash startup adjustments"
```

(Skip if nothing changed.)

---

## Self-Review Notes

- **Spec coverage:** SplashScreen widget (Task 1) ✓; on_mount wiring with two status phases + min-display + dismissal + focus re-assertion (Task 2) ✓; `#splash-dialog` CSS centering (Task 2) ✓; missing/stale path dismisses splash before IndexPrompt (Task 2 on_mount) ✓; testability / deterministic fast snapshots (Task 2 fixture + Task 3 frozen snapshot) ✓; out-of-scope items (no spinner/progress/config/version) are simply not built ✓.
- **Deviation from spec testing detail:** the spec proposed editing `test_app_layout.py` and `test_index_prompt.py` to set `SPLASH_MIN_SECONDS = 0`. The plan instead uses one autouse fixture in `tests/tui/conftest.py`. This is strictly broader and more correct — *every* full-app TUI test is affected by the modal splash, not just those two — and avoids touching many files. Same goal (deterministic, fast, unchanged baselines), one place.
- **Type/name consistency:** `SplashScreen`, `set_status`, `#splash-status`, `#splash-dialog`, `SPLASH_MIN_SECONDS`, `self._splash`, `_dismiss_splash`, `_focus_document_pane` are used identically across all tasks. `_detect_index_state` returns `Literal["missing","stale","ok"]` (unchanged) and the `("missing","stale")` branch matches the existing code.
- **No placeholders:** every code and command step is concrete.
