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
- **Secondary: compliance.** Needs every statement to trace back to a public filing.
- **Secondary: the research team.** Needs coverage of off-list stocks without adding headcount.

## 3. Goal and success measures

**Goal:** an advisor walks into every client call informed in about 2 minutes, with every fact traceable to the filing it came from.

| Measure | Target for the pilot |
| --- | --- |
| Prep time per stock | From ~45 min to under 2 min (brief ready in under 60 s) |
| Accuracy | At least 95% of points rated correct in research-team spot checks |
| Traceability | 100% of brief points and chat answers carry a source citation |
| Ease of use | A new advisor gets a brief and a chat answer with no training |
| Adoption | At least 70% of pilot advisors use it weekly |
| Compliance | Sign-off on the brief format before wider rollout |

## 4. Solution

The advisor enters a ticker and gets a one-page brief:

1. **Quote:** price, day change, 52-week range, 12-month trend.
2. **Key figures:** revenue, net income, diluted EPS, operating cash flow, debt and cash for the latest fiscal year vs. prior, read from the company's structured filing data (XBRL).
3. **AI summary:** what the company does, what's new, what's driving results, key risks.
4. **Client questions:** three questions a client is likely to ask, with sourced answers.
5. **Sources:** every point links to the filing on SEC.gov.
6. **Chat with the data:** after the brief loads, the advisor asks follow-up questions in plain English ("Why did margins fall?", "What did the last 8-K say about the CEO?", "How has the stock moved since earnings?"). Answers draw on the same filings, figures and recent prices behind the brief, and cite their sources.

### Ease of use

- One screen: a ticker box, the brief, and a chat panel beside it. No menus, settings or modes.
- Suggested follow-up questions appear under the brief, so the advisor never faces an empty box.
- Plain-language answers sized for a phone call: short paragraphs, sources one click away.
- Works on a laptop and a phone browser.
- Each answer shows within about 15 seconds; the brief within 60.

### Trust requirements

- Reported figures come from structured filing data, never from the model.
- The model sees only filing excerpts, and every point must cite a source.
- Points without a valid source are removed before display.
- Numbers not found in the cited filing excerpt are flagged "check" for the advisor.
- No buy/sell/hold recommendations or price targets. Every brief carries a "not investment advice" note.
- Chat answers follow the same rules: cited sources, the number check, no recommendations. When the loaded data does not cover a question, the answer says so instead of guessing.
- Text inside filings is treated as data, never as instructions to the model.
- If the AI service fails, the brief still shows the quote, the figures and quoted filing excerpts, labelled as such.

## 5. Scope

### In scope (prototype)

- US-listed SEC registrants, looked up by ticker.
- The latest 10-K, any newer 10-Q, and 8-Ks from the last 120 days.
- A single web page for advisors with the brief and the chat, plus a JSON API for integration.
- Chat over the loaded data set: filing excerpts, reported figures, the quote and one year of daily prices.
- A public deployment on Amazon Lightsail (container service, HTTPS URL) and a public code repository.

### Out of scope (roadmap)

| Item | Why later |
| --- | --- |
| Licensed real-time quote feed | Needs the firm's market-data contract. The prototype uses a public delayed source behind a replaceable function. |
| CRM integration: briefs ready before scheduled client meetings | Needs access to the firm's systems. |
| "What changed since the last brief" alerts on held stocks | Builds on stored briefs. |
| Audit log of briefs generated and viewed | Needed for compliance at rollout. |
| Single sign-on and access control | Needed for production. |
| Chat that pulls more filings on request (older years, peers, full-text search across EDGAR) | Builds on the fixed data set once it has proven accurate. |
| Non-US and non-SEC filers | Different disclosure sources. |

## 6. Constraints and assumptions

- Data sources: SEC EDGAR public APIs. No API key or registration is required; SEC fair-access guidance asks for a declared client name and contact email, under 10 requests/second, and caching.
- AI model: Claude Sonnet 4.5 through an OpenAI-compatible gateway, configured through environment secrets.
- Hosting: Amazon Lightsail container service. Secrets are set as deployment environment variables and are never stored in the repository.
- Prep-time and accuracy targets are assumptions, to be confirmed in the pilot.
- Known limit: some filers (large banks, for example) put management's discussion in an attachment, so that section comes back thin. The brief says so rather than guessing.

## 7. Rollout

1. **Prototype (now):** brief and chat, public repo, deployed on Amazon Lightsail.
2. **Pilot (2 weeks, 10 advisors):** measure prep time, research-team spot checks, compliance review of the brief format.
3. **Production:** licensed quote feed, SSO, audit log, CRM integration.

## 8. Risks

| Risk | Mitigation |
| --- | --- |
| The AI misstates a fact | Required citations, number check, figures from structured data, advisor verifies flagged items |
| Advisor treats the brief as a recommendation | Prompt forbids recommendations; disclaimer on every brief; compliance sign-off |
| Data source outage or rate limits | Caching; the brief degrades section by section instead of failing |
| Cost per brief | One model call per brief (about 15k input tokens); repeat requests within 6 hours reuse cached filings |
