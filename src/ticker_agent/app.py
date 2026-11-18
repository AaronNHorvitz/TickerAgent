"""HTTP surface: one page for advisors plus a small JSON API."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Iterator

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from . import chat, nasdaq
from .brief import build_brief

log = logging.getLogger("ticker_agent")
app = FastAPI(title="TickerAgent")
STATIC = Path(__file__).parent / "static"
# Letters, then letters/dots/hyphens/slashes for share classes: NVDA, BRK.B, BRK-B, BRK/B.
TICKER = re.compile(r"[A-Za-z][A-Za-z./\-]{0,9}")


@app.exception_handler(RequestValidationError)
async def friendly_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
    if request.url.path == "/api/chat":
        msg = (f"Please send a question of up to {chat.MAX_QUESTION_CHARS} characters for a valid ticker, "
               f"with at most {chat.MAX_TURNS} earlier turns of up to {chat.MAX_TURN_CHARS} characters each.")
    else:
        msg = "That request was not valid."
    return JSONResponse({"detail": msg}, status_code=400)


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


def _sse(events: Iterator[tuple[str, dict]]) -> Iterator[str]:
    try:
        for event, data in events:
            yield f"event: {event}\ndata: {json.dumps(data)}\n\n"
    except Exception:  # anything unexpected still ends the stream with a readable message
        log.exception("chat stream failed")
        yield f"event: error\ndata: {json.dumps({'message': 'Something went wrong answering that. Please try again.'})}\n\n"


@app.post("/api/chat")
def chat_endpoint(req: chat.ChatRequest) -> StreamingResponse:
    return StreamingResponse(_sse(chat.run(req)), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
