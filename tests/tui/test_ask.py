# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""The Ask viewer: question a page with the LLM, see Q&A, save, cycle views."""

from __future__ import annotations

import pytest
from PIL import Image as PILImage
from textual.widgets import Markdown

from vtextract.tui.app import VtBrowseApp
from vtextract.tui.dialogs.ask import AskDialog
from vtextract.tui.dialogs.file import FileDialog


class _FakeAsk:
    def __init__(self, answer="Daniel Power is the petitioner.", error=None):
        self.calls: list[dict] = []
        self.answer = answer
        self.error = error

    def __call__(self, messages, model, api_base=None):
        self.calls.append({"messages": messages, "model": model, "api_base": api_base})
        if self.error:
            raise self.error
        return self.answer


def _app(archive, fake):
    app = VtBrowseApp(archive=archive)
    app.ask_fn = fake
    app.ask_model = "test/model"
    return app


async def _open_page(app, pilot, page_key="volA_p0.jpg"):
    await pilot.pause()
    app.open_transcription("volA", page_key, origin="pages")
    await pilot.pause()


async def _ask(pilot, question):
    await pilot.press("a")
    await pilot.pause()
    assert isinstance(pilot.app.screen, AskDialog)
    for ch in question:
        await pilot.press(ch)
    await pilot.press("enter")
    await pilot.pause()
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


def _first_user_text(messages):
    content = messages[1]["content"]
    if isinstance(content, str):
        return content
    return "\n".join(p["text"] for p in content if p["type"] == "text")


@pytest.mark.asyncio
async def test_a_asks_and_shows_question_and_answer(tmp_archive):
    (tmp_archive / "pages/volA/volA_p0.jpg.notes.md").write_text("Power is Daniel.")
    fake = _FakeAsk()
    app = _app(tmp_archive, fake)
    async with app.run_test() as pilot:
        await _open_page(app, pilot)
        await _ask(pilot, "Who is the petitioner?")
        body = app.query_one("#ask-body", Markdown)
        assert "Who is the petitioner?" in body.source
        assert "Daniel Power is the petitioner." in body.source
        assert len(app.query("#transcription-body")) == 0
        assert app.query_one("DocumentPane").border_title.endswith("[ask]")
    call = fake.calls[0]
    assert call["model"] == "test/model"
    first = _first_user_text(call["messages"])
    assert "Power is Daniel." in first                   # notes
    assert "Registry of Deeds Transcript Book 86" in first  # volume.json label
    assert "QUESTION: Who is the petitioner?" in first
    assert isinstance(call["messages"][1]["content"], str)  # no image on disk


@pytest.mark.asyncio
async def test_image_is_attached_when_on_disk(tmp_archive):
    PILImage.new("RGB", (4, 4)).save(tmp_archive / "pages/volA/volA_p0.jpg", "JPEG")
    fake = _FakeAsk()
    app = _app(tmp_archive, fake)
    async with app.run_test() as pilot:
        await _open_page(app, pilot)
        await _ask(pilot, "What?")
    parts = fake.calls[0]["messages"][1]["content"]
    assert any(p["type"] == "image_url" for p in parts)


@pytest.mark.asyncio
async def test_second_question_appends_and_sends_history(tmp_archive):
    fake = _FakeAsk()
    app = _app(tmp_archive, fake)
    async with app.run_test() as pilot:
        await _open_page(app, pilot)
        await _ask(pilot, "Q1?")
        fake.answer = "A2."
        await _ask(pilot, "Q2?")
        src = app.query_one("#ask-body", Markdown).source
        assert src.index("Q1?") < src.index("Q2?") < src.index("A2.")
    roles = [m["role"] for m in fake.calls[1]["messages"]]
    assert roles == ["system", "user", "assistant", "user"]


@pytest.mark.asyncio
async def test_enter_cycles_text_image_ask(tmp_archive):
    app = _app(tmp_archive, _FakeAsk())
    async with app.run_test() as pilot:
        await _open_page(app, pilot)
        await pilot.press("enter")   # text -> image
        await pilot.pause()
        await pilot.press("enter")   # image -> text (no transcript yet)
        await pilot.pause()
        assert len(app.query("#transcription-body")) == 1
        await _ask(pilot, "Q?")      # -> ask view
        assert len(app.query("#ask-body")) == 1
        await pilot.press("enter")   # ask -> text
        await pilot.pause()
        assert len(app.query("#transcription-body")) == 1
        await pilot.press("enter")   # text -> image
        await pilot.pause()
        await pilot.press("enter")   # image -> ask (transcript exists now)
        await pilot.pause()
        assert len(app.query("#ask-body")) == 1


@pytest.mark.asyncio
async def test_w_saves_transcript_as_markdown(tmp_archive):
    app = _app(tmp_archive, _FakeAsk(answer="A1."))
    async with app.run_test() as pilot:
        await _open_page(app, pilot)
        await _ask(pilot, "Q1?")
        await pilot.press("w")
        await pilot.pause()
        assert isinstance(app.screen, FileDialog)
        await pilot.click("#submit")
        await pilot.pause()
    out = tmp_archive / "pages/volA/volA_p0.jpg.ask.md"
    assert out.read_text() == "# volA_p0.jpg\n\n## Q1?\n\nA1.\n"


@pytest.mark.asyncio
async def test_transcript_survives_paging_and_clears_on_back(tmp_archive):
    app = _app(tmp_archive, _FakeAsk())
    async with app.run_test() as pilot:
        await _open_page(app, pilot)
        await _ask(pilot, "Q1?")
        await pilot.press("enter")   # back to text so arrows work as usual
        await pilot.pause()
        await pilot.press("right")   # p0 -> p1
        await pilot.pause()
        await pilot.press("left")    # p1 -> p0
        await pilot.pause()
        await pilot.press("enter")   # text -> image
        await pilot.pause()
        await pilot.press("enter")   # image -> ask: transcript kept
        await pilot.pause()
        assert "Q1?" in app.query_one("#ask-body", Markdown).source
        await pilot.press("escape")  # close the document
        await pilot.pause()
        app.open_transcription("volA", "volA_p0.jpg", origin="pages")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("enter")   # image -> text: no ask view any more
        await pilot.pause()
        assert len(app.query("#transcription-body")) == 1


@pytest.mark.asyncio
async def test_llm_error_is_shown_in_transcript(tmp_archive):
    app = _app(tmp_archive, _FakeAsk(error=RuntimeError("boom")))
    async with app.run_test() as pilot:
        await _open_page(app, pilot)
        await _ask(pilot, "Q?")
        src = app.query_one("#ask-body", Markdown).source
        assert "Q?" in src and "boom" in src
