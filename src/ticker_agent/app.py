"""HTTP surface: one page for advisors, one JSON endpoint for integrations."""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from .brief import build_brief

app = FastAPI(title="TickerAgent")
STATIC = Path(__file__).parent / "static"


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/api/brief/{ticker}")
def brief(ticker: str) -> dict:
    if not re.fullmatch(r"[A-Za-z][A-Za-z.\-]{0,9}", ticker):
        raise HTTPException(400, "Enter a ticker symbol, e.g. AAPL.")
    try:
        return build_brief(ticker)
    except LookupError as e:
        raise HTTPException(404, str(e))
