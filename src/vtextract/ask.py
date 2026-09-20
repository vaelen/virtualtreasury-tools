# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""Prompt assembly for the vtbrowse Ask feature. Pure: no I/O, no LLM calls.

The LLM call itself goes through ``vtextract.names.llm.ask`` (the single
LiteLLM boundary); the TUI gathers the page's files into a ``PageContext``.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field

SYSTEM_PROMPT = """\
You are a research assistant helping a historian read one page of a scanned
manuscript volume from the Virtual Record Treasury of Ireland. The user's first
message gives everything known about the page: the volume it belongs to, the
transcription (which may contain HTML and transcription errors), the user's own
NOTES (authoritative corrections -- trust them over the transcription and the
extracted PEOPLE list), a PEOPLE list extracted by another model, and the page
image when available. Answer the user's questions about this page concisely,
in Markdown. Quote the transcription where it helps. If the page does not
contain the answer, say so rather than guessing.
"""


@dataclass
class PageContext:
    root_id: str
    page_key: str
    volume_label: str | None = None
    volume_title: str | None = None
    reference_code: str | None = None
    ordinal: int | None = None
    label: str | None = None
    transcription: str | None = None
    notes: str | None = None
    people: list[list[str]] = field(default_factory=list)


def render_context(ctx: PageContext) -> str:
    lines = ["VOLUME:"]
    for name, val in (("label", ctx.volume_label), ("title", ctx.volume_title),
                      ("reference code", ctx.reference_code), ("id", ctx.root_id)):
        if val:
            lines.append(f"- {name}: {val}")
    page = f"page {ctx.ordinal}" if ctx.ordinal is not None else "page"
    if ctx.label and ctx.label != str(ctx.ordinal):
        page += f" (labelled {ctx.label})"
    lines.append(f"\nPAGE: {page}, file {ctx.page_key}")
    if ctx.transcription:
        lines.append(f'\nTRANSCRIPTION:\n"""\n{ctx.transcription.strip()}\n"""')
    if ctx.notes and ctx.notes.strip():
        lines.append(f'\nNOTES (from the user, authoritative):\n"""\n{ctx.notes.strip()}\n"""')
    if ctx.people:
        lines.append("\nPEOPLE (extracted by another model; canonical name, then as written):")
        for forms in ctx.people:
            written = ", ".join(forms[1:])
            lines.append(f"- {forms[0]}" + (f" ({written})" if written else ""))
    return "\n".join(lines)


def _q(question: str) -> str:
    return f"QUESTION: {question.strip()}"


def build_messages(ctx: PageContext, *, history: list[tuple[str, str]],
                   question: str, image: bytes | None) -> list[dict]:
    """System prompt, then the page context + image riding with the first
    question (from history if any), then alternating Q/A, then ``question``."""
    turns = [*history, (question, None)]
    first_q = turns[0][0]
    context_text = render_context(ctx)
    if image is not None:
        data = base64.b64encode(image).decode()
        first: object = [
            {"type": "text", "text": context_text},
            {"type": "image_url",
             "image_url": {"url": f"data:image/jpeg;base64,{data}"}},
            {"type": "text", "text": _q(first_q)},
        ]
    else:
        first = f"{context_text}\n\n{_q(first_q)}"
    msgs: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": first}]
    for i, (q, a) in enumerate(turns):
        if i > 0:
            msgs.append({"role": "user", "content": _q(q)})
        if a is not None:
            msgs.append({"role": "assistant", "content": a})
    return msgs


def transcript_markdown(page_key: str, history: list[tuple[str, str]]) -> str:
    out = [f"# {page_key}\n"]
    for q, a in history:
        out.append(f"## {q.strip()}\n\n{a.strip()}\n")
    return "\n".join(out)
