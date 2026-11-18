# TickerAgent — Product Requirements

Status: draft for review

## 1. Problem

The client is a regional wealth management firm (fictional for this prototype) with about 40 advisors. Each advisor serves 100–200 households. When a client calls about a stock, the advisor needs to be up to speed in minutes, not hours.

| Pain point | Impact today |
| --- | --- |
| **Prep time.** Reading a 10-K, the latest 10-Q and recent 8-Ks takes about 45 minutes per stock. | Advisors skip prep and go into calls under-informed. |
| **Buried events.** CEO changes, acquisitions, new debt and earnings sit in 8-Ks and their exhibits. | Clients hear about material events before their advisor does. |
| **Research bottleneck.** The central research team covers the firm's model-portfolio stocks, not every legacy or concentrated position a client holds. | Coverage gaps on exactly the stocks clients worry about most. |
| **Compliance exposure.** Advisors repeat facts from news sites or memory. | Statements made to clients have no source trail. |

## 2. Users

- **Primary: the financial advisor.** Not a research analyst. Needs plain language, the latest events and likely client questions, fast.
- **Secondary: compliance.** Needs every statement to trace back to a public source.
- **Secondary: the research team.** Needs coverage of off-list stocks without adding headcount.

## 3. Goal and success measures

**Goal:** an advisor walks into every client call informed in about 2 minutes, able to ask follow-up questions, with every fact traceable to the filing or market data it came from.

| Measure | Target |
| --- | --- |
| Prep time per stock | From ~45 min to under 2 min (brief ready in under 60 s) |
| Accuracy | At least 95% of answers rated correct in research-team spot checks |
| Traceability | 100% of factual statements carry a citation to a source passage |
| Unsupported claims | 0 uncited figures shown as fact in the release eval set |
| Unanswerable questions | 100% answered "not in the loaded data" rather than guessed, in the release eval set |
| Ease of use | A new advisor gets a brief and a chat answer with no training |
| Adoption (pilot) | At least 70% of pilot advisors use it weekly |
| Compliance (pilot) | Sign-off on the brief and chat format before wider rollout |

## 4. Solution

### 4.1 Find the stock

The advisor types a ticker or part of a company name ("berkshire", "nvidia"). Matches come from Nasdaq's list of about 7,000 US-listed stocks, showing symbol, name, sector and last price, so share classes (BRK/A vs. BRK/B) are easy to tell apart.

### 4.2 The brief

1. **Market data (Nasdaq):** last sale with trade time, day change, 52-week high/low, previous close, market cap, dividend and yield, sector and industry, and a one-year daily price chart.
2. **Key figures (SEC XBRL):** revenue, net income, diluted EPS, operating cash flow, debt and cash for the latest fiscal year vs. prior.
3. **AI summary:** what the company does, what's new, what's driving results, key risks.
4. **Client questions:** three questions a client is likely to ask, with sourced answers.
5. **Sources:** every point links to its filing on SEC.gov.

### 4.3 Chat with the data

After the brief loads, the advisor asks follow-up questions in plain English, for example:

- "What did the November 8-K say about the CEO?"
- "Why did margins change last quarter?"
- "How has the stock moved since the last earnings release?"
- "What are the biggest risks for a client holding a concentrated position?"

Answers come from Claude using only the data loaded for that stock: the filing sections, the reported figures, the Nasdaq quote and one year of daily prices. Each answer streams in as it is written, cites the exact passages it relies on, and keeps the conversation context for follow-ups.

### 4.4 Ease of use

- One screen: a search box, the brief, and a chat panel beside it. No menus, settings or modes.
- Suggested follow-up questions appear under the brief, so the advisor never faces an empty box.
- Plain-language answers sized for a phone call: short paragraphs, the quoted source one tap away.
- Works on a laptop and a phone browser.
- Chat answers start appearing within about 3 seconds and finish within about 15; the brief is ready within 60.

### 4.5 No-hallucination requirements

1. **Closed book.** The model answers only from the documents loaded for the stock. It is told not to use outside knowledge, and the loaded set is listed in every answer's sources.
2. **Passage-level citations.** Chat uses Claude's built-in citations: each factual sentence links to the exact quoted passage it came from. The advisor can see the quote and open the filing.
3. **Numbers are checked.** Every number in an answer must appear in the passage it cites or in the market and figures data. Anything else is flagged "check" for the advisor.
4. **Uncited figures are never shown as fact.** In the brief, uncited points are removed. In chat, an uncited sentence that states a number or date is flagged "unverified".
5. **Say "I don't know".** When the loaded data does not cover a question, the answer says so and names what would (for example, "an older 10-K, which is not loaded").
6. **Numbers from code, not the model.** Prices and reported figures on the page are rendered directly from Nasdaq and SEC data.
7. **No advice.** No buy/sell/hold calls, price targets or predictions. Nasdaq's analyst price target is excluded from the data the model sees and from the page. Every brief and chat carries a "not investment advice" note.
8. **Filing text is data.** Instructions that appear inside filings are never followed.
9. **Measured before release.** An eval set of answerable, unanswerable, advice-seeking and instruction-injection questions runs before every deployment; the targets in section 3 gate the release.
10. **Graceful failure.** If the AI service fails, the brief still shows market data, figures and quoted filing excerpts, labelled as such, and chat says it is unavailable.

## 5. Scope

### In scope (prototype)

- US-listed stocks that file with the SEC, found by ticker or company name.
- The latest 10-K, any newer 10-Q, and 8-Ks from the last 120 days.
- Nasdaq market data: quote, summary, one year of daily prices, stock list.
- A single web page with the brief and the chat, plus a JSON API.
- Chat over the loaded data set, with the requirements in 4.5.
- Public deployment on Amazon Lightsail (container service, HTTPS URL) and a public code repository.
- Basic protection for a public URL: per-visitor rate limit and a daily cap on AI calls.

### Out of scope (roadmap)

| Item | Why later |
| --- | --- |
| Licensed market-data feed | The prototype uses Nasdaq's public website data, which has no service guarantee. Production uses the firm's licensed feed behind the same function. |
| CRM integration: briefs ready before scheduled client meetings | Needs access to the firm's systems. |
| "What changed since the last brief" alerts on held stocks | Builds on stored briefs. |
| Audit log of briefs and chats | Needed for compliance at rollout. |
| Single sign-on and access control | Needed for production. |
| Chat that pulls more filings on request (older years, peers, full-text search across EDGAR) | Builds on the fixed data set once it has proven accurate. |
| Non-US and non-SEC filers | Different disclosure sources. |

## 6. Constraints and assumptions

- **SEC EDGAR:** public APIs and filing documents. No API key or registration. SEC fair-access guidance asks for a declared client name and contact email, under 10 requests/second, and caching.
- **Nasdaq:** public quote, summary, historical and stock-list data from Nasdaq's website endpoints. No key. These are not a documented public API and can change without notice, so they sit behind one replaceable module and the page degrades section by section if they fail.
- **AI model:** Claude Opus 5.5 (`claude-opus-5-5`) through the Anthropic API on the owner's account. The model is set by an environment variable. The account carries a monthly spend limit.
- **Hosting:** Amazon Lightsail container service. Secrets are set as deployment environment variables and are never stored in the repository.
- Prep-time and accuracy targets are assumptions, to be confirmed in the pilot.
- Known limit: some filers (large banks, for example) put management's discussion in an attachment, so that section comes back thin. The brief says so rather than guessing.

## 7. Rollout

1. **Prototype (now):** brief and chat, public repo, deployed on Amazon Lightsail.
2. **Pilot (2 weeks, 10 advisors):** measure prep time, research-team spot checks, compliance review of the brief and chat format.
3. **Production:** licensed market data, SSO, audit log, CRM integration.

## 8. Risks

| Risk | Mitigation |
| --- | --- |
| The AI states something not in the sources | Closed-book prompt, passage-level citations, number check, uncited figures flagged, release eval set |
| Advisor treats an answer as a recommendation | Prompt forbids recommendations; analyst targets excluded; disclaimer on every brief and chat; compliance sign-off |
| Nasdaq endpoints change or block requests | One adapter module; market-data section degrades while filings and chat still work; licensed feed in production |
| SEC outage or rate limits | Caching; the brief degrades section by section instead of failing |
| A public URL runs up AI cost | Per-visitor rate limit, daily AI-call cap, account spend limit |
| Cost per brief or chat turn | One model call per brief or turn (about 15k input tokens); prompt caching reuses the loaded data across chat turns |
