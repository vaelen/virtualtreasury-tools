# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

RETRY_STATUS = {429, 500, 502, 503, 504}


class Client:
    """Thin HTTP layer: auth header, polite rate-limit delay, retry/backoff.

    The single choke point for all backend requests.
    """

    def __init__(
        self,
        base_url: str,
        auth_header: str,
        *,
        user_agent: str,
        transport: httpx.BaseTransport | None = None,
        delay: float = 0.5,
        max_retries: int = 3,
        sleep_func: Callable[[float], None] = time.sleep,
    ) -> None:
        self._delay = delay
        self._max_retries = max_retries
        self._sleep = sleep_func
        self._last_request = 0.0
        self._http = httpx.Client(
            base_url=base_url,
            transport=transport,
            timeout=60.0,
            headers={"Authorization": auth_header, "User-Agent": user_agent},
        )

    def _throttle(self) -> None:
        if self._delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request
        if elapsed < self._delay:
            self._sleep(self._delay - elapsed)
        self._last_request = time.monotonic()

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        for attempt in range(self._max_retries + 1):
            self._throttle()
            try:
                response = self._http.request(method, url, **kwargs)
            except httpx.TransportError:
                if attempt < self._max_retries:
                    self._sleep(2.0**attempt)
                    continue
                raise
            if response.status_code in RETRY_STATUS and attempt < self._max_retries:
                self._sleep(2.0**attempt)
                continue
            response.raise_for_status()
            return response
        raise RuntimeError("unreachable")  # pragma: no cover

    def get_json(self, url: str) -> dict:
        return self._request("GET", url).json()

    def post_json(self, url: str, body: dict) -> dict:
        return self._request("POST", url, json=body).json()

    def get_bytes(self, url: str) -> bytes:
        return self._request("GET", url).content

    def close(self) -> None:
        self._http.close()
