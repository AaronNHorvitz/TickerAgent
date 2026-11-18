# Assignment and decisions

## User and business outcome

Scenario: Finance. A wealth management firm wants advisors to get up to speed on a stock quickly: current quote data plus a summary of key information from recent SEC filings.

Client story (fictional, for the pitch): a regional wealth firm, ~40 advisors, each serving 100–200 households. A client calls about a holding (often a legacy or concentrated position outside the firm's model portfolios). The advisor has minutes, not an hour.

Pain points:

1. Prep time. Reading a 10-K, the latest 10-Q and recent 8-Ks takes 30–60 minutes per name. Advisors skip it and walk in under-informed.
2. Material events are buried. CEO changes, acquisitions, new debt and earnings sit in 8-Ks and their exhibits that no one reads.
3. Research team bottleneck. Central research covers model-portfolio names, not every stock a client happens to hold.
4. Compliance risk. Advisors repeat facts from news sites or memory with no traceable source.

Outcome: a one-page brief in under a minute, where every statement links to the filing it came from.

## Inputs and available integrations

- SEC EDGAR (public, no key): ticker→CIK map, submissions index, filing documents, XBRL company facts.
- Quote: public delayed chart endpoint (prototype only; production swaps in the firm's licensed market-data feed behind the same function).
- Model: the provided AI gateway, OpenAI-compatible, configured through `.env` (see `.env.example`). No key in code.

## Required working capabilities

1. Ticker in → company resolved from SEC.
2. Quote: price, day change, 52-week range, 1-year trend.
3. Reported figures (revenue, net income, diluted EPS, operating cash flow, debt, cash) from XBRL, latest fiscal year vs prior. Deterministic, never model-generated.
4. Filing excerpts: 10-K Items 1, 1A, 7; newer 10-Q MD&A and risk updates; 8-Ks from the last 120 days with plain-language item labels and the press-release exhibit.
5. AI summary: one-liner, what the company does, what's new, what's driving results, key risks, likely client questions with answers.
6. Grounding: every point cites source IDs; uncited points are dropped; numbers not found in the cited excerpt are flagged "check" in the UI.

## Minimum successful workflow

Advisor types a ticker → brief renders with quote, figures, summary, citations that open the filing on SEC.gov.

## Expected examples and failure cases

- AAPL, NVDA, TSLA, BRK.B: full path verified against live SEC and quote data.
- Unknown ticker: 404 with a readable message.
- Quote outage: the brief still renders from filings with a quote-unavailable note.
- Gateway down, key missing, or bad JSON twice: falls back to an extractive brief (first sentences of each cited section), labelled as such.
- Known gap: some filers (e.g. large banks) put MD&A in an annual-report exhibit; that section comes back thin and the brief says so.

## Tool, data, and deployment constraints

- Python 3.12, FastAPI + one static page, OpenAI SDK pointed at the gateway. No agent framework: the steps are fixed, so a deterministic pipeline is simpler, faster and auditable.
- SEC fair-access: declared User-Agent, under 10 req/s, 6-hour local cache in `data/cache` (git-ignored).
- Not investment advice: the prompt forbids recommendations and price targets; the page carries a disclaimer.

## Decisions and verification

- Pipeline over agent: the retrieval plan is fixed (quote + 3 filing types), so tool-calling adds latency and variance without benefit.
- Numbers from structured data, words from the model: the figures table is XBRL; the model may only restate numbers present in its cited excerpt, and a post-check enforces it.
- Section extraction: headings anchored to line start, longest span wins (skips table-of-contents hits). 8-K cover boilerplate is skipped; exhibit 99 (or the largest attachment) is appended.
- Verified with live data (no model): data path for AAPL, NVDA, TSLA, BRK.B, JPM; API on port 8010.
- Verified with a stand-in model (tests/test_brief.py, 6 passing): citation dropping, number flagging, JSON retry, gateway-failure fallback, ticker validation.
- Not yet verified: live gateway call. Run one brief with the provided key before the demo.

See the README for running, testing and deployment.

## Separate stock lookup utility

At the owner's request, `../AgentTracker` is a standalone sibling utility with
an importable NASDAQ screener downloader, ticker/name search, and CLI. It is
independent of this application's quote adapter. Its source provenance, public
API, CLI commands, and operating limits are in
[the utility README](../../AgentTracker/README.md).

Verification on November 18, 2026: 21 synthetic-response checks passed; live
CLI searches for AAPL and Berkshire Hathaway succeeded. The provider supplied
no market timestamp, so freshness remains unverified. No model was used.
