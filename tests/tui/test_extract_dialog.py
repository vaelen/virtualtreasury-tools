# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved


def test_extract_dialog_form_renders(snap_compare, tmp_archive):
    """Pressing e opens the Extract dialog; the empty form renders."""
    from vtextract.tui.app import VtBrowseApp

    async def before(pilot):
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
    assert snap_compare(VtBrowseApp(archive=tmp_archive), run_before=before)


def test_extract_dialog_with_preview(snap_compare, tmp_archive):
    """Typing keywords updates the live ``Will run:`` preview."""
    from vtextract.tui.app import VtBrowseApp

    async def before(pilot):
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        # Focus the keywords input and type.
        for ch in "smith":
            await pilot.press(ch)
        await pilot.pause()
    assert snap_compare(VtBrowseApp(archive=tmp_archive), run_before=before)


def test_extract_progress_modal_renders(snap_compare, tmp_archive):
    """Chained vtextract search → vtindex build progress modal renders."""
    from vtextract.tui.app import VtBrowseApp
    from vtextract.tui.dialogs.build import ProgressModal
    from vtextract.tui.progress_events import (
        DoneEvent, LogEvent, ProgressUpdate, StartEvent,
    )

    class _DeterministicApp(VtBrowseApp):
        def action_extract(self):
            async def stub():
                # Step 1: vtextract search
                yield StartEvent(
                    tool="vtextract search",
                    argv=["--all", "smith"],
                )
                yield ProgressUpdate(
                    phase="search", current=3, total=5,
                    counters={"items": 3, "pages": 8},
                )
                yield DoneEvent(
                    elapsed_seconds=1.4,
                    counters={"items": 5, "pages": 12},
                )
                # Step 2: vtindex build
                yield StartEvent(tool="vtindex build", argv=[])
                yield LogEvent(message="Step 2: indexing new items")
                yield ProgressUpdate(
                    phase="indexing", current=4, total=12,
                    counters={"added": 4},
                )
            self.push_screen(ProgressModal(
                title="vtextract search → vtindex build",
                stream_factory=stub,
            ))

    async def before(pilot):
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
    assert snap_compare(_DeterministicApp(archive=tmp_archive),
                        run_before=before)
