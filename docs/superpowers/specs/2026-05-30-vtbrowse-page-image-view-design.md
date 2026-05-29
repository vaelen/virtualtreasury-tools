# vtbrowse: page image view (transcription ⇄ image toggle)

**Date:** 2026-05-30
**Status:** Approved design

## Goal

In the `vtbrowse` TUI, let the user view the scanned page image for the page
they're reading. While viewing a transcription, pressing `enter` swaps to an
image view of the same page; pressing `enter` again swaps back. `esc` continues
to exit to wherever the view was opened from (search results or the page list).

## Context

- Page images are stored at `archive/pages/{rootID}/{page_key}`, where
  `page_key` keeps its image extension (e.g. `foo.jpg`); the transcription
  lives alongside as `foo.jpg.txt`. (See `index/builder.py` — "strip `.txt`;
  page_key keeps `.jpg`".)
- `ArchiveReader` already exposes `image_path(root_id, page_key)` and
  `image_exists(root_id, page_key)`, so the image bytes are reachable directly
  from the TUI layer. This does **not** cross the `tui/` architectural boundary
  (direct archive-file reads are allowed; only the SQLite index is off-limits).
- `TranscriptionScreen` currently binds `left`/`right` (prev/next page),
  `space` (select), `esc` (back to origin). `enter` is free.
- Screens are mounted into the `DocumentPane` content area via
  `app._mount_screen()`; the active screen's `selected_context()` feeds the
  info pane.

## Rendering library

Use **`textual-image[textual]>=0.11,<0.13`** — a purpose-built Textual `Image`
widget that renders via terminal graphics protocols (Kitty / iTerm2 / Sixel)
with automatic fallback to Unicode half-blocks on terminals without protocol
support. Chosen over `rich-pixels` (half-blocks only) because manuscript scans
need the protocol-level fidelity to be legible.

> **Version pin:** the `0.13.x` wheels are broken (they ship no Python
> modules — `import textual_image.widget` fails), so the dependency is pinned
> `<0.13`; `0.12.0` is the working release. Revisit when a fixed `0.13.x`/later
> wheel is published.

Cost, accepted: `textual-image` requires **Python ≥3.12** and pulls in
**Pillow** transitively. The project's `requires-python` is therefore bumped
from `>=3.11` to `>=3.12`. Installed Textual (8.2.7) already satisfies
`textual-image`'s `textual>=0.68` floor.

## Structural approach — in-screen mode toggle

Keep everything inside `TranscriptionScreen`; do **not** add a new app-level
screen. The class name is retained (it is referenced by `app.py` and several
tests); its purpose is now "one page, viewable as text or image," which is
still a single coherent responsibility.

The screen gains a `view` mode (`"text"` | `"image"`, default `"text"`) and a
single body widget identified by `#page-body`, swapped on toggle. The existing
prev/next/select/escape bindings and `selected_context()` are reused unchanged,
so the info pane stays consistent regardless of mode.

## Behavior

- **`enter` → `action_toggle_view`**: flips `text ⇄ image` and rebuilds
  `#page-body`.
- **Image body construction**:
  - if `reader.image_exists(root_id, page_key)` → a
    `textual_image.widget.Image(reader.image_path(root_id, page_key))`;
  - else → a `Static` placeholder reading
    *"No image on disk for this page — re-run vtextract with --images to
    download it."*
- **Text body**: unchanged from today — the highlighted transcription `Static`.
- **prev/next preserve mode**: `app.open_transcription()` and
  `TranscriptionScreen.__init__` gain a `view: str = "text"` parameter;
  `action_prev_page` / `action_next_page` pass `view=self.view`. So `←`/`→` in
  image mode flips through adjacent page *images* without dropping back to
  text.
- **space (select)** and **esc (back to origin)**: unchanged; identical in both
  modes.
- **Title hint**: while in image mode the pane title gets a ` [image]` suffix,
  applied via `self.app.set_pane_title(...)`.
- **Footer + help**: add the `enter` binding (label e.g. `image / text`) and a
  corresponding line in `dialogs/help.py`.

## Testing (TDD, against tmp archives — no network)

The image *pixels* are never snapshot-tested (graphics output is
terminal-dependent and non-deterministic). Behavior is tested via
`app.run_test()` pilot interactions:

1. **toggle**: body starts as the transcription `Static`; `enter` → `#page-body`
   is an `Image` whose source is `reader.image_path(...)`; `enter` again → back
   to the `Static`.
2. **missing image**: with no image on disk, `enter` mounts the placeholder
   `Static` (assert its text), not an `Image`.
3. **mode persists across paging**: in image mode, `right` → the next page's
   screen is also in image mode.
4. **escape from image mode** → returns to origin (results / pages).
5. The image-present test generates a tiny 1×1 image into the tmp archive using
   Pillow (now a dependency) — no committed binary fixture, no network.
6. A deterministic snapshot of the **placeholder** view may be added.

## Out of scope

- Side-by-side split view (explicitly rejected — fights the single-pane
  layout).
- Image zoom/pan, rotation, or multi-page contact-sheet views.
- Downloading images on demand from within the TUI (the placeholder directs the
  user to re-run `vtextract --images`).
