"""Behavior checks for grounding and fallback. The model is a stand-in here."""
import pytest
from pydantic import ValidationError

from ticker_agent import brief, llm, nasdaq, sec

SOURCES = [
    {"id": "S1", "label": "10-K", "section": "Risk factors (Item 1A)", "url": "u", "form": "10-K", "filed": "2026-01-01",
     "text": "Revenue grew to $1,234.5 million, up 18% from the prior year. Supply is concentrated in Taiwan."},
    {"id": "S2", "label": "8-K", "section": "8-K text", "url": "u", "form": "8-K", "filed": "2026-11-01",
     "text": "The Board appointed a new Chief Financial Officer effective November 3, 2026."},
]


def test_uncited_and_unknown_citations_are_dropped():
    s = brief.Summary(one_liner="x", key_risks=[
        brief.Point(point="Supply is concentrated in Taiwan.", sources=["S1"]),
        brief.Point(point="Something with no source.", sources=[]),
        brief.Point(point="Cites a source that does not exist.", sources=["S9"]),
    ])
    s, stats = brief._ground(s, SOURCES)
    assert [p.point for p in s.key_risks] == ["Supply is concentrated in Taiwan."]
    assert stats["dropped_uncited"] == 2


def test_numbers_must_appear_in_cited_text():
    s = brief.Summary(one_liner="x", performance_drivers=[
        brief.Point(point="Revenue reached $1,234.5 million, up 18%.", sources=["S1"]),
        brief.Point(point="Margins expanded to 74.2%.", sources=["S1"]),
        brief.Point(point="Revenue reached $1,234.5 million.", sources=["S2"]),  # right number, wrong source
    ])
    s, stats = brief._ground(s, SOURCES)
    ok, invented, miscited = s.performance_drivers
    assert ok.unverified_numbers == []
    assert invented.unverified_numbers == ["74.2"]
    assert miscited.unverified_numbers == ["1234.5"]
    assert stats["flagged_numbers"] == 2


def test_model_output_must_match_the_brief_schema():
    with pytest.raises(ValidationError):
        brief.BriefOutput.model_validate({"one_liner": "A chip company.", "key_risks": []})
    full = {"one_liner": "A chip company.", "snapshot": [], "recent_developments": [],
            "performance_drivers": [], "client_questions": [],
            "key_risks": [{"point": "Supply is concentrated in Taiwan.", "sources": ["S1"]}]}
    s = brief._to_summary(brief.BriefOutput.model_validate(full))
    assert s.key_risks[0].unverified_numbers == []


def _stub_data(monkeypatch, market=True):
    f = sec.Filing(form="8-K", filed="2026-11-01", period="", accession="0000000000-26-000001",
                   primary_doc="a.htm", items=["5.02"], cik=1)
    f.sections = {"8-K text": SOURCES[1]["text"]}
    monkeypatch.setattr(sec, "lookup_company", lambda t: {"ticker": "TEST", "cik": 1, "name": "Test Corp"})
    monkeypatch.setattr(sec, "recent_filings", lambda cik: [f])
    monkeypatch.setattr(sec, "load_sections", lambda f: f)
    monkeypatch.setattr(sec, "reported_figures", lambda cik: [])
    if market:
        monkeypatch.setattr(nasdaq, "market_data", lambda s: {"quote": {"price": 10.0}, "summary": None,
                                                              "history": None, "errors": {}})


def test_end_to_end_with_stand_in_model_retries_bad_output(monkeypatch):
    _stub_data(monkeypatch)
    good = brief.BriefOutput.model_validate({
        "one_liner": "Test Corp makes tests.", "snapshot": [], "performance_drivers": [], "key_risks": [],
        "recent_developments": [{"point": "New CFO effective November 3, 2026.", "sources": ["S1"]}],
        "client_questions": [{"question": "Who is the CFO?", "answer": "A new CFO started.", "sources": ["S1"]}],
    })
    calls = []

    def stand_in(system, user, schema, **k):
        calls.append(schema)
        if len(calls) == 1:
            raise llm.LLMError("bad_output", "The AI answer did not match the expected format.")
        return good
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "structured", stand_in)
    d = brief.build_brief("TEST")
    assert calls == [brief.BriefOutput, brief.BriefOutput]
    assert d["meta"]["mode"] == "ai"
    assert d["summary"]["recent_developments"][0]["unverified_numbers"] == []
    assert d["sources"][0]["id"] == "S1" and "text" not in d["sources"][0]


def test_service_failure_falls_back_to_extractive(monkeypatch):
    _stub_data(monkeypatch)
    monkeypatch.setattr(llm, "available", lambda: True)

    def boom(*a, **k):
        raise llm.LLMError("outage", "The AI service is having trouble right now.")
    monkeypatch.setattr(llm, "structured", boom)
    d = brief.build_brief("TEST")
    assert d["meta"]["mode"] == "extractive"
    assert "having trouble" in d["meta"]["note"] and "extractive" in d["meta"]["note"]
    assert d["summary"]["recent_developments"]


def test_refusal_falls_back_to_extractive(monkeypatch):
    _stub_data(monkeypatch)
    monkeypatch.setattr(llm, "available", lambda: True)

    def refuse(*a, **k):
        raise llm.LLMRefusal("cyber")
    monkeypatch.setattr(llm, "structured", refuse)
    d = brief.build_brief("TEST")
    assert d["meta"]["mode"] == "extractive" and "declined" in d["meta"]["note"]


def test_nasdaq_outage_leaves_the_brief_working(monkeypatch):
    _stub_data(monkeypatch, market=False)  # Nasdaq calls hit the offline transport
    monkeypatch.setattr(brief.llm, "available", lambda: False)
    d = brief.build_brief("TEST")
    assert d["market"]["quote"] is None and set(d["market"]["errors"]) == {"quote", "summary", "history"}
    assert d["summary"]["recent_developments"] and d["sources"][0]["id"] == "S1"
    assert any("Nasdaq" in n for n in d["meta"]["notes"])


def test_api_accepts_share_class_tickers(monkeypatch):
    from fastapi.testclient import TestClient
    from ticker_agent import app as app_mod
    seen = []
    monkeypatch.setattr(app_mod, "build_brief", lambda t, **k: seen.append(t) or {"ok": True})
    c = TestClient(app_mod.app)
    for t in ("BRK/B", "BRK.B", "brk-b"):
        assert c.get(f"/api/brief/{t}").status_code == 200
    assert seen == ["BRK/B", "BRK.B", "brk-b"]
    assert c.get("/api/brief/BRK/B/LONGER/PATH").status_code == 400
