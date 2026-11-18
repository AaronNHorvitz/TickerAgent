# Adapted from the owner's earlier Nasdaq screener code (download, row validation, symbol/name search).
"""Market data from Nasdaq's public website endpoints: stock list, quote, summary, daily history.

No API key. These endpoints are not a documented API, so everything sits behind
this one module and each call fails on its own with a NasdaqError; callers
degrade section by section. A licensed feed would replace this module in
production with the same return shapes.

Prices stay as Nasdaq formats them for display and are also parsed to floats.
The analyst price target is removed here so it never reaches the page or the model.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx

BASE = "https://api.nasdaq.com/api"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/110.0.0.0 Safari/537.36",
    "Accept": "application/json",
}
MAX_BYTES = 8_000_000
LIST_TTL_S = 15 * 60  # stock list cache
QUOTE_TTL_S = 5 * 60  # quote/summary/history cache: keeps chat turns on the same numbers
FIELDS = ("symbol", "name", "lastsale", "netchange", "pctchange", "volume",
          "marketCap", "country", "ipoyear", "sector", "industry")
# Summary keys never passed on: analyst price targets (no-recommendation rule).
_DROPPED = re.compile(r"target", re.I)

_client = httpx.Client(headers=HEADERS, timeout=15.0, follow_redirects=False)
_lock = threading.Lock()
_cache: dict[str, tuple[float, Any]] = {}


class NasdaqError(RuntimeError):
    """A network, access, or response-format failure. No fabricated fallback."""


# ---- Symbols -----------------------------------------------------------------
def display_symbol(symbol: str) -> str:
    """Nasdaq's list spelling: share classes use a slash (BRK/B)."""
    return re.sub(r"[.\-]", "/", symbol.strip().upper())


def sec_symbol(symbol: str) -> str:
    """SEC ticker-map spelling: share classes use a hyphen (BRK-B)."""
    return re.sub(r"[./]", "-", symbol.strip().upper())


def _quote_symbol(symbol: str) -> str:
    """Spelling the quote endpoints accept in the URL path (BRK.B)."""
    return re.sub(r"[/\-]", ".", symbol.strip().upper())


# ---- HTTP --------------------------------------------------------------------
def _get(path: str, params: dict[str, str]) -> dict[str, Any]:
    try:
        with _client.stream("GET", f"{BASE}/{path}", params=params) as resp:
            if resp.status_code in (401, 403):
                raise NasdaqError(f"Nasdaq denied access (HTTP {resp.status_code}).")
            if resp.status_code == 429:
                raise NasdaqError("Nasdaq rate limit reached; try again shortly.")
            resp.raise_for_status()
            body = bytearray()
            for chunk in resp.iter_bytes():
                if len(body) + len(chunk) > MAX_BYTES:
                    raise NasdaqError("Nasdaq response exceeds the download size limit.")
                body.extend(chunk)
        payload = json.loads(body)
    except NasdaqError:
        raise
    except httpx.TimeoutException:
        raise NasdaqError("Nasdaq request timed out.") from None
    except httpx.HTTPStatusError as e:
        raise NasdaqError(f"Nasdaq returned HTTP {e.response.status_code}.") from None
    except httpx.HTTPError:
        raise NasdaqError("Could not connect to Nasdaq.") from None
    except ValueError:
        raise NasdaqError("Nasdaq returned invalid JSON.") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        msgs = ((payload or {}).get("status") or {}).get("bCodeMessage") or []
        detail = msgs[0].get("errorMessage") if msgs and isinstance(msgs[0], dict) else None
        raise NasdaqError(f"Nasdaq has no data for this request{': ' + detail if detail else ''}.")
    return payload["data"]


def _cached(key: str, ttl: float, fetch):
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    value = fetch()
    with _lock:
        _cache[key] = (now, value)
    return value


def clear_cache() -> None:
    with _lock:
        _cache.clear()


# ---- Parsing helpers ---------------------------------------------------------
def _num(v: Any) -> float | None:
    """'$1,234.50', '-2.23%', '3,665,369,000,000' -> float; anything else -> None."""
    if isinstance(v, (int, float)):
        return float(v)
    if not isinstance(v, str):
        return None
    s = v.replace("$", "").replace(",", "").replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _clean(v: Any) -> str | None:
    if not isinstance(v, str):
        return None
    v = v.strip()
    return None if v in ("", "N/A", "NA", "--") else v


# ---- Stock list and search ---------------------------------------------------
def stock_list() -> list[dict[str, Any]]:
    """All listed stocks (about 7,000 rows), cached in memory for 15 minutes."""
    def fetch():
        data = _get("screener/stocks", {"tableonly": "true", "limit": "0", "offset": "0", "download": "true"})
        rows = data.get("rows")
        if not isinstance(rows, list) or not rows:
            raise NasdaqError("Nasdaq stock list has no rows; its format may have changed.")
        out = []
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("symbol"), str) or not row["symbol"].strip():
                continue  # skip malformed rows rather than failing the whole list
            if not isinstance(row.get("name"), str):
                continue
            out.append({k: row.get(k) for k in FIELDS})
        return out
    return _cached("list", LIST_TTL_S, fetch)


def search(query: str, limit: int = 8) -> list[dict[str, Any]]:
    """Ticker or company-name search.

    Order: exact symbol, symbol prefix, name starting with the query, a word in the
    name starting with the query, then any name containing it. "BRK.B", "BRK-B"
    and "BRK/B" all find BRK/B; "berkshire" finds both share classes.
    """
    q = query.strip()
    if not q:
        return []
    sym = display_symbol(q)
    needle = q.casefold()
    word = re.compile(r"\b" + re.escape(needle))
    ranked = []
    for row in stock_list():
        s, name = row["symbol"].upper(), row["name"].casefold()
        if s == sym:
            rank = 0
        elif s.startswith(sym):
            rank = 1
        elif name.startswith(needle):
            rank = 2
        elif word.search(name):
            rank = 3
        elif needle in name:
            rank = 4
        else:
            continue
        ranked.append((rank, s, row))
    ranked.sort(key=lambda t: (t[0], t[1]))
    return [{
        "symbol": row["symbol"], "name": row["name"],
        "sector": _clean(row.get("sector")), "industry": _clean(row.get("industry")),
        "last": _clean(row.get("lastsale")), "change_pct": _clean(row.get("pctchange")),
    } for _, _, row in ranked[:limit]]


# ---- Quote, summary, history -------------------------------------------------
def quote(symbol: str) -> dict[str, Any]:
    qs = _quote_symbol(symbol)

    def fetch():
        d = _get(f"quote/{qs}/info", {"assetclass": "stocks"})
        p = d.get("primaryData") or {}
        price = _num(p.get("lastSalePrice"))
        if price is None:
            raise NasdaqError("Nasdaq quote has no last sale price.")
        return {
            "symbol": display_symbol(symbol), "company": d.get("companyName"),
            "exchange": d.get("exchange"), "price": price,
            "price_text": p.get("lastSalePrice"),
            "change": _num(p.get("netChange")), "change_pct": _num(p.get("percentageChange")),
            "trade_time": p.get("lastTradeTimestamp"), "is_real_time": bool(p.get("isRealTime")),
            "market_status": d.get("marketStatus"),
        }
    return _cached(f"quote:{qs}", QUOTE_TTL_S, fetch)


def summary(symbol: str) -> dict[str, Any]:
    """Key facts from the summary endpoint; analyst targets removed."""
    qs = _quote_symbol(symbol)

    def fetch():
        d = _get(f"quote/{qs}/summary", {"assetclass": "stocks"})
        raw = d.get("summaryData")
        if not isinstance(raw, dict):
            raise NasdaqError("Nasdaq summary has no data.")
        fields = {}
        for key, item in raw.items():
            if _DROPPED.search(key) or (isinstance(item, dict) and _DROPPED.search(str(item.get("label", "")))):
                continue
            if isinstance(item, dict):
                val = _clean(item.get("value")) if isinstance(item.get("value"), str) else item.get("value")
                if val is not None:
                    fields[key] = {"label": item.get("label") or key, "value": val}
        hi = lo = None
        rng = (fields.get("FiftTwoWeekHighLow") or {}).get("value")
        if isinstance(rng, str) and "/" in rng:
            a, b = rng.split("/", 1)
            hi, lo = _num(a), _num(b)
        return {
            "fields": fields,
            "exchange": (fields.get("Exchange") or {}).get("value"),
            "sector": (fields.get("Sector") or {}).get("value"),
            "industry": (fields.get("Industry") or {}).get("value"),
            "previous_close": _num((fields.get("PreviousClose") or {}).get("value")),
            "high_52w": hi, "low_52w": lo,
            "market_cap": _num((fields.get("MarketCap") or {}).get("value")),
            "dividend": (fields.get("AnnualizedDividend") or {}).get("value"),
            "yield": (fields.get("Yield") or {}).get("value"),
            "ex_dividend_date": (fields.get("ExDividendDate") or {}).get("value"),
        }
    return _cached(f"summary:{qs}", QUOTE_TTL_S, fetch)


def history(symbol: str, days: int = 366) -> list[dict[str, Any]]:
    """One year of daily prices, oldest first: date (ISO), open, high, low, close, volume."""
    qs = _quote_symbol(symbol)

    def fetch():
        to = dt.date.today()
        frm = to - dt.timedelta(days=days)
        d = _get(f"quote/{qs}/historical", {"assetclass": "stocks", "fromdate": frm.isoformat(),
                                             "todate": to.isoformat(), "limit": "400"})
        rows = ((d.get("tradesTable") or {}).get("rows")) or []
        out = []
        for r in rows:
            try:
                day = dt.datetime.strptime(r["date"], "%m/%d/%Y").date().isoformat()
            except (KeyError, TypeError, ValueError):
                continue
            close = _num(r.get("close"))
            if close is None:
                continue
            out.append({"date": day, "open": _num(r.get("open")), "high": _num(r.get("high")),
                        "low": _num(r.get("low")), "close": close, "volume": _num(r.get("volume"))})
        if not out:
            raise NasdaqError("Nasdaq returned no price history.")
        return sorted(out, key=lambda r: r["date"])
    return _cached(f"history:{qs}:{days}", QUOTE_TTL_S, fetch)


def market_data(symbol: str) -> dict[str, Any]:
    """Quote, summary and history, each fetched independently.

    A failing part is reported in `errors` and left as None; the others still return.
    """
    out: dict[str, Any] = {"quote": None, "summary": None, "history": None, "errors": {},
                           "source": "Nasdaq public website data"}
    parts = (("quote", quote), ("summary", summary), ("history", history))
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {part: pool.submit(fn, symbol) for part, fn in parts}
    for part, fut in futures.items():
        try:
            out[part] = fut.result()
        except NasdaqError as e:
            out["errors"][part] = str(e)
        except Exception:  # unexpected shape changes must not break the brief
            out["errors"][part] = "Nasdaq data could not be read."
    h = out["history"]
    q = out["quote"]
    if h and q and h[0]["close"]:
        out["one_year_pct"] = round((q["price"] / h[0]["close"] - 1) * 100, 1)
    return out
