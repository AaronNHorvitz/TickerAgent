"""The loaded data set for one stock, shared by the brief and chat.

Filing sections (S1..Sn), reported figures (F) and Nasdaq market data (Q, P).
SEC responses are cached on disk and Nasdaq responses in memory, and the
assembled set is kept for a few minutes so chat turns see the same documents
as the brief (which also keeps the model's prompt cache warm).
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import httpx

from . import nasdaq, sec

TTL_S = 5 * 60
_lock = threading.Lock()
_cache: dict[str, tuple[float, "StockData"]] = {}


class SourceUnavailable(RuntimeError):
    """SEC could not be reached to resolve the ticker; nothing useful can be shown."""


@dataclass
class StockData:
    company: dict
    market: dict
    figures: list[dict]
    sources: list[dict]  # filing sections with text: id, label, section, url, form, filed, text
    data_seconds: float = 0.0
    notes: list[str] = field(default_factory=list)


def sources_from(filings: list[sec.Filing]) -> list[dict]:
    out = []
    for f in filings:
        for name, text in f.sections.items():
            label = f"{f.form} filed {f.filed}"
            if f.form == "8-K" and f.item_labels():
                label += f" ({', '.join(f.item_labels())})"
            out.append({"id": f"S{len(out) + 1}", "label": label, "section": name,
                        "url": f.url, "form": f.form, "filed": f.filed, "text": text})
    return out


def _market_or_error(symbol: str) -> dict:
    try:
        return nasdaq.market_data(symbol)
    except Exception:  # never let market data take the brief down
        return {"quote": None, "summary": None, "history": None,
                "errors": {"all": "Nasdaq data unavailable."}, "source": "Nasdaq public website data"}


def load(ticker: str, use_cache: bool = True) -> StockData:
    """Resolve the ticker with SEC, then gather filings, figures and market data.

    Raises LookupError for a ticker SEC does not know. Everything else degrades:
    a failing source leaves its part empty and adds a note.
    """
    key = nasdaq.sec_symbol(ticker)
    now = time.time()
    if use_cache:
        with _lock:
            hit = _cache.get(key)
        if hit and now - hit[0] < TTL_S:
            return hit[1]

    t0 = time.time()
    try:
        company = sec.lookup_company(key)
    except httpx.HTTPError:
        raise SourceUnavailable("SEC EDGAR is not responding right now, so the company can't be looked up. "
                                "Please try again in a few minutes.") from None
    company["symbol"] = nasdaq.display_symbol(company["ticker"])
    notes: list[str] = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        fm = pool.submit(_market_or_error, company["symbol"])
        ff = pool.submit(sec.reported_figures, company["cik"])
        try:
            filings = [sec.load_sections(f) for f in sec.recent_filings(company["cik"])]
        except Exception:
            filings = []
            notes.append("SEC filings could not be loaded right now.")
        market = fm.result()
        try:
            figures = ff.result()
        except Exception:
            figures = []
            notes.append("SEC reported figures could not be loaded right now.")
    if market.get("errors"):
        notes.append("Some Nasdaq market data is unavailable: " + ", ".join(sorted(market["errors"])) + ".")
    data = StockData(company=company, market=market, figures=figures, sources=sources_from(filings),
                     data_seconds=round(time.time() - t0, 1), notes=notes)
    with _lock:
        _cache[key] = (time.time(), data)
    return data


def clear_cache() -> None:
    with _lock:
        _cache.clear()
