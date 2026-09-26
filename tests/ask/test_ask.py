# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

import base64

from vtextract.ask import PageContext, build_messages, render_context, transcript_markdown


def _ctx(**kw):
    base = dict(root_id="474234", page_key="474234_Page_003.jpg",
                volume_label="Transcript Book 86", volume_title="Memorials 1737",
                reference_code="IMC 1954/RoD/1/86", ordinal=3, label="3",
                transcription="The humble petition of David Power Gent",
                notes="David Power is Daniel Power.",
                people=[["Daniel Power", "David Power Gent"], ["Constantine Phipps"]])
    base.update(kw)
    return PageContext(**base)


def test_render_context_includes_every_block():
    text = render_context(_ctx())
    for needle in ("Transcript Book 86", "Memorials 1737", "IMC 1954/RoD/1/86",
                   "page 3", "humble petition", "David Power is Daniel Power.",
                   "Daniel Power (David Power Gent)", "Constantine Phipps"):
        assert needle in text


def test_render_context_omits_absent_blocks():
    text = render_context(_ctx(notes=None, people=[], transcription=None))
    assert "NOTES" not in text and "PEOPLE" not in text and "TRANSCRIPTION" not in text


def test_build_messages_first_question_carries_context_and_image():
    msgs = build_messages(_ctx(), history=[], question="Who is the petitioner?",
                          image=b"\xff\xd8jpegbytes")
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    parts = msgs[1]["content"]
    assert parts[0]["type"] == "text" and "humble petition" in parts[0]["text"]
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"] == (
        "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8jpegbytes").decode())
    assert "Who is the petitioner?" in parts[2]["text"]
    assert len(msgs) == 2


def test_build_messages_without_image_is_plain_text():
    msgs = build_messages(_ctx(), history=[], question="Q?", image=None)
    assert isinstance(msgs[1]["content"], str)
    assert "Q?" in msgs[1]["content"]


def test_build_messages_history_alternates_after_context():
    msgs = build_messages(_ctx(), history=[("Q1?", "A1."), ("Q2?", "A2.")],
                          question="Q3?", image=None)
    roles = [m["role"] for m in msgs]
    assert roles == ["system", "user", "assistant", "user", "assistant", "user"]
    assert "humble petition" in msgs[1]["content"] and "Q1?" in msgs[1]["content"]
    assert msgs[2]["content"] == "A1."
    assert msgs[3]["content"].endswith("Q2?") and "humble petition" not in msgs[3]["content"]
    assert msgs[5]["content"].endswith("Q3?")


def test_transcript_markdown():
    md = transcript_markdown("474234_Page_003.jpg", [("Q1?", "A1."), ("Q2?", "A2.")])
    assert md.startswith("# 474234_Page_003.jpg")
    assert "## Q1?\n\nA1.\n" in md and "## Q2?\n\nA2.\n" in md
