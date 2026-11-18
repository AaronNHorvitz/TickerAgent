"""Public-URL protection: per-visitor rate limit, daily AI cap, friendly errors."""
from fastapi.testclient import TestClient
from starlette.requests import Request

from ticker_agent import brief, gather, guard, llm, sec
from ticker_agent.app import app


def req(xff=None, host="10.0.0.9"):
    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request({"type": "http", "headers": headers, "client": (host, 1234)})


def test_client_ip_prefers_first_forwarded_entry():
    assert guard.client_ip(req("203.0.113.7, 10.1.1.1")) == "203.0.113.7"
    assert guard.client_ip(req()) == "10.0.0.9"


def test_rate_limiter_window():
    rl = guard.RateLimiter(2)
    assert rl.check("a", now=0) == 0 and rl.check("a", now=1) == 0
    assert rl.check("a", now=2) == 58          # third in the minute waits for the oldest to expire
    assert rl.check("b", now=2) == 0           # other visitors unaffected
    assert rl.check("a", now=60.5) == 0        # window slid


def test_daily_cap_resets_each_utc_day():
    cap = guard.DailyCap(2)
    assert cap.take("2026-11-18") and cap.take("2026-11-18") and not cap.take("2026-11-18")
    assert cap.remaining("2026-11-18") == 0
    assert cap.take("2026-11-19")
    assert not guard.DailyCap(0).take("2026-11-18")


def test_visitor_limit_returns_friendly_429(monkeypatch):
    monkeypatch.setattr(guard, "pages", guard.RateLimiter(2))
    monkeypatch.setattr("ticker_agent.app.build_brief", lambda t, **k: {"ok": True})
    c = TestClient(app)
    h = {"X-Forwarded-For": "198.51.100.1"}
    assert c.get("/api/brief/NVDA", headers=h).status_code == 200
    assert c.get("/api/brief/NVDA", headers=h).status_code == 200
    r = c.get("/api/brief/NVDA", headers=h)
    assert r.status_code == 429 and "Please wait" in r.json()["detail"] and int(r.headers["Retry-After"]) > 0
    assert c.get("/api/brief/NVDA", headers={"X-Forwarded-For": "198.51.100.2"}).status_code == 200
    r = c.post("/api/chat", headers=h, json={"ticker": "NVDA", "question": "q"})
    assert r.status_code == 429  # chat shares the visitor's budget


def test_search_limit(monkeypatch, nasdaq_recorded):
    monkeypatch.setattr(guard, "searches", guard.RateLimiter(1))
    c = TestClient(app)
    assert c.get("/api/search?q=nvda").status_code == 200
    assert c.get("/api/search?q=nvda").status_code == 429


def test_daily_cap_blocks_chat_with_429(monkeypatch):
    monkeypatch.setattr(guard, "ai_calls", guard.DailyCap(0))
    monkeypatch.setattr(llm, "available", lambda: True)
    r = TestClient(app).post("/api/chat", json={"ticker": "NVDA", "question": "Who is the CEO?"})
    assert r.status_code == 429 and "daily limit" in r.json()["detail"]


def test_daily_cap_turns_the_brief_extractive(monkeypatch, synthetic_stock):
    monkeypatch.setattr(guard, "ai_calls", guard.DailyCap(0))
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "structured", lambda *a, **k: (_ for _ in ()).throw(AssertionError("model called")))
    r = TestClient(app).get("/api/brief/NVDA")
    assert r.status_code == 200 and r.json()["meta"]["mode"] == "extractive"
    assert "Daily AI limit" in r.json()["meta"]["note"]


def test_unknown_ticker_and_sec_outage_messages(monkeypatch):
    c = TestClient(app)
    r = c.get("/api/brief/NVDA")  # SEC client is offline in tests
    assert r.status_code == 503 and "SEC EDGAR is not responding" in r.json()["detail"]
    monkeypatch.setattr(sec, "_cached_get", lambda url, key: b'{"0": {"ticker": "NVDA", "cik_str": 1, "title": "N"}}')
    r = c.get("/api/brief/ZZZZ")
    assert r.status_code == 404 and "isn't a ticker we can find" in r.json()["detail"]


def test_unexpected_errors_are_friendly_500(monkeypatch):
    def boom(t, **k):
        raise RuntimeError("secret detail sk-ant-xxxx")
    monkeypatch.setattr("ticker_agent.app.build_brief", boom)
    r = TestClient(app, raise_server_exceptions=False).get("/api/brief/NVDA")
    assert r.status_code == 500 and "sk-ant" not in r.text and "went wrong" in r.json()["detail"]


def test_logs_carry_no_secrets(monkeypatch, caplog):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-secret")
    import anthropic
    import httpx2
    rq = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")

    class C:
        beta = type("B", (), {"messages": type("M", (), {"stream": staticmethod(
            lambda **k: (_ for _ in ()).throw(anthropic.AuthenticationError("bad", response=httpx2.Response(401, request=rq), body=None)))})()})()
    monkeypatch.setattr(llm, "_client", C())
    with caplog.at_level("DEBUG"):
        try:
            llm.structured("s", "u", brief.BriefOutput)
        except llm.LLMError:
            pass
    assert caplog.records and "sk-ant-test-secret" not in caplog.text
