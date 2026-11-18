"""Current quote data.

Prototype source: a public delayed-quote chart endpoint, no key required.
Production would swap this for the firm's licensed market-data feed; the
function contract (one dict) stays the same.
"""
from __future__ import annotations

import time

import httpx

_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{t}?range=1y&interval=1d"


def get_quote(ticker: str) -> dict:
    resp = httpx.get(_URL.format(t=ticker.upper()), headers={"User-Agent": "Mozilla/5.0"}, timeout=15.0)
    resp.raise_for_status()
    res = resp.json()["chart"]["result"][0]
    meta = res["meta"]
    closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
    price = meta.get("regularMarketPrice") or closes[-1]
    prev = closes[-2] if len(closes) > 1 else meta.get("chartPreviousClose")
    year_ago = closes[0] if closes else None
    return {
        "price": round(price, 2),
        "currency": meta.get("currency", "USD"),
        "change": round(price - prev, 2) if prev else None,
        "change_pct": round((price / prev - 1) * 100, 2) if prev else None,
        "one_year_pct": round((price / year_ago - 1) * 100, 1) if year_ago else None,
        "high_52w": round(max(closes), 2) if closes else None,
        "low_52w": round(min(closes), 2) if closes else None,
        "as_of": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(meta.get("regularMarketTime", time.time()))),
        "exchange": meta.get("fullExchangeName") or meta.get("exchangeName"),
        "series": [round(c, 2) for c in closes[::5]],  # weekly points for the sparkline
        "source": "Delayed public quote (prototype source)",
    }
