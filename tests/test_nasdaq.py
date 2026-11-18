"""Nasdaq adapter against recorded responses (tests/fixtures/nasdaq_*.json)."""
import httpx

from ticker_agent import nasdaq


def test_search_by_name_finds_both_berkshire_share_classes(nasdaq_recorded):
    syms = [m["symbol"] for m in nasdaq.search("berkshire")]
    assert syms[:2] == ["BRK/A", "BRK/B"]


def test_search_accepts_every_share_class_spelling(nasdaq_recorded):
    for q in ("BRK/B", "brk.b", "BRK-B"):
        assert nasdaq.search(q)[0]["symbol"] == "BRK/B", q


def test_search_ranks_exact_ticker_then_name_words(nasdaq_recorded):
    assert nasdaq.search("nvda")[0]["symbol"] == "NVDA"
    # "apple" starts Apple's name; Pineapple only contains it, so it ranks last.
    syms = [m["symbol"] for m in nasdaq.search("apple")]
    assert syms[0] == "AAPL" and syms.index("APLE") < syms.index("MLP")


def test_stock_list_is_cached(nasdaq_recorded):
    nasdaq.search("nvidia")
    nasdaq.search("berkshire")
    assert sum("/screener/" in u for u in nasdaq_recorded) == 1


def test_symbol_spellings():
    assert nasdaq.display_symbol("brk.b") == "BRK/B"
    assert nasdaq.sec_symbol("BRK/B") == "BRK-B"
    assert nasdaq._quote_symbol("BRK/B") == "BRK.B"


def test_quote_summary_history_parse(nasdaq_recorded):
    q = nasdaq.quote("NVDA")
    assert q["price"] > 0 and q["trade_time"].endswith("ET") and q["exchange"]
    s = nasdaq.summary("NVDA")
    assert s["high_52w"] > s["low_52w"] > 0 and s["market_cap"] > 1e9 and s["sector"] == "Technology"
    h = nasdaq.history("NVDA")
    assert h == sorted(h, key=lambda r: r["date"]) and h[-1]["close"] > 0 and h[0]["date"][4] == "-"


def test_analyst_target_is_removed(nasdaq_recorded):
    s = nasdaq.summary("NVDA")
    assert "OneYrTarget" not in s["fields"]
    assert not any("target" in (f["label"] or "").lower() for f in s["fields"].values())
    assert "target" not in str(s).lower()


def test_unknown_symbol_and_outage_each_degrade_alone(monkeypatch, nasdaq_recorded):
    d = nasdaq.market_data("ZZZZ")  # recorded "Symbol not exists" reply
    assert d["quote"] is None and set(d["errors"]) == {"quote", "summary", "history"}

    def flaky(request):
        if request.url.path.endswith("/historical"):
            raise httpx.ConnectError("down")
        if request.url.path.endswith("/info"):
            return httpx.Response(200, json={"data": {"primaryData": {"lastSalePrice": "$10.00"}}})
        return httpx.Response(503)
    monkeypatch.setattr(nasdaq, "_client", httpx.Client(transport=httpx.MockTransport(flaky)))
    d = nasdaq.market_data("ABC")
    assert d["quote"]["price"] == 10.0
    assert d["summary"] is None and d["history"] is None
    assert d["errors"]["history"] == "Could not connect to Nasdaq."
    assert "503" in d["errors"]["summary"]


def test_missing_fields_are_none_not_errors(monkeypatch):
    def sparse(request):
        return httpx.Response(200, json={"data": {"summaryData": {
            "Exchange": {"label": "Exchange", "value": "NYSE"}, "Sector": {"label": "Sector", "value": "N/A"}}}})
    monkeypatch.setattr(nasdaq, "_client", httpx.Client(transport=httpx.MockTransport(sparse)))
    s = nasdaq.summary("X")
    assert s["exchange"] == "NYSE" and s["sector"] is None and s["high_52w"] is None and s["market_cap"] is None


def test_search_api_endpoint(nasdaq_recorded):
    from fastapi.testclient import TestClient
    from ticker_agent.app import app
    r = TestClient(app).get("/api/search", params={"q": "berkshire"})
    assert r.status_code == 200 and [m["symbol"] for m in r.json()["matches"]][:2] == ["BRK/A", "BRK/B"]


def test_search_api_when_nasdaq_down():
    from fastapi.testclient import TestClient
    from ticker_agent.app import app
    r = TestClient(app).get("/api/search", params={"q": "nvidia"})  # offline transport raises
    assert r.status_code == 200 and r.json()["matches"] == [] and "unavailable" in r.json()["error"]
