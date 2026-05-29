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
