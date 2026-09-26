# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

import pytest
from textual.app import App

from vtextract.index.models import PageEntry
from vtextract.tui.bundle import Bundle, PageRef
from vtextract.tui.screens.pages import PagesScreen


class _FakeIndex:
    def __init__(self, pages):
        self._pages = pages

    async def pages(self, _root_id):
        return self._pages


class _PagesHarness(App):
    def __init__(self, pages, bundle, root_id="V"):
        super().__init__()
        self._index = _FakeIndex(pages)
        self._bundle = bundle
        self._root_id = root_id
        self.bundle_changed_calls = 0

    def compose(self):
        yield PagesScreen(index=self._index, bundle=self._bundle,
                          root_id=self._root_id)

    def set_pane_count(self, _text):  # satisfies CountFooterMixin
        pass

    def bundle_changed(self):
        self.bundle_changed_calls += 1


_PAGES = [
    PageEntry(root_id="V", page_key="p1", ordinal=1, transcription="text", image="img",
              names="names", notes="notes"),
    PageEntry(root_id="V", page_key="p2", ordinal=2, transcription=None, image="img"),
]
SEL = 6  # column index of the bundle-selection marker


@pytest.mark.asyncio
async def test_pages_show_names_and_notes_columns():
    harness = _PagesHarness(_PAGES, Bundle())
    async with harness.run_test() as pilot:
        table = pilot.app.query_one(PagesScreen)
        assert [str(c.label) for c in table.columns.values()] == \
            ["#", "Page key", "Txt", "Img", "Names", "Notes", "Sel"]
        assert list(table.get_row_at(0)) == ["1", "p1", "•", "•", "•", "•", ""]
        assert list(table.get_row_at(1)) == ["2", "p2", "", "•", "", "", ""]


@pytest.mark.asyncio
async def test_pages_a_selects_all_then_deselects_all():
    bundle = Bundle()
    harness = _PagesHarness(_PAGES, bundle)
    async with harness.run_test() as pilot:
        await pilot.press("a")  # none -> select all
        assert bundle.is_in_bundle(PageRef("V", "p1"))
        assert bundle.is_in_bundle(PageRef("V", "p2"))
        table = pilot.app.query_one(PagesScreen)
        assert table.get_row_at(0)[SEL] == "*"
        assert table.get_row_at(1)[SEL] == "*"

        await pilot.press("a")  # all -> deselect all
        assert not bundle.is_in_bundle(PageRef("V", "p1"))
        assert not bundle.is_in_bundle(PageRef("V", "p2"))
        assert table.get_row_at(0)[SEL] == ""
        assert table.get_row_at(1)[SEL] == ""
        assert harness.bundle_changed_calls == 2


@pytest.mark.asyncio
async def test_pages_a_treats_item_included_page_as_selected():
    # A page implicitly in the bundle via a selected item counts as selected,
    # so a partial state selects the rest (does not deselect).
    bundle = Bundle(selected_items={9: [PageRef("V", "p1")]})
    harness = _PagesHarness(_PAGES, bundle)
    async with harness.run_test() as pilot:
        await pilot.press("a")  # p1 already in via item -> select all the rest
        assert bundle.is_in_bundle(PageRef("V", "p1"))
        assert bundle.is_in_bundle(PageRef("V", "p2"))


@pytest.mark.asyncio
async def test_pages_a_on_empty_is_noop():
    bundle = Bundle()
    harness = _PagesHarness([], bundle)
    async with harness.run_test() as pilot:
        await pilot.press("a")
        assert bundle.page_state == {}
        assert harness.bundle_changed_calls == 0


def test_pages_screen_after_enter_on_volume(snap_compare, tmp_archive):
    from vtextract.tui.app import VtBrowseApp

    async def before(pilot):
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
    assert snap_compare(VtBrowseApp(archive=tmp_archive), run_before=before)
