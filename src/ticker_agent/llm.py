"""Model access through the firm's AI gateway (OpenAI-compatible endpoint).

Configuration comes from the environment or a local .env file (never committed):
  PORTKEY_API_KEY, PORTKEY_BASE_URL, PORTKEY_MODEL
With no key set, callers fall back to an extractive (no-model) brief.
"""
from __future__ import annotations

import os
from pathlib import Path

from openai import OpenAI


def _load_dotenv() -> None:
    env = Path(__file__).resolve().parents[2] / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


def available() -> bool:
    return bool(os.environ.get("PORTKEY_API_KEY") and os.environ.get("PORTKEY_BASE_URL"))


def model_name() -> str:
    return os.environ.get("PORTKEY_MODEL", "")


def complete(system: str, user: str, max_tokens: int = 4000) -> str:
    key = os.environ["PORTKEY_API_KEY"]
    client = OpenAI(
        api_key=key,
        base_url=os.environ["PORTKEY_BASE_URL"],
        default_headers={"x-portkey-api-key": key},
        timeout=120.0,
        max_retries=2,
    )
    resp = client.chat.completions.create(
        model=model_name(),
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.1,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content or ""
