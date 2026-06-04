# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import json

import httpx
import litellm
import pytest

from vtextract.names import llm
from vtextract.names.models import Person


def _rate_limit_error(retry_after: str | None = None) -> litellm.RateLimitError:
    resp = None
    if retry_after is not None:
        resp = httpx.Response(429, headers={"retry-after": retry_after})
    return litellm.RateLimitError(
        message="rate limit exceeded", llm_provider="anthropic",
        model="claude-haiku-4-5", response=resp)


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


def _ok_response():
    return {"choices": [{"message": {"content": '{"people": []}'}}]}


def test_complete_retries_rate_limit_then_succeeds(monkeypatch):
    calls = []
    sleeps = []
    monkeypatch.setattr(llm.time, "sleep", lambda s: sleeps.append(s))

    def fake_completion(**kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise _rate_limit_error()
        return _ok_response()

    monkeypatch.setattr(llm.litellm, "completion", fake_completion)
    assert llm._complete({"model": "m", "messages": []}) == '{"people": []}'
    assert len(calls) == 2
    assert sleeps  # slept before retrying


def test_complete_rate_limit_backoff_is_longer_than_transport(monkeypatch):
    sleeps = []
    monkeypatch.setattr(llm.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(llm.litellm, "completion",
                        lambda **kw: (_ for _ in ()).throw(_rate_limit_error()))

    with pytest.raises(litellm.RateLimitError):
        llm._complete({"model": "m", "messages": []})
    # rate-limit waits start well above the 1s transport backoff
    assert sleeps[0] >= llm._RATE_LIMIT_BASE_DELAY
    assert len(sleeps) == llm._RATE_LIMIT_RETRIES


def test_complete_honors_retry_after_header(monkeypatch):
    sleeps = []
    monkeypatch.setattr(llm.time, "sleep", lambda s: sleeps.append(s))
    calls = []

    def fake_completion(**kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise _rate_limit_error(retry_after="30")
        return _ok_response()

    monkeypatch.setattr(llm.litellm, "completion", fake_completion)
    llm._complete({"model": "m", "messages": []})
    assert sleeps == [30.0]


def test_complete_message_only_rate_limit_is_detected(monkeypatch):
    """A provider that raises a plain Exception still gets the long backoff."""
    sleeps = []
    monkeypatch.setattr(llm.time, "sleep", lambda s: sleeps.append(s))
    calls = []

    def fake_completion(**kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("This request would exceed your rate limit of ...")
        return _ok_response()

    monkeypatch.setattr(llm.litellm, "completion", fake_completion)
    llm._complete({"model": "m", "messages": []})
    assert sleeps and sleeps[0] >= llm._RATE_LIMIT_BASE_DELAY


def test_complete_transport_error_keeps_short_backoff(monkeypatch):
    sleeps = []
    monkeypatch.setattr(llm.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(llm.litellm, "completion",
                        lambda **kw: (_ for _ in ()).throw(RuntimeError("connection refused")))

    with pytest.raises(RuntimeError):
        llm._complete({"model": "m", "messages": []})
    assert sleeps == [1, 2]  # unchanged transport backoff (2**0, 2**1)


def test_friendly_error_rate_limit():
    msg = llm.friendly_error(_rate_limit_error(), "anthropic/claude-haiku-4-5", None)
    assert "rate limit" in msg.lower()


def test_unload_noop_for_non_ollama(monkeypatch):
    calls = []
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: calls.append((a, k)))
    llm.unload("openai/gpt-4.1")
    assert calls == []   # remote models are not locally loaded


def test_unload_posts_keep_alive_zero_to_ollama(monkeypatch):
    seen = {}
    def fake_post(url, json=None, timeout=None):
        seen["url"] = url
        seen["json"] = json
        return None
    monkeypatch.setattr(llm.httpx, "post", fake_post)
    llm.unload("ollama/qwen2.5:7b", "http://localhost:11434")
    assert seen["url"] == "http://localhost:11434/api/generate"
    assert seen["json"] == {"model": "qwen2.5:7b", "keep_alive": 0}  # prefix dropped


def test_unload_defaults_base_and_swallows_errors(monkeypatch):
    seen = {}
    def fake_post(url, json=None, timeout=None):
        seen["url"] = url
        raise RuntimeError("ollama down")
    monkeypatch.setattr(llm.httpx, "post", fake_post)
    llm.unload("ollama/x")   # no api_base -> default localhost; must not raise
    assert seen["url"] == "http://localhost:11434/api/generate"
