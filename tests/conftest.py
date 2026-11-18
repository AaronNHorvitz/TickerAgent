import json
from pathlib import Path

import httpx
import pytest

from ticker_agent import brief, gather, nasdaq, sec

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(autouse=True)
def _fresh_caches(monkeypatch):
    """No test reuses another's cached data, and no test reaches the network."""
    nasdaq.clear_cache()
    brief.clear_cache()
    gather.clear_cache()

    def offline(request):
        raise httpx.ConnectError(f"tests are offline: {request.url}")
    monkeypatch.setattr(nasdaq, "_client", httpx.Client(transport=httpx.MockTransport(offline)))
    monkeypatch.setattr(sec, "_client", httpx.Client(transport=httpx.MockTransport(offline)))
    yield
    nasdaq.clear_cache()
    brief.clear_cache()
    gather.clear_cache()


@pytest.fixture
def nasdaq_recorded(monkeypatch):
    """Serve recorded Nasdaq responses; returns the list of requested URLs."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        path = request.url.path
        if path.endswith("/screener/stocks"):
            return httpx.Response(200, json=fixture("nasdaq_screener.json"))
        if "/quote/NVDA/" in path:
            kind = path.rsplit("/", 1)[-1]
            name = {"info": "nasdaq_info_NVDA.json", "summary": "nasdaq_summary_NVDA.json",
                    "historical": "nasdaq_history_NVDA.json"}[kind]
            return httpx.Response(200, json=fixture(name))
        return httpx.Response(200, json=fixture("nasdaq_not_found.json"))
    monkeypatch.setattr(nasdaq, "_client", httpx.Client(transport=httpx.MockTransport(handler)))
    return seen
