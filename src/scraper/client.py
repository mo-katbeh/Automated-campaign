from __future__ import annotations

import time
from typing import Any

import requests

from src.config import (
    DEFAULT_BACKOFF_FACTOR,
    DEFAULT_HEADERS,
    DEFAULT_MAX_RETRIES,
    DEFAULT_REQUEST_DELAY,
    DEFAULT_TIMEOUT,
)


class HttpClient:
    def __init__(
        self,
        *,
        headers: dict[str, str] | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        delay: float = DEFAULT_REQUEST_DELAY,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    ) -> None:
        self.session = requests.Session()
        self.session.headers.update(headers or DEFAULT_HEADERS)
        self.timeout = timeout
        self.delay = delay
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self._last_request_ts = 0.0

    def close(self) -> None:
        self.session.close()

    def _sleep_if_needed(self) -> None:
        if self.delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request_ts
        remaining = self.delay - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def get(self, url: str, params: dict[str, Any] | None = None) -> str:
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            self._sleep_if_needed()
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                self._last_request_ts = time.monotonic()
                response.raise_for_status()
                try:
                    return response.content.decode("utf-8")
                except UnicodeDecodeError:
                    response.encoding = response.apparent_encoding or response.encoding or "utf-8"
                    return response.text
            except requests.RequestException as exc:
                self._last_request_ts = time.monotonic()
                last_error = exc
                if attempt == self.max_retries:
                    break
                time.sleep(self.backoff_factor * attempt)

        raise RuntimeError(f"Request failed for {url}: {last_error}") from last_error
