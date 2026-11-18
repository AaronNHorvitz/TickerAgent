"""HTTP surface: one page for advisors plus a small JSON API."""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Iterator

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from . import chat, gather, guard, llm, nasdaq
from .brief import build_brief

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper(),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("ticker_agent")
for noisy in ("httpx", "httpx2"):  # per-request URL logs add noise, not insight
    logging.getLogger(noisy).setLevel(logging.WARNING)
app = FastAPI(title="TickerAgent", docs_url=None, redoc_url=None)
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


@app.exception_handler(Exception)
async def friendly_crash(request: Request, exc: Exception) -> JSONResponse:
    # Log the error class and path only; request bodies and headers stay out of the logs.
    log.error("unhandled %s on %s", type(exc).__name__, request.url.path)
    return JSONResponse({"detail": "Something went wrong on our side. Please try again."}, status_code=500)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/api/search", dependencies=[Depends(guard.limit_search)])
def search(q: str = Query("", max_length=60)) -> dict:
    q = q.strip()
    if not q:
        return {"query": q, "matches": []}
    try:
        return {"query": q, "matches": nasdaq.search(q)}
    except nasdaq.NasdaqError as e:
        log.warning("search unavailable: %s", e)
        return {"query": q, "matches": [], "error": "Company search is unavailable right now; enter a ticker symbol."}


@app.get("/api/brief/{ticker:path}", dependencies=[Depends(guard.limit_pages)])
def brief(ticker: str) -> dict:
    if not TICKER.fullmatch(ticker):
        raise HTTPException(400, "Enter a ticker symbol, e.g. AAPL or BRK/B.")
    try:
        return build_brief(ticker, take_ai_call=guard.take_ai_call)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except gather.SourceUnavailable as e:
        raise HTTPException(503, str(e))


def _sse(events: Iterator[tuple[str, dict]]) -> Iterator[str]:
    try:
        for event, data in events:
            yield f"event: {event}\ndata: {json.dumps(data)}\n\n"
    except Exception as e:  # anything unexpected still ends the stream with a readable message
        log.error("chat stream failed: %s", type(e).__name__)
        yield f"event: error\ndata: {json.dumps({'message': 'Something went wrong answering that. Please try again.'})}\n\n"


@app.post("/api/chat", dependencies=[Depends(guard.limit_pages)])
def chat_endpoint(req: chat.ChatRequest) -> StreamingResponse:
    if llm.available() and not guard.take_ai_call():
        raise HTTPException(429, guard.DAILY_CAP_MESSAGE)
    return StreamingResponse(_sse(chat.run(req)), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
