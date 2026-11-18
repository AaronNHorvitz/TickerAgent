"""HTTP surface: one page for advisors plus a small JSON API."""
from __future__ import annotations

import logging
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from . import nasdaq
from .brief import build_brief

log = logging.getLogger("ticker_agent")
app = FastAPI(title="TickerAgent")
STATIC = Path(__file__).parent / "static"
# Letters, then letters/dots/hyphens/slashes for share classes: NVDA, BRK.B, BRK-B, BRK/B.
TICKER = re.compile(r"[A-Za-z][A-Za-z./\-]{0,9}")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/api/search")
def search(q: str = Query("", max_length=60)) -> dict:
    q = q.strip()
    if not q:
        return {"query": q, "matches": []}
    try:
        return {"query": q, "matches": nasdaq.search(q)}
    except nasdaq.NasdaqError as e:
        log.warning("search unavailable: %s", e)
        return {"query": q, "matches": [], "error": "Company search is unavailable right now; enter a ticker symbol."}


@app.get("/api/brief/{ticker:path}")
def brief(ticker: str) -> dict:
    if not TICKER.fullmatch(ticker):
        raise HTTPException(400, "Enter a ticker symbol, e.g. AAPL or BRK/B.")
    try:
        return build_brief(ticker)
    except LookupError as e:
        raise HTTPException(404, str(e))
