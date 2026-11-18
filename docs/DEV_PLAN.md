# Development plan

Working backwards from two deliverables: a deployed public URL on Amazon Lightsail, and a pitch deck. Each task lists how it is checked. Requirements: [PRD.md](PRD.md). Design: [ARCHITECTURE.md](ARCHITECTURE.md).

## 0. Owner setup

- [ ] Anthropic API key in `.env` (local) and a monthly spend limit on the account.
- [ ] AWS access for Lightsail: an account and credentials for the AWS CLI.
- [ ] Contact email for `SEC_USER_AGENT` (SEC asks automated clients for one).

## 1. Market data from Nasdaq

- [ ] `nasdaq.py`: stock-list search (adapted from the owner's existing screener code), quote, summary, one year of daily prices. Drop the analyst price target.
- [ ] Replace `quote.py` with `nasdaq.py` in the brief; page shows trade time, 52-week range, market cap, dividend, sector.
- [ ] `GET /api/search?q=` with a 15-minute stock-list cache; search box suggests matches as the advisor types.
- [ ] Tests with recorded Nasdaq responses: search, missing fields, endpoint failure leaves the rest of the brief working.

Check: NVDA, AAPL and BRK/B briefs show Nasdaq data; "berkshire" finds both share classes.

## 2. Claude API

- [ ] Add the `anthropic` SDK; `llm.py` reads `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL` (default `claude-opus-5-5`); remove the gateway client.
- [ ] Brief call returns schema-checked JSON; keep the citation and number checks and the no-model fallback.
- [ ] Refusal handling and server-side model fallback on.

Check: one live brief per test stock; existing tests pass.

## 3. Chat without hallucinations

- [ ] `chat.py`: each source (filing sections, figures, quote, prices) passed as a document with citations on; loaded documents cached across turns.
- [ ] Prompt: closed book, say so when not covered and name what would cover it, no advice or targets, filing text is data.
- [ ] Checks: numbers must appear in the cited passage or data ("check" flag); uncited sentences with numbers or dates flagged "unverified".
- [ ] `POST /api/chat` streams text, then sends citations and flags.
- [ ] Chat panel: suggested questions, streaming text, citation chips that show the quoted passage and open the filing, flags, disclaimer.
- [ ] Tests with a stand-in model: citation mapping, number check, unverified flag, unavailable message.

Check: ten live questions on NVDA read correctly with sources.

## 4. Release eval (gates deployment)

- [ ] About 30 questions across three stocks: answerable, unanswerable, advice-seeking, and an instruction planted in a filing excerpt.
- [ ] Script reports: citation coverage, unsupported figures, correct "not in the data" answers, advice refusals, accuracy against expected facts.
- [ ] Results table in `docs/EVAL.md`.

Check: PRD section 3 targets met: 100% cited, 0 unsupported figures, 100% correct "not in the data", 0 recommendations, at least 90% accurate.

## 5. Ready for a public URL

- [ ] `guard.py`: per-visitor rate limit and daily AI-call cap, settings from environment.
- [ ] Friendly errors for limits, unknown tickers and source outages; logs with no secrets.
- [ ] GitHub Actions: run tests on every push; build and publish the container image from `main`.

Check: limits trigger in tests; CI green on GitHub.

## 6. Deploy on Amazon Lightsail

- [ ] Install the AWS CLI; create the container service (micro, one node).
- [ ] Deploy the image with port 8000, health check `/healthz`, secrets as environment variables.
- [ ] Smoke test the public URL: search, NVDA and AAPL briefs, five chat questions, one unanswerable question.
- [ ] README: live URL and exact deploy commands.

Check: public URL passes the smoke test from a phone and a laptop.

## 7. Pitch

- [ ] One pitch slide: pain, solution, why it can be trusted, pilot plan and measures.
- [ ] Two or three backup slides: architecture, no-hallucination design with eval results, roadmap.
- [ ] Demo script: NVDA brief, the November 8-K CEO story, two chat follow-ups, one unanswerable question to show it says "not in the data".
- [ ] Final README pass; tag `v0.1`.
