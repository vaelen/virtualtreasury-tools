# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import httpx
import pytest

from vtextract.client import Client


def make_client(handler, **kwargs):
    transport = httpx.MockTransport(handler)
    return Client(
        base_url="https://api.test",
        auth_header="Basic xyz",
        user_agent="UA",
        transport=transport,
        delay=0.0,
        sleep_func=lambda _s: None,
        **kwargs,
    )


def test_get_json_sends_auth_and_parses_body():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["ua"] = request.headers.get("user-agent")
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler)
    assert client.get_json("/rest/thing/1") == {"ok": True}
    assert seen["auth"] == "Basic xyz"
    assert seen["ua"] == "UA"
    assert seen["url"] == "https://api.test/rest/thing/1"


def test_post_json_sends_body():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        return httpx.Response(200, content=b'{"totalDocs": 0}', headers={"content-type": "text/plain"})

    client = make_client(handler)
    result = client.post_json("/search", {"a": 1})
    assert result == {"totalDocs": 0}
    assert b'"a": 1' in seen["body"] or b'"a":1' in seen["body"]


def test_get_bytes_returns_raw_content():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"\xff\xd8image")

    client = make_client(handler)
    assert client.get_bytes("https://api.test/loris/x/full/full/0/default.jpg") == b"\xff\xd8image"


def test_retries_on_500_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(500)
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler, max_retries=3)
    assert client.get_json("/x") == {"ok": True}
    assert calls["n"] == 3


def test_raises_after_exhausting_retries():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    client = make_client(handler, max_retries=2)
    with pytest.raises(httpx.HTTPStatusError):
        client.get_json("/x")


def test_raises_immediately_on_404_without_retry():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404, text="nope")

    client = make_client(handler, max_retries=3)
    with pytest.raises(httpx.HTTPStatusError):
        client.get_json("/missing")
    assert calls["n"] == 1  # 404 must not be retried


def test_raises_on_401():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    client = make_client(handler, max_retries=2)
    with pytest.raises(httpx.HTTPStatusError):
        client.get_json("/secure")


def test_throttle_sleeps_between_consecutive_requests():
    slept: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    client = Client(
        base_url="https://api.test", auth_header="Basic x", user_agent="UA",
        transport=httpx.MockTransport(handler), delay=0.05, sleep_func=slept.append,
    )
    client.get_json("/a")  # first request: no wait (no prior request)
    client.get_json("/b")  # second request: must wait out the delay
    assert any(s > 0 for s in slept)


def test_backoff_grows_per_retry():
    slept: list[float] = []
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(500)
        return httpx.Response(200, json={"ok": True})

    client = Client(
        base_url="https://api.test", auth_header="Basic x", user_agent="UA",
        transport=httpx.MockTransport(handler), delay=0.0, max_retries=3,
        sleep_func=slept.append,
    )
    assert client.get_json("/x") == {"ok": True}
    # delay=0.0 means _throttle never sleeps, so these are pure backoff waits:
    # 2**0 after the first 500, 2**1 after the second.
    assert slept == [1.0, 2.0]
