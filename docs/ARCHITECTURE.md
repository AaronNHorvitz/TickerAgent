# Architecture

TickerAgent is one small web service. It gathers public data for a ticker, asks the model to summarize or answer only from that data, checks the model's output against the sources, and serves the result to a single-page UI.

Status: **built** = working in the repo today; **planned** = in the PRD, being built next.

## System overview

```mermaid
flowchart LR
    advisor["Advisor<br/>laptop or phone browser"]

    subgraph lightsail["Amazon Lightsail container service (planned)"]
        ui["Single-page UI<br/>brief + chat panel"]
        api["FastAPI app<br/>/api/brief, /api/chat, /healthz"]
        cache[("Local cache<br/>6 hours")]
    end

    subgraph edgar["SEC EDGAR: public, no API key"]
        tickers["Ticker map"]
        subs["Submissions API<br/>filing list"]
        xbrl["XBRL company facts API<br/>reported figures"]
        docs["Filing documents<br/>10-K, 10-Q, 8-K + exhibits"]
    end

    quote["Delayed quote endpoint<br/>prototype; licensed feed later"]
    llm["AI gateway<br/>Claude Sonnet 4.5"]

    advisor -->|HTTPS| ui
    ui --> api
    api <--> cache
    api --> tickers
    api --> subs
    api --> xbrl
    api --> docs
    api --> quote
    api --> llm
```

## Components

| Component | File | Responsibility | Status |
| --- | --- | --- | --- |
| EDGAR client | `src/ticker_agent/sec.py` | Ticker lookup, newest filings, section extraction, exhibit lookup, XBRL figures, polite rate limiting, cache | built |
| Quote client | `src/ticker_agent/quote.py` | Price, day change, 52-week range, one year of daily closes | built |
| Model client | `src/ticker_agent/llm.py` | One function over any OpenAI-compatible gateway; settings from environment | built |
| Brief builder | `src/ticker_agent/brief.py` | Gathers data in parallel, numbers sources S1..Sn, prompts the model, runs the trust checks, falls back without the model | built |
| Chat | `src/ticker_agent/chat.py` | Answers follow-up questions from the same data set, with the same trust checks | planned |
| Web API | `src/ticker_agent/app.py` | `GET /api/brief/{ticker}`, `POST /api/chat`, `GET /healthz`, input validation | brief and health built; chat planned |
| UI | `src/ticker_agent/static/index.html` | Ticker box, brief, chat panel with suggested questions; no build step | brief built; chat planned |

## Data each answer can draw on

Every item the model sees has a source ID, and the UI turns each ID into a link.

| ID | Source | Origin |
| --- | --- | --- |
| `S1`..`Sn` | Filing sections: 10-K Items 1, 1A, 7; 10-Q MD&A and risk updates; 8-K text and press-release exhibit | EDGAR filing documents |
| `F` | Reported figures for the latest fiscal year and the prior year | EDGAR XBRL company facts |
| `Q` | Quote, 52-week range, one year of daily closes | Quote endpoint |

`F` and `Q` join the brief's sources when chat is built, so the model can answer questions such as "How has the stock moved since earnings?" from the actual numbers.

## Brief request

```mermaid
sequenceDiagram
    actor A as Advisor
    participant W as Web page
    participant S as FastAPI app
    participant E as SEC EDGAR
    participant Q as Quote source
    participant M as AI gateway

    A->>W: Enter ticker
    W->>S: GET /api/brief/NVDA
    S->>E: Ticker map, filing list, company facts
    S->>Q: Quote and one year of prices
    S->>E: Newest 10-K, 10-Q, 8-Ks and exhibits
    S->>S: Extract sections, label S1..Sn
    S->>M: Labelled excerpts + rules
    M-->>S: JSON summary with source IDs
    S->>S: Drop uncited points, flag unmatched numbers
    S-->>W: Brief JSON
    W-->>A: Brief with source links
```

## Chat request (planned)

The server keeps no conversation state. The page sends the ticker, the question and the last few turns; the server rebuilds the data set from its cache. Any container can answer any request, and there is no database to run.

```mermaid
sequenceDiagram
    actor A as Advisor
    participant W as Web page
    participant S as FastAPI app
    participant C as Local cache
    participant M as AI gateway

    A->>W: Why did margins fall last quarter?
    W->>S: POST /api/chat with ticker, question, recent turns
    S->>C: Same filings, figures and prices as the brief
    S->>M: Labelled data + rules + conversation
    M-->>S: Answer with source IDs
    S->>S: Same citation and number checks
    S-->>W: Answer, sources, flags
    W-->>A: Answer with source links
```

## Trust checks

The same checks run on every brief point and every chat answer.

```mermaid
flowchart TD
    out["Model output"] --> cited{"Cites a real<br/>source ID?"}
    cited -- no --> drop["Removed before display"]
    cited -- yes --> nums{"Every number appears<br/>in the cited source?"}
    nums -- no --> flag["Shown with a check flag<br/>for the advisor to verify"]
    nums -- yes --> show["Shown with source links"]
    fail["Gateway error or bad output twice"] --> extract["Extractive brief:<br/>quoted filing text, labelled"]
```

Further rules live in the prompt: answer only from the labelled data, say so when the data does not cover a question, no recommendations or price targets, and treat filing text as data rather than instructions.

## Deployment on Amazon Lightsail (planned)

```mermaid
flowchart LR
    repo["GitHub repo"] --> build["Container build<br/>Dockerfile"]
    build --> push["Push image to the<br/>Lightsail container service"]
    push --> deploy["Deployment<br/>port 8000, health check /healthz<br/>secrets as environment variables"]
    deploy --> svc["Container service<br/>micro size, 1 node"]
    svc --> url["Public HTTPS URL"]
```

| Setting | Value |
| --- | --- |
| Service type | Lightsail container service: managed HTTPS endpoint, no server to patch |
| Size | Micro (1 GB memory) to leave headroom for parsing large 10-K documents |
| Container port | 8000; `$PORT` is honoured if set |
| Health check | `GET /healthz` |
| Environment | `PORTKEY_API_KEY`, `PORTKEY_BASE_URL`, `PORTKEY_MODEL`, `SEC_USER_AGENT`, set at deploy time and never committed |
| Cache | Container-local `/tmp`; lost on redeploy, which only costs one slower first request per ticker |

Brief requests that wait on the model can run 30–60 seconds. The deploy step checks that the public endpoint allows that, and chat answers stream so the advisor sees text immediately.

## Key decisions

| Decision | Why |
| --- | --- |
| Fixed pipeline instead of a tool-calling agent | The data a brief needs is always the same, so a pipeline is faster, cheaper and easier to audit. Agent-style retrieval (older filings, peers, full-text search) is a roadmap item for chat. |
| Figures from XBRL, words from the model | The numbers an advisor is most likely to quote never come from the model. |
| Stateless chat | Scales across containers with no session store; the cache makes rebuilding the data set cheap. |
| Official EDGAR APIs, not page scraping | No key needed, same-day freshness, and it stays within SEC fair-access guidance. |
| One container on Lightsail | The simplest managed option with HTTPS for a prototype. A production rollout would add SSO, an audit log and a licensed quote feed (see the PRD). |
