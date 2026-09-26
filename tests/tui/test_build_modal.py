# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT


def test_build_modal_renders(snap_compare, tmp_archive):
    """Pressing b opens ProgressModal; renders mid-progress + done counters."""
    from vtextract.tui.app import VtBrowseApp
    from vtextract.tui.dialogs.build import ProgressModal
    from vtextract.tui.progress_events import (
        DoneEvent, ProgressUpdate, StartEvent,
    )

    class _DeterministicApp(VtBrowseApp):
        def action_build_index(self):
            async def stub():
                yield StartEvent(tool="vtindex build", argv=[])
                yield ProgressUpdate(
                    phase="indexing", current=42, total=100,
                    counters={"added": 10, "updated": 2},
                )
                yield DoneEvent(
                    elapsed_seconds=2.3,
                    counters={"added": 12, "updated": 2, "unchanged": 88,
                              "skipped": 0, "removed": 0},
                )
            self.push_screen(ProgressModal(
                title="vtindex build", stream_factory=stub,
            ))

    async def before(pilot):
        await pilot.pause()
        await pilot.press("b")
        await pilot.pause()
    assert snap_compare(_DeterministicApp(archive=tmp_archive),
                        run_before=before)


def test_build_modal_failure(snap_compare, tmp_archive):
    """ProgressModal shows the ErrorEvent and swaps Cancel→Close."""
    from vtextract.tui.app import VtBrowseApp
    from vtextract.tui.dialogs.build import ProgressModal
    from vtextract.tui.progress_events import (
        ErrorEvent, ProgressUpdate, StartEvent,
    )

    class _DeterministicApp(VtBrowseApp):
        def action_build_index(self):
            async def stub():
                yield StartEvent(tool="vtindex build", argv=[])
                yield ProgressUpdate(
                    phase="indexing", current=7, total=100,
                    counters={"added": 1},
                )
                yield ErrorEvent(message="vtindex crashed", exit_code=2)
            self.push_screen(ProgressModal(
                title="vtindex build", stream_factory=stub,
            ))

    async def before(pilot):
        await pilot.pause()
        await pilot.press("b")
        await pilot.pause()
    assert snap_compare(_DeterministicApp(archive=tmp_archive),
                        run_before=before)
