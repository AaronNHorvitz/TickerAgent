"""Claude access through the Anthropic SDK.

Configuration comes from the environment or a local .env file (never committed):
  ANTHROPIC_API_KEY   required for AI features; without it callers fall back
  ANTHROPIC_MODEL     default claude-opus-5-5
  BRIEF_EFFORT        default medium
  CHAT_EFFORT         default low

Two calls: `structured()` returns schema-validated JSON for the brief, and
`stream_chat()` streams a cited answer over plain-text documents. Both opt into
the server-side fallback for refusals, check the stop reason before reading the
content, and turn SDK errors into LLMError with an advisor-friendly message.
No sampling parameters are sent. Keys are never logged.
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, TypeVar

import anthropic
from pydantic import BaseModel

log = logging.getLogger("ticker_agent.llm")

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
EFFORTS = {"low", "medium", "high", "xhigh", "max"}
T = TypeVar("T", bound=BaseModel)


def _load_dotenv() -> None:
    env = Path(__file__).resolve().parents[2] / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


class LLMError(RuntimeError):
    """A model call that did not produce usable output. `kind` is a short code; str() is safe to show."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


class LLMRefusal(LLMError):
    def __init__(self, category: str | None = None):
        super().__init__("refusal", "The AI service declined to answer this request.")
        self.category = category


def available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def model_name() -> str:
    return os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL


def effort(kind: str) -> str:
    default = "medium" if kind == "brief" else "low"
    value = (os.environ.get(f"{kind.upper()}_EFFORT") or default).strip().lower()
    return value if value in EFFORTS else default


_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        # The SDK retries connection errors, 408, 409, 429 and 5xx itself.
        _client = anthropic.Anthropic(timeout=anthropic.Timeout(180.0, connect=10.0), max_retries=2)
    return _client


@contextmanager
def _errors() -> Iterator[None]:
    """Most specific first; every branch ends in an LLMError the page can show."""
    try:
        yield
    except LLMError:
        raise
    except anthropic.AuthenticationError:
        log.error("model call failed: authentication")
        raise LLMError("auth", "The AI service key is missing or invalid.") from None
    except anthropic.PermissionDeniedError:
        log.error("model call failed: permission denied")
        raise LLMError("auth", "The AI service key is not allowed to use this model.") from None
    except anthropic.NotFoundError:
        log.error("model call failed: model not found (%s)", model_name())
        raise LLMError("config", "The configured AI model is not available.") from None
    except anthropic.RateLimitError:
        log.warning("model call failed: rate limited")
        raise LLMError("busy", "The AI service is busy right now. Please try again in a minute.") from None
    except anthropic.BadRequestError as e:
        log.error("model call rejected: %s", getattr(e, "type", "invalid_request_error"))
        raise LLMError("request", "The AI service rejected the request.") from None
    except anthropic.APIStatusError as e:
        log.error("model call failed: HTTP %s", e.status_code)
        if e.status_code >= 500:
            raise LLMError("outage", "The AI service is having trouble right now. Please try again shortly.") from None
        raise LLMError("request", "The AI service could not handle the request.") from None
    except anthropic.APITimeoutError:
        log.warning("model call timed out")
        raise LLMError("timeout", "The AI service took too long to answer.") from None
    except anthropic.APIConnectionError:
        log.warning("model call failed: connection")
        raise LLMError("network", "Could not reach the AI service.") from None


def _common(effort_kind: str) -> dict[str, Any]:
    return {"model": model_name(), "output_config": {"effort": effort(effort_kind)},
            "betas": [FALLBACK_BETA], "fallbacks": "default"}


def _check_stop(msg: Any) -> None:
    if msg.stop_reason == "refusal":
        cat = getattr(getattr(msg, "stop_details", None), "category", None)
        log.warning("model refused (category=%s)", cat)
        raise LLMRefusal(cat)
    if msg.stop_reason == "max_tokens":
        raise LLMError("truncated", "The AI answer was cut off.")


def structured(system: str, user: str, schema: type[T], max_tokens: int = 32000) -> T:
    """One streamed call whose JSON output is constrained to `schema` and validated."""
    with _errors():
        with client().beta.messages.stream(
            max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}],
            output_format=schema, **_common("brief"),
        ) as stream:
            msg = stream.get_final_message()
    _check_stop(msg)
    parsed = msg.parsed_output
    if parsed is None:
        raise LLMError("bad_output", "The AI answer did not match the expected format.")
    return parsed


def _after_last_fallback(content: list[Any]) -> list[Any]:
    """With a fallback, content holds the declining model's partial output, a
    fallback block, then the answer. Keep only the answer."""
    idx = max((i for i, b in enumerate(content) if b.type == "fallback"), default=-1)
    return content[idx + 1:]


def answer_blocks(content: list[Any]) -> list[dict]:
    """Text blocks with their citations, as plain dicts (SDK-independent)."""
    out = []
    for b in _after_last_fallback(content):
        if b.type != "text":
            continue
        cites = []
        for c in b.citations or []:
            if getattr(c, "type", None) != "char_location":
                continue
            cites.append({"document_index": c.document_index, "document_title": c.document_title,
                          "cited_text": c.cited_text, "start": c.start_char_index, "end": c.end_char_index})
        out.append({"text": b.text, "citations": cites})
    return out


def stream_chat(system: str, messages: list[dict], max_tokens: int = 16000) -> Iterator[tuple[str, Any]]:
    """Stream a cited answer.

    Yields ("text", delta) while the answer is written, ("reset", None) when a
    fallback model takes over (discard text shown so far), then exactly one of
    ("done", {"blocks", "model", "usage"}) or ("refusal", category).
    Raises LLMError for service failures.
    """
    with _errors():
        with client().beta.messages.stream(
            max_tokens=max_tokens, system=system, messages=messages, **_common("chat"),
        ) as stream:
            for event in stream:
                if event.type == "text":
                    yield "text", event.text
                elif event.type == "content_block_start" and getattr(event.content_block, "type", None) == "fallback":
                    yield "reset", None
            msg = stream.get_final_message()
    try:
        _check_stop(msg)
    except LLMRefusal as r:
        yield "refusal", r.category
        return
    u = msg.usage
    yield "done", {"blocks": answer_blocks(msg.content), "model": msg.model,
                   "usage": {"input": u.input_tokens, "output": u.output_tokens,
                             "cache_read": getattr(u, "cache_read_input_tokens", None) or 0,
                             "cache_write": getattr(u, "cache_creation_input_tokens", None) or 0}}
