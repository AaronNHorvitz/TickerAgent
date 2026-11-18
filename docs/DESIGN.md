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
- Market data: Nasdaq public website data (quote, summary, daily history, stock list). No key; not a documented API, so it sits behind one module that a licensed feed replaces in production.
- Model: Claude Opus 5.5 through the Anthropic API on the owner's account, configured through `.env` (see `.env.example`). No key in code.

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
- AI service down, key missing, a refusal, or output that fails the schema twice: falls back to an extractive brief (first sentences of each cited section), labelled as such.
- Known gap: some filers (e.g. large banks) put MD&A in an annual-report exhibit; that section comes back thin and the brief says so.

## Tool, data, and deployment constraints

- Python 3.12, FastAPI + one static page, Anthropic SDK. No agent framework: the steps are fixed, so a deterministic pipeline is simpler, faster and auditable.
- SEC fair-access: declared User-Agent, under 10 req/s, 6-hour local cache in `data/cache` (git-ignored).
- Not investment advice: the prompt forbids recommendations and price targets; the page carries a disclaimer.

## Decisions and verification

- Pipeline over agent: the retrieval plan is fixed (quote + 3 filing types), so tool-calling adds latency and variance without benefit.
- Numbers from structured data, words from the model: the figures table is XBRL; the model may only restate numbers present in its cited excerpt, and a post-check enforces it.
- Section extraction: headings anchored to line start, longest span wins (skips table-of-contents hits). 8-K cover boilerplate is skipped; exhibit 99 (or the largest attachment) is appended.
- Verified with live data (no model): data path for AAPL, NVDA, TSLA, BRK.B, JPM; API on port 8010.
- Verified with a stand-in model (tests/test_brief.py, 6 passing): citation dropping, number flagging, JSON retry, service-failure fallback, ticker validation.
- Not yet verified: live model call. Needs the Anthropic API key (dev plan task 2).

See the README for running, testing and deployment.

## Decision log

- 2026-11-18: Market data moves from a public delayed chart endpoint to Nasdaq's quote, summary, history and stock-list data, adapting the owner's existing screener code. Adds company-name search and an exchange trade timestamp. Nasdaq's analyst price target is dropped to keep the no-recommendation rule.
- 2026-11-18: Model access moves from the interview gateway to the Anthropic API on the owner's account, using the Anthropic SDK. Chat uses Claude's built-in citations so every sentence maps to an exact quoted passage.
- 2026-11-18: Hosting target is an Amazon Lightsail container service; the image is built by GitHub Actions.
- 2026-11-18: Task 1 done. `nasdaq.py` (adapted from the owner's screener code) serves search over the 7,291-row stock list (15-minute memory cache), quote, summary and one year of daily prices (5-minute cache so chat turns see the same numbers). Summary keys or labels mentioning a target are dropped. Symbols are normalized: BRK/B for display and search, BRK-B for SEC, BRK.B in the quote URL (Nasdaq 404s on an encoded slash). Each Nasdaq part fails on its own and the brief renders from SEC data. `quote.py` removed. Verified with live data, no model: NVDA, AAPL and BRK/B briefs carry quote with trade time, 52-week range, market cap, sector and 252 daily rows; "berkshire" returns BRK/A and BRK/B. Unit tests use recorded responses in `tests/fixtures/`.
- 2026-11-18: Task 2 done. `llm.py` uses the Anthropic SDK (`anthropic` 2.10.0); the gateway client and `openai` dependency are gone. Model from `ANTHROPIC_MODEL` (default `claude-opus-5-5`), effort from `BRIEF_EFFORT` (medium) and `CHAT_EFFORT` (low), no sampling parameters. The brief call streams with structured outputs (`output_format=BriefOutput`), so the JSON is schema-checked by the API and by pydantic; the source-ID scheme, `_ground` and `_unverified` stay because citations cannot be combined with structured outputs. Every call sends `fallbacks: "default"` (beta `server-side-fallback-2026-07-01`) and checks `stop_reason` for `refusal` and `max_tokens` before reading content. SDK errors map, most specific first, to friendly messages; logs carry the error class only. AI briefs are kept 10 minutes per ticker so reloads cost nothing. Verified with a stand-in model and a fake SDK client (request shape, refusal, fallback, error mapping). Not yet verified live: no API key on the build machine.
