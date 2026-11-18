"""SEC EDGAR access: ticker lookup, recent filings, filing text, reported figures.

Everything here is deterministic. The model never produces a number that is
shown as a reported figure; those come from the company's XBRL data.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

import httpx

# SEC asks automated clients to identify themselves. Override per deployment.
USER_AGENT = os.environ.get("SEC_USER_AGENT", "TickerAgent prototype research@example.com")
CACHE_DIR = Path(os.environ.get("BRIEF_CACHE_DIR", Path(__file__).resolve().parents[2] / "data" / "cache"))
CACHE_TTL_S = 6 * 3600

_client = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30.0, follow_redirects=True)

# Public 8-K item codes -> plain-language labels for advisors.
EIGHT_K_ITEMS = {
    "1.01": "Entered a material agreement",
    "1.02": "Ended a material agreement",
    "1.03": "Bankruptcy or receivership",
    "2.01": "Completed an acquisition or sale of assets",
    "2.02": "Earnings results",
    "2.03": "New debt obligation",
    "2.05": "Restructuring / exit costs",
    "2.06": "Material impairment",
    "3.01": "Exchange listing notice",
    "4.01": "Auditor change",
    "4.02": "Prior financials no longer reliable",
    "5.02": "Executive or director change",
    "5.03": "Bylaw / charter amendment",
    "5.07": "Shareholder vote results",
    "7.01": "Reg FD disclosure",
    "8.01": "Other material event",
    "9.01": "Financial statements and exhibits",
}


def _cached_get(url: str, key: str) -> bytes:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / re.sub(r"[^A-Za-z0-9_.-]", "_", key)
    if path.exists() and time.time() - path.stat().st_mtime < CACHE_TTL_S:
        return path.read_bytes()
    resp = _client.get(url)
    resp.raise_for_status()
    time.sleep(0.12)  # stay well under SEC's 10 requests/second guidance
    path.write_bytes(resp.content)
    return resp.content


def lookup_company(ticker: str) -> dict:
    data = json.loads(_cached_get("https://www.sec.gov/files/company_tickers.json", "company_tickers.json"))
    t = re.sub(r"[./]", "-", ticker.strip().upper())
    for row in data.values():
        if row["ticker"].upper() == t:
            return {"ticker": row["ticker"], "cik": int(row["cik_str"]), "name": row["title"]}
    raise LookupError(f"'{ticker.strip().upper()}' isn't a ticker we can find among SEC filers. "
                      "Check the symbol, or search by company name.")


@dataclass
class Filing:
    form: str
    filed: str
    period: str
    accession: str
    primary_doc: str
    items: list[str]
    cik: int
    sections: dict[str, str] = field(default_factory=dict)

    @property
    def url(self) -> str:
        acc = self.accession.replace("-", "")
        return f"https://www.sec.gov/Archives/edgar/data/{self.cik}/{acc}/{self.primary_doc}"

    @property
    def folder(self) -> str:
        return f"https://www.sec.gov/Archives/edgar/data/{self.cik}/{self.accession.replace('-', '')}"

    def item_labels(self) -> list[str]:
        return [EIGHT_K_ITEMS.get(i, f"Item {i}") for i in self.items if i != "9.01"]


def recent_filings(cik: int, max_8k: int = 4, eight_k_days: int = 120) -> list[Filing]:
    """Latest 10-K, latest 10-Q (if newer than the 10-K) and recent 8-Ks."""
    sub = json.loads(_cached_get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", f"sub_{cik}.json"))
    r = sub["filings"]["recent"]
    rows = [
        Filing(
            form=r["form"][i], filed=r["filingDate"][i], period=r["reportDate"][i],
            accession=r["accessionNumber"][i], primary_doc=r["primaryDocument"][i],
            items=[x for x in (r["items"][i] or "").split(",") if x], cik=cik,
        )
        for i in range(len(r["form"]))
    ]
    out: list[Filing] = []
    tenk = next((f for f in rows if f.form in ("10-K", "20-F", "40-F")), None)
    tenq = next((f for f in rows if f.form == "10-Q"), None)
    if tenk:
        out.append(tenk)
    if tenq and (not tenk or tenq.filed > tenk.filed):
        out.append(tenq)
    cutoff = time.strftime("%Y-%m-%d", time.gmtime(time.time() - eight_k_days * 86400))
    eights = [f for f in rows if f.form == "8-K" and f.filed >= cutoff]
    # Prefer substantive 8-Ks (not exhibit-only) and keep the newest.
    eights = [f for f in eights if f.item_labels()][:max_8k]
    out.extend(eights)
    return out


class _TextExtractor(HTMLParser):
    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section"}
    SKIP = {"script", "style", "ix:header", "head"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip_depth += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip_depth:
            self.skip_depth -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip_depth:
            self.parts.append(data)


def html_to_text(raw: bytes) -> str:
    p = _TextExtractor()
    p.feed(raw.decode("utf-8", errors="ignore"))
    text = "".join(p.parts).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def _between(text: str, start: str, end: str) -> str:
    """Longest span from a start heading to the next end heading.

    Filings repeat headings in the table of contents; the real section is the
    longest match, which skips the short TOC hit.
    """
    best = ""
    for m in re.finditer(r"(?m)^[ \t]*(?:" + start + ")", text, flags=re.I):
        e = re.search(end, text[m.end():], flags=re.I)
        span = text[m.start(): m.end() + (e.start() if e else 60000)]
        if len(span) > len(best):
            best = span
    return best


def _clip(s: str, n: int) -> str:
    s = s.strip()
    return s if len(s) <= n else s[:n] + "\n[...truncated for length...]"


def load_sections(f: Filing, budget: int = 14000) -> Filing:
    text = html_to_text(_cached_get(f.url, f"doc_{f.accession}_{f.primary_doc}"))
    if f.form in ("10-K", "20-F", "40-F"):
        f.sections["Business overview (Item 1)"] = _clip(_between(text, r"item\s*1\.?\s*business", r"item\s*1a\.?\s*risk"), budget // 3)
        f.sections["Risk factors (Item 1A)"] = _clip(_between(text, r"item\s*1a\.?\s*risk\s*factors", r"item\s*1b|item\s*1c|item\s*2\.?\s*propert"), budget)
        f.sections["MD&A (Item 7)"] = _clip(_between(text, r"item\s*7\.?\s*management", r"item\s*7a|item\s*8\.?\s*financial"), budget)
    elif f.form == "10-Q":
        f.sections["MD&A (Part I, Item 2)"] = _clip(_between(text, r"item\s*2\.?\s*management", r"item\s*3\.?\s*quantitative|item\s*4\.?\s*controls"), budget)
        f.sections["Risk factor updates (Part II, Item 1A)"] = _clip(_between(text, r"item\s*1a\.?\s*risk\s*factors", r"item\s*2\.?\s*unregistered|item\s*5|item\s*6"), budget // 3)
    else:  # 8-K: the cover is short; the press release usually sits in exhibit 99.
        first_item = re.search(r"(?m)^[ \t]*item\s*\d\.\d\d", text, flags=re.I)
        body = text[first_item.start():] if first_item else text
        if "2.02" in f.items or "7.01" in f.items or "8.01" in f.items or len(body) < 4000:
            body += "\n\n" + _exhibit_99_text(f)
        f.sections["8-K text"] = _clip(body, 7000)
    f.sections = {k: v for k, v in f.sections.items() if len(v) > 200}
    if not f.sections:  # extraction failed; fall back to the opening of the document
        f.sections["Document text"] = _clip(text, budget // 2)
    return f


def _exhibit_99_text(f: Filing) -> str:
    try:
        idx = json.loads(_cached_get(f.folder + "/index.json", f"idx_{f.accession}.json"))
    except Exception:
        return ""
    files = [i for i in idx.get("directory", {}).get("item", [])
             if i.get("name", "").lower().endswith((".htm", ".html"))
             and i["name"] != f.primary_doc and not re.match(r"R\d+\.htm", i["name"])
             and "index" not in i["name"].lower()]
    if not files:
        return ""
    # Exhibit 99.x when the name says so; otherwise the largest attachment (usually the press release).
    pick = next((i for i in files if "99" in i["name"]), None) or max(files, key=lambda i: int(i.get("size") or 0))
    return html_to_text(_cached_get(f"{f.folder}/{pick['name']}", f"ex_{f.accession}_{pick['name']}"))


# ---- Reported figures (XBRL company facts) ---------------------------------
_CONCEPTS = {
    "Revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"],
    "Net income": ["NetIncomeLoss", "ProfitLoss"],
    "Diluted EPS": ["EarningsPerShareDiluted"],
    "Operating cash flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "Long-term debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "Cash & equivalents": ["CashAndCashEquivalentsAtCarryingValue"],
}


def reported_figures(cik: int) -> list[dict]:
    """Latest annual (10-K) values with prior-year comparison, straight from XBRL."""
    try:
        facts = json.loads(_cached_get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json", f"facts_{cik}.json"))
    except Exception:
        return []
    gaap = facts.get("facts", {}).get("us-gaap", {})
    out = []
    for label, names in _CONCEPTS.items():
        best = None
        for name in names:
            units = gaap.get(name, {}).get("units", {})
            vals = units.get("USD") or units.get("USD/shares") or []
            annual = [v for v in vals if v.get("form") == "10-K" and v.get("fp") == "FY"
                      and (("start" not in v) or _days(v["start"], v["end"]) > 300)]
            if not annual:
                continue
            by_end = {}
            for v in sorted(annual, key=lambda v: v.get("filed", "")):
                by_end[v["end"]] = v  # later filings overwrite restated values
            ends = sorted(by_end)
            cur = by_end[ends[-1]]
            prev = by_end[ends[-2]] if len(ends) > 1 else None
            if best is None or cur["end"] > best[0]["end"]:
                best = (cur, prev)
        if best:
            cur, prev = best
            out.append({
                "metric": label, "period_end": cur["end"], "value": cur["val"],
                "prior": prev["val"] if prev else None,
                "is_per_share": label == "Diluted EPS", "accession": cur.get("accn"),
            })
    # A company can stop reporting a line item (BRK's cash line ends in 2017).
    # Show only figures from the latest fiscal year so nothing stale sits next
    # to current numbers; 31 days allows for 52/53-week fiscal calendars.
    if out:
        latest = max(r["period_end"] for r in out)
        out = [r for r in out if _days(r["period_end"], latest) <= 31]
    return out


def _days(a: str, b: str) -> int:
    ta = time.mktime(time.strptime(a, "%Y-%m-%d"))
    tb = time.mktime(time.strptime(b, "%Y-%m-%d"))
    return int((tb - ta) / 86400)
