"""Shared HTTP client: identifying User-Agent, per-host rate limiting, bounded retries with backoff.

Secrets are never logged. Responses from providers are treated as untrusted data.
"""
from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_SENSITIVE_HEADERS = {"authorization", "x-subscription-token", "x-api-key", "cookie", "api-key"}


class RateLimitedError(Exception):
    pass


class HttpStatusError(Exception):
    """Non-2xx response; the message carries the redacted URL only (no query string / keys)."""

    def __init__(self, status: int, url: str, body: str = ""):
        self.status = status
        self.url = url
        super().__init__(f"HTTP {status} from {url}" + (f": {body.strip()[:120]}" if body else ""))


class ProviderDisabledError(Exception):
    pass


@dataclass
class HostThrottle:
    min_interval: float
    _last: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._last + self.min_interval - now
            if delay > 0:
                time.sleep(delay)
            self._last = time.monotonic()


class HttpClient:
    """Thin wrapper around httpx with polite defaults. One instance per process."""

    def __init__(self, user_agent: str, default_timeout: float = 60.0, default_interval: float = 1.0):
        self.user_agent = user_agent
        self.default_interval = default_interval
        self._client = httpx.Client(
            headers={"User-Agent": user_agent, "Accept": "application/json, text/html;q=0.9, */*;q=0.5"},
            timeout=httpx.Timeout(default_timeout, connect=20.0),
            follow_redirects=True,
            max_redirects=5,
        )
        self._throttles: dict[str, HostThrottle] = {}
        self._lock = threading.Lock()
        self.stats: dict[str, dict[str, int]] = {}

    def set_rate(self, host: str, min_interval: float) -> None:
        with self._lock:
            self._throttles[host] = HostThrottle(min_interval=min_interval)

    def _throttle(self, url: str) -> HostThrottle:
        host = urlsplit(url).hostname or url
        with self._lock:
            throttle = self._throttles.get(host)
            if throttle is None:
                throttle = HostThrottle(min_interval=self.default_interval)
                self._throttles[host] = throttle
        return throttle

    def _bump(self, url: str, key: str) -> None:
        host = urlsplit(url).hostname or url
        with self._lock:
            self.stats.setdefault(host, {"requests": 0, "rate_limited": 0, "errors": 0})
            self.stats[host][key] = self.stats[host].get(key, 0) + 1

    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        data: Any = None,
        json: Any = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
        max_attempts: int = 4,
        stream: bool = False,
    ) -> httpx.Response:
        attempt = 0
        last_exc: Exception | None = None
        while attempt < max_attempts:
            attempt += 1
            self._throttle(url).wait()
            self._bump(url, "requests")
            try:
                if stream:
                    req = self._client.build_request(method, url, params=params, data=data, json=json, headers=headers, timeout=timeout)
                    resp = self._client.send(req, stream=True)
                else:
                    resp = self._client.request(method, url, params=params, data=data, json=json, headers=headers, timeout=timeout)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exc = exc
                self._bump(url, "errors")
                log.warning("HTTP %s %s attempt %d failed: %s", method, _redact(url), attempt, exc.__class__.__name__)
                self._sleep_backoff(attempt)
                continue
            if resp.status_code in RETRYABLE_STATUS:
                self._bump(url, "rate_limited" if resp.status_code == 429 else "errors")
                retry_after = _retry_after_seconds(resp)
                if stream:
                    resp.close()
                log.warning("HTTP %s %s -> %s (attempt %d)", method, _redact(url), resp.status_code, attempt)
                if attempt >= max_attempts:
                    if resp.status_code == 429:
                        raise RateLimitedError(f"{_redact(url)} rate limited after {attempt} attempts")
                    resp.raise_for_status()
                self._sleep_backoff(attempt, retry_after)
                continue
            return resp
        if last_exc:
            raise last_exc
        raise RuntimeError(f"request to {_redact(url)} failed after {max_attempts} attempts")

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def get_json(self, url: str, **kwargs: Any) -> Any:
        resp = self.get(url, **kwargs)
        if resp.status_code >= 400:
            raise HttpStatusError(resp.status_code, _redact(url), resp.text[:200])
        return resp.json()

    @staticmethod
    def _sleep_backoff(attempt: int, retry_after: float | None = None) -> None:
        if retry_after is not None:
            time.sleep(min(retry_after, 120.0))
            return
        time.sleep(min(60.0, (2 ** attempt) + random.uniform(0, 1.0)))

    def close(self) -> None:
        self._client.close()


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    value = resp.headers.get("Retry-After")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _redact(url: str) -> str:
    """Strip query strings so keys never land in logs."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    return {k: ("***" if k.lower() in _SENSITIVE_HEADERS else v) for k, v in headers.items()}
