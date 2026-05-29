# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""Snapshot tests for Bundle-pane keyboard handling (Task 25).

⏎ on a page leaf jumps the document pane to that page's transcription.
space on a leaf (or volume header) removes the page (or all the volume's
pages) from the bundle.
"""


def _seed_bundle(app) -> None:
    """Pre-populate the bundle with two pages on volA and one on volB."""
    from vtextract.tui.bundle import PageRef

    app.bundle.selected_items[100] = [
        PageRef("volA", "volA_p0.jpg"),
        PageRef("volA", "volA_p1.jpg"),
    ]
    app.bundle.selected_items[200] = [
        PageRef("volB", "volB_p5.jpg"),
    ]


def test_bundle_pane_enter_jumps_to_page(snap_compare, tmp_archive):
    """Tab → Bundle pane, walk to a leaf, press ⏎ → transcription view."""
    from pathlib import Path

    from vtextract.tui.app import VtBrowseApp

    class _SeededApp(VtBrowseApp):
        def __init__(self, *, archive: Path) -> None:
            super().__init__(archive=archive)
            _seed_bundle(self)

    async def before(pilot):
        await pilot.pause()
        await pilot.press("tab")        # focus Bundle pane
        await pilot.pause()
        await pilot.press("down")       # first volume header → first leaf
        await pilot.pause()
        await pilot.press("down")       # advance to the first page leaf
        await pilot.pause()
        await pilot.press("enter")      # jump to that page's transcription
        await pilot.pause()
    assert snap_compare(_SeededApp(archive=tmp_archive), run_before=before)


def test_bundle_pane_space_removes_page(snap_compare, tmp_archive):
    """Tab → Bundle pane, walk to a leaf, press space → page removed."""
    from pathlib import Path

    from vtextract.tui.app import VtBrowseApp

    class _SeededApp(VtBrowseApp):
        def __init__(self, *, archive: Path) -> None:
            super().__init__(archive=archive)
            _seed_bundle(self)

    async def before(pilot):
        await pilot.pause()
        await pilot.press("tab")        # focus Bundle pane
        await pilot.pause()
        await pilot.press("down")       # first volume header → first leaf
        await pilot.pause()
        await pilot.press("down")       # first page leaf
        await pilot.pause()
        await pilot.press("space")      # remove this page from the bundle
        await pilot.pause()
    assert snap_compare(_SeededApp(archive=tmp_archive), run_before=before)
