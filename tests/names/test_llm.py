# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import json

import pytest

from vtextract.names import llm
from vtextract.names.models import Person


def test_build_messages_contains_text_and_schema():
    msgs = llm.build_messages("Wm Young paid the toll.")
    assert msgs[0]["role"] == "system"
    assert "canonical" in msgs[0]["content"]
    assert "Wm Young paid the toll." in msgs[1]["content"]


def test_parse_people():
    content = json.dumps({"people": [
        {"canonical": "William Young", "confidence": "high",
         "aliases": [{"text": "Wm Young", "confidence": "high"}]}]})
    people = llm._parse(content)
    assert people[0].canonical == "William Young"
    assert people[0].aliases[0].text == "Wm Young"


def test_parse_lenient_strips_prose():
    content = 'Here is the JSON:\n{"people": []}\nThanks!'
    assert llm._parse(content) == []


def test_find_people_uses_completion(monkeypatch):
    captured = {}

    def fake_complete(kwargs, *, max_retries=2):
        captured["model"] = kwargs["model"]
        return json.dumps({"people": [{"canonical": "John Young", "confidence": "medium",
                                       "aliases": [{"text": "Young", "confidence": "low"}]}]})

    monkeypatch.setattr(llm, "_complete", fake_complete)
    people = llm.find_people("text", model="ollama/llama3.1")
    assert captured["model"] == "ollama/llama3.1"
    assert isinstance(people[0], Person)
    assert people[0].canonical == "John Young"


def test_find_people_reprompts_on_bad_json(monkeypatch):
    calls = []

    def fake_complete(kwargs, *, max_retries=2):
        calls.append(kwargs["messages"])
        if len(calls) == 1:
            return "not json at all"
        return json.dumps({"people": []})

    monkeypatch.setattr(llm, "_complete", fake_complete)
    assert llm.find_people("text", model="m") == []
    assert len(calls) == 2  # original + one reprompt


def test_friendly_error_not_found_ollama():
    msg = llm.friendly_error(RuntimeError("model not found, try pulling"), "ollama/llama3.1", None)
    assert "ollama pull" in msg
