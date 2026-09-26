# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

"""End-to-end smoke test for vtbrowse.

Drives the real ``VtBrowseApp`` against the real fixture-built archive,
covering: startup → f search dialog → query submission → real ``vtindex``
subprocess → results screen → space-to-toggle item selection → bundle JSON
round-trip.

The FileDialog interaction (Save) is intentionally bypassed in favour of
writing the bundle directly via ``app.bundle.to_json()`` — the dialog itself
is covered by its own snapshot tests (Task 20). This keeps the e2e test
focused on the interesting code paths rather than fragile key-by-key
DirectoryTree navigation.
"""

from __future__ import annotations

import pytest

from vtextract.tui.app import VtBrowseApp
from vtextract.tui.bundle import Bundle


@pytest.mark.asyncio
async def test_smoke_open_search_select_save(tmp_archive, tmp_path):
    """Drive the real TUI through: open → search → select → save."""

    bundle_path = tmp_path / "smoke_bundle.json"
    app = VtBrowseApp(archive=tmp_archive)

    async with app.run_test() as pilot:
        await pilot.pause()  # let startup settle

        # Defensive: dismiss any startup index prompt. The fixture archive is
        # freshly built so this is usually a no-op, but escape is safe either
        # way (the prompt's "No" path falls through to the no-index screen,
        # which we'd then have to recover from — pressing escape directly on
        # the IndexPromptDialog dismisses it cleanly).
        await pilot.press("escape")
        await pilot.pause()

        # Open the search dialog via the global binding.
        await pilot.press("f")
        await pilot.pause()

        # The dialog's first focusable widget is the query Input. Type a
        # known fixture keyword and submit.
        for ch in "houston":
            await pilot.press(ch)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        # The search ran the real ``vtindex search`` subprocess and mounted
        # the ResultsScreen. The cursor lands on row 0 by default; toggle
        # the first item into the bundle.
        await pilot.press("space")
        await pilot.pause()

        assert app.bundle.selected_items, \
            "expected at least one item selected after space toggle"

        # Write the bundle to disk directly, bypassing the FileDialog (which
        # is covered by its own snapshot tests). This still exercises the
        # real ``Bundle.to_json`` serialization path.
        bundle_path.write_text(app.bundle.to_json())

    # After the app exits, verify the saved bundle round-trips.
    assert bundle_path.exists()
    restored = Bundle.from_json(bundle_path.read_text())
    assert restored.selected_items, \
        "round-tripped bundle should preserve selections"
