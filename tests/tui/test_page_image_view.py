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
        assert "No image on disk" in str(placeholder.content)
        assert len(app.query("#page-image")) == 0


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


@pytest.mark.asyncio
async def test_tall_image_is_not_stretched_to_full_width(tmp_archive):
    # A portrait page scan should keep its aspect ratio: the image widget must
    # be narrower than the pane, not stretched to fill the full width.
    path = tmp_archive / "pages" / "volA" / "volA_p0.jpg"
    PILImage.new("RGB", (100, 400), (60, 60, 200)).save(path, "JPEG")  # 1:4 portrait
    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.open_transcription("volA", "volA_p0.jpg", origin="pages")
        await pilot.pause()
        await pilot.press("enter")          # text -> image
        await pilot.pause()
        img = app.query_one("#page-image")
        screen = _active(app)
        assert img.content_size.height > 0
        assert img.content_size.width < screen.content_size.width


@pytest.mark.asyncio
async def test_image_is_horizontally_centered_in_pane(tmp_archive):
    # A page scan narrower than the pane should sit centered, with roughly
    # equal margins on the left and right rather than hugging the left edge.
    path = tmp_archive / "pages" / "volA" / "volA_p0.jpg"
    PILImage.new("RGB", (100, 400), (60, 60, 200)).save(path, "JPEG")  # 1:4 portrait
    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.open_transcription("volA", "volA_p0.jpg", origin="pages")
        await pilot.pause()
        await pilot.press("enter")          # text -> image
        await pilot.pause()
        img = app.query_one("#page-image")
        screen = _active(app)
        left = img.region.x - screen.content_region.x
        right = screen.content_region.right - img.region.right
        assert left > 0                      # not flush against the left edge
        assert abs(left - right) <= 1        # centered (within rounding)
