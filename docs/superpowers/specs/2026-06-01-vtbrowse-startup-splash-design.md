# vtbrowse startup splash screen — design

**Date:** 2026-06-01
**Status:** Approved (pending implementation plan)
**Component:** `vtbrowse` TUI (`src/vtextract/tui/`)

## Problem

At startup, `vtbrowse` shows a blank document pane while it does two slow
things in `VtBrowseApp.on_mount` (`src/vtextract/tui/app.py`):

1. `_detect_index_state()` makes the first `IndexClient.stats()` call, which
   **lazily opens the SQLite/`IndexService` connection** on the read executor
   thread. This is the genuinely slow step.
2. `_finalize_startup()` → `open_volumes()` mounts `VolumesScreen`, whose
   async `on_mount` queries volumes on the same serial read thread.

During both, the `DocumentPane` is empty, so the user sees a confusing blank
screen with no indication that work is happening.

## Goal

Show a branded splash screen with a live status line while the index/database
loads, so startup reads as intentional and informative rather than broken.

## User-chosen parameters

- **Content:** branded splash + status line — centered `vtbrowse` title, a
  `Virtual Record Treasury browser` subtitle, and a single status line that
  updates as load progresses.
- **Timing:** always show, with a minimum display time (~0.5s) so a fast load
  doesn't flash the splash; dismissed once startup work is done.

## Approach (chosen: A)

A `SplashScreen(ModalScreen[None])` pushed at the top of `on_mount` and
dismissed at the end. A centered modal box renders over the already-composed
main screen; the existing `ModalScreen { align: center middle }` CSS centers
it, matching the chosen mockup. The empty `BundlePane`/`DocumentPane` behind it
are hidden while it is up.

Rejected alternatives:

- **B — render into the `DocumentPane`:** only fills the right pane, leaving
  `BundlePane` visible on the left; not the full centered box chosen.
- **C — full non-modal initial `Screen` swapped after load:** requires
  restructuring the screen stack; more invasive than the problem warrants.

## Components

### New: `src/vtextract/tui/dialogs/splash.py`

`SplashScreen(ModalScreen[None])`, structured like `dialogs/exit.py`:

- `compose()` yields a `Vertical(id="splash-dialog")` containing:
  - a branded title `Static` (`vtbrowse`),
  - a subtitle `Static` (`Virtual Record Treasury browser`),
  - a status `Static(id="splash-status")` with initial text `"Opening index…"`.
- `set_status(text: str)` updates the status line via
  `self.query_one("#splash-status", Static).update(text)`.
- No bindings and no result value. It is purely informational and dismissed by
  the app; it deliberately does **not** trap `escape`/`q` because it is gone
  before the user can interact with it.

### CSS (in `app.py`)

- Add `#splash-dialog` to the existing shared modal selector group (the block
  setting `width: 70%; max-width: 92; height: auto; max-height: 90%;
  padding: 1 2; border: round $primary; background: $surface`).
- Add `#splash-dialog { content-align: center middle; text-align: center; }`
  so the title and status center within the box.

## Control flow — rewritten `VtBrowseApp.on_mount`

```
restore theme                                 # unchanged
splash = SplashScreen(); push_screen(splash)
start = time.monotonic()
splash.set_status("Opening index…")
state = await _detect_index_state()           # warms + opens the DB (slow bit)
if state in ("missing", "stale"):
    await _dismiss_splash(start)              # honor min display, then pop
    push IndexPromptDialog(...)               # existing callback, unchanged
    return
splash.set_status("Loading volumes…")
_finalize_startup(state)                       # open_volumes() mounts VolumesScreen
await _dismiss_splash(start)                    # honor min display, then pop
```

### `_dismiss_splash(start)` helper

```
remaining = SPLASH_MIN_SECONDS - (time.monotonic() - start)
if remaining > 0:
    await asyncio.sleep(remaining)
splash.dismiss()        # guarded: a second call is a no-op
# re-assert focus on the revealed document-pane child via call_after_refresh,
# because the modal held focus while it was up
```

`SPLASH_MIN_SECONDS = 0.5` is a **class attribute** on `VtBrowseApp` so tests
can override it to `0`.

## Status phases

Only the two real phases, conveyed by text (no spinner animation, which keeps
snapshots deterministic):

- `"Opening index…"` — during `_detect_index_state` (the slow connection-open).
- `"Loading volumes…"` — during `_finalize_startup`.

The expensive work (opening the SQLite connection) happens in
`_detect_index_state`; once that returns the connection is warm, so the
`VolumesScreen.on_mount` volumes query is fast and comfortably completes within
the 0.5s minimum display window. The splash therefore does not need to couple
to `VolumesScreen`'s load completion.

## Error handling

- `_detect_index_state` already swallows `IndexError` and returns `"missing"`,
  so the splash always reaches a dismiss path.
- The missing/stale branch dismisses the splash **before** showing
  `IndexPromptDialog` / `NoIndexScreen`, leaving those flows visually unchanged.
- `splash.dismiss()` is guarded so a double-call (e.g. a min-time path race) is
  a no-op.

## Testing

- **`test_empty_app_layout`** currently snapshots the bare panes with no
  `run_before`. With a 0.5s minimum the splash would still be up at screenshot
  time and change that baseline. To keep that test about the panes, it sets
  `SPLASH_MIN_SECONDS = 0` and `pilot.pause()` so the splash dismisses
  immediately; the existing baseline is unchanged.
- **New `tests/tui/test_splash_screen.py`** snapshot test: a `VtBrowseApp`
  subclass whose `_detect_index_state` awaits an `asyncio.Event` that is never
  set, freezing the splash at `"Opening index…"` for a deterministic
  screenshot. Baseline lives under
  `tests/tui/__snapshots__/test_splash_screen/`.
- **Index-prompt tests** (`test_index_prompt.py`) already override
  `_detect_index_state` / `_start_stale_poll`; they set `SPLASH_MIN_SECONDS = 0`
  so the splash neither delays them nor appears in their snapshots.

## Out of scope (YAGNI)

- No animated spinner.
- No progress bar / percentage.
- No per-step progress beyond the two status strings.
- No config option to disable the splash.
- No version string on the splash.

## Files touched

- **New:** `src/vtextract/tui/dialogs/splash.py`
- **New:** `tests/tui/test_splash_screen.py` (+ snapshot baseline)
- **Edit:** `src/vtextract/tui/app.py` — `on_mount` rewrite, `_dismiss_splash`
  helper, `SPLASH_MIN_SECONDS` attribute, `#splash-dialog` CSS.
- **Edit:** `tests/tui/test_app_layout.py` and `tests/tui/test_index_prompt.py`
  — set `SPLASH_MIN_SECONDS = 0` for deterministic, fast snapshots.
