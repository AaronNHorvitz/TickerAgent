"""Protection for a public URL: a per-visitor rate limit and a daily cap on AI calls.

Settings (environment):
  RATE_LIMIT_PER_MINUTE    brief and chat requests per visitor per minute (default 10)
  SEARCH_LIMIT_PER_MINUTE  search requests per visitor per minute (default 90)
  DAILY_AI_CALLS           model calls per UTC day across all visitors (default 300; 0 turns AI off)

Counters live in memory, so they are per container; the prototype runs one.
The visitor is the first X-Forwarded-For entry (the client as seen by the load
balancer), else the socket address. That header can be set by a client, so the
limit slows casual abuse; the account's spend limit is the hard stop.
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque

from fastapi import HTTPException, Request

MAX_VISITORS = 20_000  # bound memory; the oldest visitors are forgotten first


def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, default)))
    except ValueError:
        return default


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    first = fwd.split(",")[0].strip()
    if first:
        return first[:64]
    return request.client.host if request.client else "unknown"


class RateLimiter:
    """Sliding one-minute window per visitor."""

    def __init__(self, per_minute: int, window_s: float = 60.0):
        self.per_minute, self.window = per_minute, window_s
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def check(self, key: str, now: float | None = None) -> float:
        """Record a request. Returns 0 when allowed, else seconds until the next one is."""
        now = time.monotonic() if now is None else now
        with self._lock:
            q = self._hits.pop(key, None) or deque()
            while q and now - q[0] >= self.window:
                q.popleft()
            self._hits[key] = q  # re-insert: dict order tracks recent use
            if len(q) >= self.per_minute:
                return max(1.0, self.window - (now - q[0]))
            q.append(now)
            while len(self._hits) > MAX_VISITORS:
                self._hits.pop(next(iter(self._hits)))
            return 0.0


class DailyCap:
    """Count of AI calls per UTC day."""

    def __init__(self, limit: int):
        self.limit = limit
        self._day, self._count = "", 0
        self._lock = threading.Lock()

    def take(self, today: str | None = None) -> bool:
        today = today or time.strftime("%Y-%m-%d", time.gmtime())
        with self._lock:
            if today != self._day:
                self._day, self._count = today, 0
            if self._count >= self.limit:
                return False
            self._count += 1
            return True

    def remaining(self, today: str | None = None) -> int:
        today = today or time.strftime("%Y-%m-%d", time.gmtime())
        with self._lock:
            return self.limit if today != self._day else max(0, self.limit - self._count)


pages = RateLimiter(_env_int("RATE_LIMIT_PER_MINUTE", 10))
searches = RateLimiter(_env_int("SEARCH_LIMIT_PER_MINUTE", 90))
ai_calls = DailyCap(_env_int("DAILY_AI_CALLS", 300))


def _limit(limiter: RateLimiter, request: Request, what: str) -> None:
    wait = limiter.check(client_ip(request))
    if wait:
        secs = int(wait + 0.999)
        raise HTTPException(429, f"Too many {what} from this connection. Please wait {secs} seconds and try again.",
                            headers={"Retry-After": str(secs)})


def limit_pages(request: Request) -> None:
    """FastAPI dependency for brief and chat."""
    _limit(pages, request, "requests")


def limit_search(request: Request) -> None:
    """FastAPI dependency for search."""
    _limit(searches, request, "searches")


def take_ai_call() -> bool:
    return ai_calls.take()


DAILY_CAP_MESSAGE = "The daily limit for AI answers has been reached. Please try again tomorrow (UTC)."
