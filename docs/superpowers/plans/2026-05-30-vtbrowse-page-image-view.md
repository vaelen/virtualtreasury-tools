# vtbrowse Page Image View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In the `vtbrowse` TUI, let the user press `enter` while viewing a page's transcription to swap to its scanned page image, and `enter` again to swap back.

**Architecture:** All changes live in `TranscriptionScreen`, which gains a `view` mode (`"text"` | `"image"`) and a body widget swapped on toggle. Images render via the `textual-image` Textual `Image` widget (terminal graphics protocols with Unicode fallback). `esc` still exits to origin; `space`/`←`/`→` still work; image mode is preserved across paging.

**Tech Stack:** Python ≥3.12, Textual, `textual-image[textual]` (+ Pillow, transitively), pytest / pytest-asyncio / pytest-textual-snapshot.

---

## Verified integration facts (read before starting)

These were confirmed against the live libraries/fixtures while writing this plan — do not re-litigate them:

1. **Dependency version:** `textual-image` **0.13.x wheels are broken** (ship no Python modules). Use `textual-image[textual]>=0.11,<0.13` (0.12.0 resolves and works). Installed Textual (8.2.7) satisfies its `textual>=0.68` floor.
2. **Import location matters:** `textual-image` queries the terminal for the best renderer **at import time**, which must happen **before** the Textual app starts. Therefore `from textual_image.widget import Image` goes at **module top** of `transcription.py` (imported via `app.py` at process startup), never lazily inside a method.
3. **Widget construction:** `Image(path, id="page-image")` — the path (a `pathlib.Path`) is the first positional arg; `id=` is a standard widget kwarg. `isinstance(widget, Image)` is `True` for the auto-selected subclass.
4. **Sizing is required:** without an explicit size the widget renders at size 0 and raises `ValueError: height and width must be > 0`. Scope `#page-image { width: 100%; height: 100%; }` via the screen's `DEFAULT_CSS`. This makes it work under the default `run_test()` size.
5. **Snapshots will change:** the app has a `Footer()` that renders the focused screen's binding labels. The existing transcription snapshots (`test_transcription_view`, `test_transcription_highlights`) and the help-dialog snapshot (`test_help_dialog_via_question`) already show binding/label text, so adding the `enter` binding and the help row **requires regenerating those three baselines** with `--snapshot-update`.
6. **Index stays fresh:** `is_stale` / the index builder only walk `*/metadata.json`, `*/volume.json`, and `*/*.jpg.txt`. Dropping a `.jpg` into an already-built archive does **not** make the index stale, so tests can write image files after `tmp_archive` builds and the app won't pop the index-prompt dialog.
7. **Fixture facts:** volume `volA` has pages `volA_p0.jpg` then `volA_p1.jpg` (next of p0 is p1). The default `tmp_archive` fixture has transcriptions but **no** image files on disk.

## File structure

- Modify: `pyproject.toml` — add dependency, bump Python floor.
- Modify: `src/vtextract/tui/screens/transcription.py` — view mode, toggle, image body, CSS.
- Modify: `src/vtextract/tui/app.py:230-242` — `open_transcription` gains `view` + title suffix + `base_title`.
- Modify: `src/vtextract/tui/dialogs/help.py:11-34` — add a help row.
- Create: `tests/tui/test_page_image_view.py` — behavior tests.
- Regenerate: `tests/tui/__snapshots__/test_transcription_screen/test_transcription_view.raw`,
  `tests/tui/__snapshots__/test_transcription_highlights/test_transcription_highlights_query_terms.raw`,
  `tests/tui/__snapshots__/test_help_dialog/test_help_dialog_via_question.raw`.

---

## Task 1: Add the textual-image dependency and bump the Python floor

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add the dependency and bump `requires-python`**

In `pyproject.toml`, change the `dependencies` line and `requires-python`:

```toml
requires-python = ">=3.12"
```

```toml
dependencies = ["httpx>=0.27", "rich>=13", "textual>=0.50", "textual-image[textual]>=0.11,<0.13"]
```

(Leave the existing `httpx`/`rich`/`textual` entries as they are; only append `textual-image` and edit `requires-python`.)

- [ ] **Step 2: Sync the environment and refresh the lockfile**

Run: `uv sync --extra dev`
Expected: resolves and installs `textual-image` (0.12.0) and `pillow`; `uv.lock` is updated.

- [ ] **Step 3: Verify the widget imports**

Run: `uv run python -c "from textual_image.widget import Image; print('ok', Image.__name__)"`
Expected: prints `ok Image` (no `ModuleNotFoundError`).

- [ ] **Step 4: Confirm the existing suite still passes**

Run: `uv run pytest -q`
Expected: PASS (no behavior changed yet).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build(vtbrowse): add textual-image dependency; require python>=3.12"
```

---

## Task 2: Toggle a page between transcription text and its image

**Files:**
- Modify: `src/vtextract/tui/screens/transcription.py`
- Test: `tests/tui/test_page_image_view.py`
- Regenerate: `tests/tui/__snapshots__/test_transcription_screen/test_transcription_view.raw`,
  `tests/tui/__snapshots__/test_transcription_highlights/test_transcription_highlights_query_terms.raw`

- [ ] **Step 1: Write the failing tests**

Create `tests/tui/test_page_image_view.py`:

```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""Toggling a page between its transcription text and its scanned image."""

from __future__ import annotations

import pytest
from PIL import Image as PILImage

from vtextract.tui.app import VtBrowseApp
from vtextract.tui.panes.document_pane import DocumentPane


def _active(app):
    return app.query_one(DocumentPane).children[0]


def _write_image(archive, root_id, page_key):
    path = archive / "pages" / root_id / page_key
    PILImage.new("RGB", (8, 8), (180, 40, 40)).save(path, "JPEG")
    return path


@pytest.mark.asyncio
async def test_enter_toggles_to_image_and_back(tmp_archive):
    _write_image(tmp_archive, "volA", "volA_p0.jpg")
    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.open_transcription("volA", "volA_p0.jpg", origin="pages")
        await pilot.pause()
        assert len(app.query("#transcription-body")) == 1
        assert len(app.query("#page-image")) == 0

        await pilot.press("enter")          # text -> image
        await pilot.pause()
        assert len(app.query("#page-image")) == 1
        assert len(app.query("#transcription-body")) == 0

        await pilot.press("enter")          # image -> text
        await pilot.pause()
        assert len(app.query("#transcription-body")) == 1
        assert len(app.query("#page-image")) == 0


@pytest.mark.asyncio
async def test_enter_on_page_without_image_shows_placeholder(tmp_archive):
    # tmp_archive has transcriptions but no image files on disk.
    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.open_transcription("volA", "volA_p0.jpg", origin="pages")
        await pilot.pause()

        await pilot.press("enter")          # text -> (missing) image
        await pilot.pause()
        placeholder = app.query_one("#page-image-missing")
        assert "No image on disk" in str(placeholder.renderable)
        assert len(app.query("#page-image")) == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/tui/test_page_image_view.py -q`
Expected: FAIL — pressing `enter` does nothing (no `toggle_view` action), so `#page-image` / `#page-image-missing` are never mounted.

- [ ] **Step 3: Rewrite `transcription.py` with the view toggle**

Replace the entire contents of `src/vtextract/tui/screens/transcription.py` with:

```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from textual.binding import Binding
from textual.containers import ScrollableContainer
from textual.widgets import Static

# Imported at module top (not lazily) on purpose: textual-image queries the
# terminal for the best rendering protocol at import time, which must happen
# before the Textual app starts. This module is imported via app.py at startup.
from textual_image.widget import Image

from vtextract.theme import THEMES, highlight_terms
from vtextract.tui.archive_reader import ArchiveReader
from vtextract.tui.bundle import Bundle, PageRef
from vtextract.tui.index_client import IndexClient

_NO_IMAGE_MESSAGE = (
    "No image on disk for this page — re-run vtextract with --images to "
    "download it."
)


class TranscriptionScreen(ScrollableContainer):
    DEFAULT_CSS = """
    TranscriptionScreen #page-image {
        width: 100%;
        height: 100%;
    }
    """

    BINDINGS = [
        Binding("left", "prev_page", "prev"),
        Binding("right", "next_page", "next"),
        Binding("enter", "toggle_view", "image"),
        Binding("space", "toggle_select", "select"),
        Binding("escape", "back", "back"),
    ]

    can_focus = True

    def __init__(self, *, index: IndexClient, reader: ArchiveReader,
                 bundle: Bundle, root_id: str, page_key: str,
                 query: str | None = None, origin: str = "pages",
                 view: str = "text", base_title: str | None = None) -> None:
        super().__init__()
        self.index = index
        self.reader = reader
        self.bundle = bundle
        self.root_id = root_id
        self.page_key = page_key
        self.query = query
        # Where this view was opened from, so ``esc`` (action_back) returns
        # there: "results" → the search results screen, "pages" → the volume's
        # page list. Preserved across prev/next page navigation.
        self.origin = origin
        # "text" shows the transcription; "image" shows the page scan. Toggled
        # with enter and preserved across prev/next paging.
        self.view = view
        # Pane title without the mode suffix; used to re-derive the title when
        # toggling between the text and image views.
        self.base_title = base_title or page_key

    def compose(self):
        yield self._build_body()

    def _build_body(self):
        if self.view == "image":
            if self.reader.image_exists(self.root_id, self.page_key):
                return Image(
                    self.reader.image_path(self.root_id, self.page_key),
                    id="page-image",
                )
            return Static(_NO_IMAGE_MESSAGE, id="page-image-missing")
        text = self.reader.read_transcription(self.root_id, self.page_key) or \
            "(no transcription available for this page)"
        styled = highlight_terms(text, self.query, THEMES["dark"].match_style)
        return Static(styled, id="transcription-body")

    def _current_ref(self) -> PageRef:
        return PageRef(self.root_id, self.page_key)

    async def action_toggle_view(self) -> None:
        self.view = "image" if self.view == "text" else "text"
        await self.remove_children()
        await self.mount(self._build_body())
        suffix = " [image]" if self.view == "image" else ""
        self.app.set_pane_title(self.base_title + suffix)  # type: ignore[attr-defined]

    async def action_prev_page(self) -> None:
        nav = await self.index.page(self.root_id, self.page_key)
        if nav and nav.get("previous"):
            self.app.open_transcription(  # type: ignore[attr-defined]
                self.root_id, nav["previous"]["page_key"],
                query=self.query, origin=self.origin)

    async def action_next_page(self) -> None:
        nav = await self.index.page(self.root_id, self.page_key)
        if nav and nav.get("next"):
            self.app.open_transcription(  # type: ignore[attr-defined]
                self.root_id, nav["next"]["page_key"],
                query=self.query, origin=self.origin)

    def action_toggle_select(self) -> None:
        self.bundle.toggle_page(self._current_ref())
        self.app.bundle_changed()  # type: ignore[attr-defined]

    def action_back(self) -> None:
        if self.origin == "results":
            self.app.action_open_results()  # type: ignore[attr-defined]
        else:
            self.app.open_pages(self.root_id)  # type: ignore[attr-defined]

    def selected_context(self) -> tuple | None:
        return ("page", self.root_id, self.page_key)
```

(Note: `action_prev_page` / `action_next_page` are intentionally left without view-preservation here — that is added in Task 3.)

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `uv run pytest tests/tui/test_page_image_view.py -q`
Expected: PASS (both tests).

- [ ] **Step 5: Regenerate the two affected transcription snapshots**

The `enter` binding adds an `image` entry to the footer, changing these snapshots.

Run: `uv run pytest tests/tui/test_transcription_screen.py tests/tui/test_transcription_highlights.py -q`
Expected: FAIL (snapshot mismatch — footer gained an `image` entry).

Run: `uv run pytest tests/tui/test_transcription_screen.py tests/tui/test_transcription_highlights.py --snapshot-update -q`
Expected: snapshots updated.

- [ ] **Step 6: Confirm the diff is only the new footer entry**

Run: `git diff --stat tests/tui/__snapshots__/`
Expected: only the two `.raw` files changed. Spot-check with `git diff tests/tui/__snapshots__/test_transcription_screen/` that the change is the added `image` footer label, not the transcription body content.

- [ ] **Step 7: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/vtextract/tui/screens/transcription.py tests/tui/test_page_image_view.py tests/tui/__snapshots__/
git commit -m "feat(vtbrowse): toggle page transcription <-> scanned image with enter"
```

---

## Task 3: Preserve image mode across prev/next paging

**Files:**
- Modify: `src/vtextract/tui/app.py:230-242` (`open_transcription`)
- Modify: `src/vtextract/tui/screens/transcription.py` (`action_prev_page`, `action_next_page`)
- Test: `tests/tui/test_page_image_view.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/tui/test_page_image_view.py`:

```python
@pytest.mark.asyncio
async def test_image_mode_persists_across_next_page(tmp_archive):
    _write_image(tmp_archive, "volA", "volA_p0.jpg")
    _write_image(tmp_archive, "volA", "volA_p1.jpg")
    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.open_transcription("volA", "volA_p0.jpg", origin="pages")
        await pilot.pause()

        await pilot.press("enter")          # -> image mode
        await pilot.pause()
        assert _active(app).view == "image"

        await pilot.press("right")          # next page, should stay in image mode
        await pilot.pause()
        screen = _active(app)
        assert screen.page_key == "volA_p1.jpg"
        assert screen.view == "image"
        assert len(app.query("#page-image")) == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/tui/test_page_image_view.py::test_image_mode_persists_across_next_page -q`
Expected: FAIL — after `right`, the new screen is in `"text"` mode (`open_transcription` does not yet accept/propagate `view`), so `screen.view == "image"` fails.

- [ ] **Step 3: Add a `view` parameter to `open_transcription`**

In `src/vtextract/tui/app.py`, replace the `open_transcription` method (currently lines 230-242) with:

```python
    def open_transcription(self, root_id: str, page_key: str,
                           *, query: str | None = None,
                           origin: str = "pages",
                           view: str = "text") -> None:
        vol = (self.current_volume_title
               if self.current_root_id == root_id else None)
        base_title = f"{vol} — {page_key}" if vol else page_key
        screen = TranscriptionScreen(
            index=self.index, reader=ArchiveReader(self.archive),
            bundle=self.bundle, root_id=root_id, page_key=page_key,
            query=query, origin=origin, view=view, base_title=base_title,
        )
        title = base_title + (" [image]" if view == "image" else "")
        # Transcription is a single document, not a list — no count footer.
        self._mount_screen(screen, title=title)
```

- [ ] **Step 4: Propagate the current view through paging**

In `src/vtextract/tui/screens/transcription.py`, update both paging actions to pass `view=self.view`:

```python
    async def action_prev_page(self) -> None:
        nav = await self.index.page(self.root_id, self.page_key)
        if nav and nav.get("previous"):
            self.app.open_transcription(  # type: ignore[attr-defined]
                self.root_id, nav["previous"]["page_key"],
                query=self.query, origin=self.origin, view=self.view)

    async def action_next_page(self) -> None:
        nav = await self.index.page(self.root_id, self.page_key)
        if nav and nav.get("next"):
            self.app.open_transcription(  # type: ignore[attr-defined]
                self.root_id, nav["next"]["page_key"],
                query=self.query, origin=self.origin, view=self.view)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/tui/test_page_image_view.py::test_image_mode_persists_across_next_page -q`
Expected: PASS.

- [ ] **Step 6: Run the full suite (guards against title/snapshot regressions)**

Run: `uv run pytest -q`
Expected: PASS. (Default `view="text"` keeps the non-image title and existing snapshots unchanged.)

- [ ] **Step 7: Commit**

```bash
git add src/vtextract/tui/app.py src/vtextract/tui/screens/transcription.py tests/tui/test_page_image_view.py
git commit -m "feat(vtbrowse): keep image mode when paging with left/right"
```

---

## Task 4: Guard that esc exits to origin from image mode

**Files:**
- Test: `tests/tui/test_page_image_view.py`

This behavior already holds (the `escape` binding lives on the screen regardless of body). This task adds a regression guard so a future change can't silently break it.

- [ ] **Step 1: Write the test**

Append to `tests/tui/test_page_image_view.py`:

```python
@pytest.mark.asyncio
async def test_escape_from_image_mode_returns_to_pages(tmp_archive):
    from vtextract.tui.screens.pages import PagesScreen

    _write_image(tmp_archive, "volA", "volA_p0.jpg")
    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")          # volumes -> volA page list
        await pilot.pause()
        await pilot.press("enter")          # -> a page's transcription
        await pilot.pause()
        await pilot.press("enter")          # text -> image
        await pilot.pause()
        assert _active(app).view == "image"

        await pilot.press("escape")         # exit to origin
        await pilot.pause()
        assert isinstance(_active(app), PagesScreen)
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/tui/test_page_image_view.py::test_escape_from_image_mode_returns_to_pages -q`
Expected: PASS (verifies existing `action_back` behavior holds in image mode).

- [ ] **Step 3: Commit**

```bash
git add tests/tui/test_page_image_view.py
git commit -m "test(vtbrowse): esc from image mode returns to page list"
```

---

## Task 5: Document the toggle in the help dialog

**Files:**
- Modify: `src/vtextract/tui/dialogs/help.py:11-34`
- Regenerate: `tests/tui/__snapshots__/test_help_dialog/test_help_dialog_via_question.raw`

- [ ] **Step 1: Add a help row for the enter toggle**

In `src/vtextract/tui/dialogs/help.py`, add a row to the `_BINDINGS` tuple immediately after the existing `("⏎", "search result row", ...)` line (currently line 17):

```python
    ("⏎",        "transcription view",        "swap text ⇄ page image"),
```

So that region reads:

```python
    ("⏎",        "volume row",                "open page list"),
    ("⏎",        "page row",                  "open transcription"),
    ("⏎",        "search result row",         "open first matched page"),
    ("⏎",        "transcription view",        "swap text ⇄ page image"),
    ("space",    "page row, transcription",   "toggle page user state"),
```

- [ ] **Step 2: Regenerate the help snapshot**

Run: `uv run pytest tests/tui/test_help_dialog.py -q`
Expected: FAIL (the help table gained a row).

Run: `uv run pytest tests/tui/test_help_dialog.py --snapshot-update -q`
Expected: snapshot updated.

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/vtextract/tui/dialogs/help.py tests/tui/__snapshots__/test_help_dialog/
git commit -m "docs(vtbrowse): document enter toggle (text/image) in help dialog"
```

---

## Task 6: Update user-facing docs

**Files:**
- Modify: `README.md` (vtbrowse key bindings section)

- [ ] **Step 1: Locate the vtbrowse key-bindings list**

Run: `grep -n "esc\|prev\|select\|key binding\|vtbrowse" README.md | head`
Expected: finds the vtbrowse bindings/usage section.

- [ ] **Step 2: Add the enter binding to the documented bindings**

Add a bullet/row to the vtbrowse key-bindings list (match the surrounding format) describing:

> `enter` (in a transcription) — swap between the transcription text and the scanned page image; if no image is on disk, shows a hint to re-run `vtextract --images`.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(vtbrowse): document page image toggle in README"
```

---

## Self-review (completed while writing)

- **Spec coverage:** enter-toggle both ways (Task 2) ✓; placeholder for missing image (Task 2) ✓; image mode persists across ←/→ (Task 3) ✓; esc exits to origin from image mode (Task 4) ✓; space/select unchanged (unchanged code, covered by existing tests) ✓; title `[image]` suffix (Task 3) ✓; footer + help (Tasks 2, 5) ✓; `textual-image[textual]` + Python floor (Task 1) ✓; tests against tmp archives, image generated with Pillow, no network (Tasks 2-4) ✓; README (Task 6) ✓.
- **Placeholder scan:** none — every step has concrete code/commands.
- **Type/name consistency:** `view` ("text"/"image"), `base_title`, ids `#transcription-body` / `#page-image` / `#page-image-missing`, `action_toggle_view`, `_build_body`, `_NO_IMAGE_MESSAGE`, `open_transcription(..., view=...)` are used consistently across tasks.
- **Snapshot regen:** the three affected baselines are called out explicitly (Tasks 2 and 5) — no silent snapshot breakage left for the suite to trip over.
