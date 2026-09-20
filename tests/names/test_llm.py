# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import json

import httpx
import litellm
import pytest
from pydantic import ValidationError

from vtextract.names import llm
from vtextract.names.llm import (
    TruncatedResponseError,
    error_class,
    is_persistent_failure,
    truncation_finish_reason,
)
from vtextract.names.models import NameResponse, Person, Usage


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
    content = json.dumps({"people": [["William Young", "Wm Young"]]})
    people = llm._parse(content)
    assert people[0].canonical == "William Young"
    assert people[0].aliases == ["Wm Young"]


def test_system_prompt_uses_compact_list_form_without_confidence():
    sp = llm.SYSTEM_PROMPT
    assert "confidence" not in sp.lower()         # confidence is gone entirely
    assert '["Thomas Young","Sgt. Young"]' in sp  # worked example is array form


def test_parse_lenient_strips_prose():
    content = 'Here is the JSON:\n{"people": []}\nThanks!'
    assert llm._parse(content) == []


def test_find_people_uses_completion(monkeypatch):
    captured = {}

    def fake_complete(kwargs, *, max_retries=2):
        captured["model"] = kwargs["model"]
        content = json.dumps({"people": [["John Young", "Young"]]})
        return content, Usage(input=100, output=20, cached=0)

    monkeypatch.setattr(llm, "_complete", fake_complete)
    people, usage = llm.find_people("text", model="ollama/llama3.1")
    assert captured["model"] == "ollama/llama3.1"
    assert isinstance(people[0], Person)
    assert people[0].canonical == "John Young"
    assert usage == Usage(input=100, output=20, cached=0)


def test_find_people_reprompts_on_bad_json_and_sums_usage(monkeypatch):
    calls = []

    def fake_complete(kwargs, *, max_retries=2):
        calls.append(kwargs["messages"])
        if len(calls) == 1:
            return "not json at all", Usage(input=100, output=5)
        return json.dumps({"people": []}), Usage(input=120, output=2)

    monkeypatch.setattr(llm, "_complete", fake_complete)
    people, usage = llm.find_people("text", model="m")
    assert people == []
    assert len(calls) == 2  # original + one reprompt
    # the repair call's tokens are billed too, so usage sums both calls
    assert usage == Usage(input=220, output=7)


def test_complete_raises_truncated_error_with_usage(monkeypatch):
    # finish_reason == "length" means the provider cut the output off at its
    # token cap; the JSON is incomplete. _complete must surface this as a typed
    # error (not hand the broken JSON downstream) and carry the attempt's usage
    # so the caller can still bill the wasted tokens.
    monkeypatch.setattr(llm.litellm, "completion", lambda **kw: {
        "choices": [{"finish_reason": "length",
                     "message": {"content": '{"people": [{"canonical": "A"'}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 8000}})
    with pytest.raises(llm.TruncatedResponseError) as ei:
        llm._complete({"model": "m", "messages": []})
    assert ei.value.usage == Usage(input=5, output=8000)


def test_complete_truncation_is_not_retried(monkeypatch):
    # A length-capped response is deterministic; retrying it as a transport blip
    # would just burn another huge call. It must raise on the first occurrence.
    calls = []
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)

    def fake_completion(**kwargs):
        calls.append(1)
        return {"choices": [{"finish_reason": "length",
                             "message": {"content": "{"}}]}

    monkeypatch.setattr(llm.litellm, "completion", fake_completion)
    with pytest.raises(llm.TruncatedResponseError):
        llm._complete({"model": "m", "messages": []})
    assert len(calls) == 1  # not retried


def test_complete_truncation_detection_can_be_disabled(monkeypatch):
    # The check_model preflight sends max_tokens=1, so finish_reason is always
    # "length"; hitting a deliberate tiny cap is not a failure. detect_truncation
    # is what controls this -- NOT the mere presence of max_tokens, because the
    # extraction guardrail also sets max_tokens yet hitting it IS a loop.
    monkeypatch.setattr(llm.litellm, "completion", lambda **kw: {
        "choices": [{"finish_reason": "length", "message": {"content": "x"}}]})
    content, _usage = llm._complete(
        {"model": "m", "messages": [], "max_tokens": 1}, detect_truncation=False)
    assert content == "x"


def test_complete_detects_truncation_even_with_max_tokens_guardrail(monkeypatch):
    # Hitting an extraction guardrail (max_tokens=12000) still means the output
    # was cut off -- it must be flagged, not silently parsed.
    monkeypatch.setattr(llm.litellm, "completion", lambda **kw: {
        "choices": [{"finish_reason": "length", "message": {"content": "{"}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 12000}})
    with pytest.raises(llm.TruncatedResponseError):
        llm._complete({"model": "m", "messages": [], "max_tokens": 12000})


def test_complete_raises_empty_response_error_on_none_content(monkeypatch):
    # Gemini flags dense, list-like text (e.g. a name index) for recitation /
    # safety and returns a completion whose message.content is None with a
    # finish_reason that is NOT a truncation reason. _complete must surface this
    # as a typed EmptyResponseError carrying usage -- not return None and let
    # _parse blow up downstream with 'NoneType' object has no attribute 'strip'.
    monkeypatch.setattr(llm.litellm, "completion", lambda **kw: {
        "choices": [{"finish_reason": "content_filter",
                     "message": {"content": None}}],
        "usage": {"prompt_tokens": 7, "completion_tokens": 0}})
    with pytest.raises(llm.EmptyResponseError) as ei:
        llm._complete({"model": "gemini/gemini-2.5-flash-lite", "messages": []})
    assert ei.value.usage == Usage(input=7, output=0)


def test_find_people_surfaces_empty_response_not_attribute_error(monkeypatch):
    # The end-to-end symptom: a None-content completion used to crash in
    # _loads_lenient with the cryptic AttributeError. find_people must instead
    # raise the typed, classifiable EmptyResponseError.
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    monkeypatch.setattr(llm.litellm, "completion", lambda **kw: {
        "choices": [{"finish_reason": "content_filter",
                     "message": {"content": None}}]})
    with pytest.raises(llm.EmptyResponseError):
        llm.find_people("a page of names", "gemini/gemini-2.5-flash-lite")


def test_check_model_does_not_flag_truncation_as_failure(monkeypatch):
    # Preflight caps output at 1 token -> finish_reason "length" always. This must
    # not be reported as a model failure (it would reject every working model).
    monkeypatch.setattr(llm.litellm, "completion", lambda **kw: {
        "choices": [{"finish_reason": "length", "message": {"content": "p"}}]})
    assert llm.check_model("gemini/gemini-2.5-flash-lite") is None


def test_find_people_forwards_max_output_tokens_as_cap(monkeypatch):
    seen = []

    def fake_complete(kwargs, **_):
        seen.append(kwargs.get("max_tokens"))
        return json.dumps({"people": []}), Usage(input=5, output=3)

    monkeypatch.setattr(llm, "_complete", fake_complete)
    llm.find_people("text", model="m", max_output_tokens=12000)
    assert seen == [12000]  # the output cap is sent to the provider


def test_find_people_caps_both_pass_and_retry_on_truncation(monkeypatch):
    seen = []

    def fake_complete(kwargs, **_):
        seen.append(kwargs.get("max_tokens"))
        if len(seen) == 1:
            raise llm.TruncatedResponseError("response truncated",
                                             usage=Usage(input=5, output=12000))
        return json.dumps({"people": []}), Usage(input=5, output=3)

    monkeypatch.setattr(llm, "_complete", fake_complete)
    llm.find_people("repetitive", model="m", max_output_tokens=12000)
    assert seen == [12000, 12000]  # cap applied on the loop-breaking retry too


def test_find_people_retries_at_higher_temperature_on_truncation(monkeypatch):
    # The real cause of the will-index failures: temperature=0 greedy decoding
    # loops on repetitive text until the output cap. The retry must bump the
    # temperature to break the loop, and must bill the truncated attempt too.
    calls = []

    def fake_complete(kwargs, **_):
        calls.append(kwargs.get("temperature"))
        if len(calls) == 1:
            raise llm.TruncatedResponseError(
                "response truncated", usage=Usage(input=5, output=8000))
        return json.dumps({"people": []}), Usage(input=5, output=3)

    monkeypatch.setattr(llm, "_complete", fake_complete)
    people, usage = llm.find_people("repetitive", model="gemini/gemini-2.5-flash-lite")
    assert people == []
    assert calls[0] == 0           # first pass stays deterministic
    assert calls[1] and calls[1] > 0  # retry escapes greedy decoding
    assert usage == Usage(input=10, output=8003)  # both attempts billed


def test_find_people_propagates_when_retry_also_truncates(monkeypatch):
    # A genuinely huge page (not a loop) truncates even at higher temperature;
    # the truncation error must surface so the page is left for a later run /
    # smaller chunk size -- not silently mis-parsed.
    def fake_complete(kwargs, **_):
        raise llm.TruncatedResponseError(
            "response truncated", usage=Usage(input=5, output=8000))

    monkeypatch.setattr(llm, "_complete", fake_complete)
    with pytest.raises(llm.TruncatedResponseError):
        llm.find_people("x", model="m")


def test_friendly_error_truncation_is_clear_even_when_wrapped():
    direct = llm.friendly_error(
        llm.TruncatedResponseError("response truncated at output-token limit"),
        "gemini/gemini-2.5-flash-lite", None)
    assert "output-token" in direct.lower()
    assert "truncat" in direct.lower() or "cut off" in direct.lower()
    # the extractor wraps the cause in a RuntimeError; the message must still be
    # classified as a truncation (via its stable marker), not the generic branch.
    wrapped = RuntimeError(
        "chunk 1/1 failed for x.jpg.txt: response truncated at output-token "
        "limit (finish_reason=length)")
    msg = llm.friendly_error(wrapped, "gemini/gemini-2.5-flash-lite", None)
    assert "truncat" in msg.lower() or "cut off" in msg.lower()


def test_friendly_error_empty_response_is_clear_even_when_wrapped():
    direct = llm.friendly_error(
        llm.EmptyResponseError(
            "model returned an empty response (no content) "
            "(finish_reason=content_filter)", finish_reason="content_filter"),
        "gemini/gemini-2.5-flash-lite", None)
    assert "empty" in direct.lower() or "no content" in direct.lower()
    assert "different model" in direct.lower()
    # crucially, NOT the old cryptic crash text
    assert "nonetype" not in direct.lower()
    # the extractor wraps the cause in a RuntimeError; classify via stable marker.
    wrapped = RuntimeError(
        "chunk 1/1 failed for x.jpg.txt: model returned an empty response "
        "(no content) (finish_reason=content_filter)")
    msg = llm.friendly_error(wrapped, "gemini/gemini-2.5-flash-lite", None)
    assert "empty" in msg.lower() or "no content" in msg.lower()


def test_error_class_empty_response_direct_and_wrapped():
    exc = llm.EmptyResponseError(
        "model returned an empty response (no content) "
        "(finish_reason=content_filter)", finish_reason="content_filter")
    assert error_class(exc) == "empty"
    assert error_class(_wrap(exc)) == "empty"
    assert is_persistent_failure(_wrap(exc)) is True


def test_friendly_error_wrapped_validation_error_is_bad_json_message():
    # A pydantic ValidationError, wrapped by the extractor in a RuntimeError, is
    # a bad-JSON failure. isinstance no longer matches through the wrapper, so
    # the message must still resolve to the friendly "valid JSON" branch (its str
    # carries "validation error"), not the generic LLM-error tail.
    try:
        NameResponse.model_validate({"people": "not-a-list"})
        raise AssertionError("expected ValidationError")
    except ValidationError as vexc:
        wrapped = RuntimeError(f"chunk 1/1 failed for x.jpg.txt: {vexc}")
    msg = llm.friendly_error(wrapped, "openai/gpt-4o-mini", None)
    assert "valid json" in msg.lower()


def test_usage_from_response_reads_prompt_completion_cached():
    response = {"choices": [{"message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 1144, "completion_tokens": 304,
                          "prompt_tokens_details": {"cached_tokens": 512}}}
    assert llm.usage_from_response(response) == Usage(input=1144, output=304, cached=512)


def test_usage_from_response_handles_missing_usage_and_details():
    # no usage block at all (e.g. some Ollama responses) -> unknown
    assert llm.usage_from_response({"choices": []}) is None
    # usage present but no cached details -> cached defaults to 0
    response = {"usage": {"prompt_tokens": 10, "completion_tokens": 2}}
    assert llm.usage_from_response(response) == Usage(input=10, output=2, cached=0)


def test_complete_returns_content_and_usage(monkeypatch):
    monkeypatch.setattr(llm.litellm, "completion", lambda **kw: {
        "choices": [{"message": {"content": '{"people": []}'}}],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3,
                  "prompt_tokens_details": {"cached_tokens": 4}}})
    content, usage = llm._complete({"model": "m", "messages": []})
    assert content == '{"people": []}'
    assert usage == Usage(input=7, output=3, cached=4)


def test_friendly_error_not_found_ollama():
    msg = llm.friendly_error(RuntimeError("model not found, try pulling"), "ollama/llama3.1", None)
    assert "ollama pull" in msg


def test_friendly_error_missing_key_is_auth_not_connection():
    # LiteLLM wraps a missing key in APIConnectionError whose text/class name
    # contains "connection"; the message must still tell the user it's a key
    # problem, not a network one.
    exc = RuntimeError("litellm.APIConnectionError: Missing Gemini API key. "
                       "Set the GEMINI_API_KEY or GOOGLE_API_KEY environment variable.")
    msg = llm.friendly_error(exc, "gemini/gemini-2.5-flash-lite", None)
    assert "Authentication failed" in msg
    assert "GEMINI_API_KEY" in msg
    assert "network" not in msg.lower()


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
    content, _usage = llm._complete({"model": "m", "messages": []})
    assert content == '{"people": []}'
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


def test_offending_param_detects_deprecated_temperature():
    exc = RuntimeError("AnthropicException - `temperature` is deprecated for this model.")
    assert llm._offending_param(exc) == "temperature"
    # an unrelated error names no droppable param
    assert llm._offending_param(RuntimeError("connection refused")) is None


def test_complete_drops_deprecated_param_and_retries(monkeypatch):
    monkeypatch.setattr(llm, "_unsupported_params", {})
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    seen = []

    def fake_completion(**kwargs):
        seen.append(dict(kwargs))
        if "temperature" in kwargs:   # this model rejects temperature
            raise RuntimeError("`temperature` is deprecated for this model.")
        return _ok_response()

    monkeypatch.setattr(llm.litellm, "completion", fake_completion)
    out, _usage = llm._complete(
        {"model": "anthropic/claude-opus-4-8", "messages": [], "temperature": 0})
    assert out == '{"people": []}'
    assert len(seen) == 2                    # rejected once, then retried
    assert "temperature" not in seen[1]      # dropped on the retry
    # remembered so later calls for this model skip it up front
    assert "temperature" in llm._unsupported_params["anthropic/claude-opus-4-8"]


def test_complete_skips_known_unsupported_param_up_front(monkeypatch):
    # model already known to reject temperature -> never sent, no failed attempt
    monkeypatch.setattr(llm, "_unsupported_params", {"m": {"temperature"}})
    seen = []

    def fake_completion(**kwargs):
        seen.append(dict(kwargs))
        return _ok_response()

    monkeypatch.setattr(llm.litellm, "completion", fake_completion)
    llm._complete({"model": "m", "messages": [], "temperature": 0})
    assert len(seen) == 1                    # no rejected first call
    assert "temperature" not in seen[0]      # stripped before sending


def test_check_model_recovers_from_deprecated_temperature(monkeypatch):
    monkeypatch.setattr(llm, "_unsupported_params", {})
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)

    def fake_completion(**kwargs):
        if "temperature" in kwargs:
            raise RuntimeError("`temperature` is deprecated for this model.")
        return _ok_response()

    monkeypatch.setattr(llm.litellm, "completion", fake_completion)
    # preflight must succeed (None) by dropping temperature, not skip the model
    assert llm.check_model("anthropic/claude-opus-4-8") is None


def test_friendly_error_rate_limit():
    msg = llm.friendly_error(_rate_limit_error(), "anthropic/claude-haiku-4-5", None)
    assert "rate limit" in msg.lower()


def test_friendly_error_surfaces_provider_detail_for_quota():
    # A daily-quota cap arrives as a 429 (classified as a rate limit), but the
    # generic "slow down" advice hides WHICH limit was hit. The provider's own
    # words must survive into the message so the true cause is visible.
    exc = litellm.RateLimitError(
        message="RESOURCE_EXHAUSTED: Quota exceeded for quota metric "
                "'generate_content_free_tier_requests' per day, limit 50",
        llm_provider="gemini", model="gemini-2.5-flash-lite", response=None)
    msg = llm.friendly_error(exc, "gemini/gemini-2.5-flash-lite", None)
    assert "rate limit" in msg.lower()
    assert "per day" in msg            # the real cause is no longer hidden
    assert "Quota exceeded" in msg


def test_friendly_error_detail_trims_traceback_to_first_line():
    exc = RuntimeError(
        "Connection refused by host\n"
        "Traceback (most recent call last):\n  File \"x.py\", line 1")
    msg = llm.friendly_error(exc, "openai/gpt-4o-mini", None)
    assert "Connection refused by host" in msg   # raw cause surfaced
    assert "Traceback" not in msg                # but no stack dump leaks


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


def _wrap(cause: Exception) -> Exception:
    # Mirror extractor._extract_one: RuntimeError(...) from cause.
    try:
        raise cause
    except Exception as inner:
        try:
            raise RuntimeError(f"chunk 1/1 failed for x: {inner}") from inner
        except RuntimeError as wrapped:
            return wrapped


def test_error_class_truncated_direct_and_wrapped():
    exc = TruncatedResponseError(
        "response truncated at output-token limit (finish_reason=length)",
        finish_reason="length")
    assert error_class(exc) == "truncated"
    assert error_class(_wrap(exc)) == "truncated"
    assert is_persistent_failure(_wrap(exc)) is True


def test_error_class_bad_json_direct_and_wrapped():
    jexc = json.JSONDecodeError("Expecting value", "", 0)
    assert error_class(jexc) == "bad_json"
    assert error_class(_wrap(jexc)) == "bad_json"
    try:
        NameResponse.model_validate({"people": "not-a-list"})
        raise AssertionError("expected ValidationError")
    except ValidationError as vexc:
        assert error_class(vexc) == "bad_json"
        assert error_class(_wrap(vexc)) == "bad_json"


def test_error_class_transient_returns_none():
    assert error_class(ConnectionError("connection refused")) is None
    assert error_class(RuntimeError("rate limit: 429 too many requests")) is None
    assert is_persistent_failure(ConnectionError("nope")) is False


def test_truncation_finish_reason_walks_chain():
    exc = TruncatedResponseError("response truncated ...", finish_reason="max_tokens")
    assert truncation_finish_reason(exc) == "max_tokens"
    assert truncation_finish_reason(_wrap(exc)) == "max_tokens"
    assert truncation_finish_reason(ConnectionError("x")) is None


def test_build_messages_appends_user_notes():
    msgs = llm.build_messages("J. Smith paid.", notes="J. Smith is James Smith.")
    assert "NOTES" in msgs[0]["content"]  # system prompt explains notes override
    assert "J. Smith paid." in msgs[1]["content"]
    assert "NOTES:" in msgs[1]["content"]
    assert "J. Smith is James Smith." in msgs[1]["content"]


def test_build_messages_without_notes_has_no_notes_block():
    msgs = llm.build_messages("J. Smith paid.")
    assert "NOTES:" not in msgs[1]["content"]
