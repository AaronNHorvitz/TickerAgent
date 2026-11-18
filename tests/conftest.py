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


@pytest.fixture
def synthetic_stock(monkeypatch, nasdaq_recorded):
    """NVDA from synthetic SEC data plus recorded Nasdaq responses."""
    fx = fixture("sec_synthetic.json")
    filings = []
    for f in fx["filings"]:
        fl = sec.Filing(form=f["form"], filed=f["filed"], period=f["period"], accession=f["accession"],
                        primary_doc=f["primary_doc"], items=f["items"], cik=fx["company"]["cik"])
        fl.sections = dict(f["sections"])
        filings.append(fl)
    monkeypatch.setattr(sec, "lookup_company", lambda t: dict(fx["company"]))
    monkeypatch.setattr(sec, "recent_filings", lambda cik: filings)
    monkeypatch.setattr(sec, "load_sections", lambda f: f)
    monkeypatch.setattr(sec, "reported_figures", lambda cik: [dict(x) for x in fx["figures"]])
    return gather.load("NVDA")
