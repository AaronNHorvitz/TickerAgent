"""Reported figures: latest fiscal year only, latest filing wins."""
import json

from ticker_agent import sec


def _fact(start, end, val, filed):
    return {"start": start, "end": end, "val": val, "form": "10-K", "fp": "FY", "filed": filed, "accn": "x"}


def test_stale_line_items_are_dropped_and_restatements_win(monkeypatch):
    facts = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [
            _fact("2025-01-01", "2025-12-31", 110, "2026-03-02"),
            _fact("2024-01-01", "2024-12-31", 99, "2025-02-24"),
            _fact("2024-01-01", "2024-12-31", 100, "2026-03-02"),  # restated in the newer 10-K
        ]}},
        "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [
            {"end": "2017-12-31", "val": 5, "form": "10-K", "fp": "FY", "filed": "2018-02-26", "accn": "y"},
        ]}},
    }}}
    monkeypatch.setattr(sec, "_cached_get", lambda url, key: json.dumps(facts).encode())
    figs = sec.reported_figures(1)
    assert [f["metric"] for f in figs] == ["Revenue"]
    assert figs[0]["value"] == 110 and figs[0]["prior"] == 100
