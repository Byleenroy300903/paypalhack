# PayPal Nexus

**The Trust Network for Autonomous AI Commerce**

An Angular 20 + FastAPI hackathon application that discovers specialists, evaluates trust, negotiates a logo contract with Ollama Cloud, verifies delivery, and settles through PayPal sandbox buyer approval, authorization and capture. Elasticsearch indexes and searches audit events. Every backend simulation uses the real PayPal sandbox and Elasticsearch; if Ollama Cloud fails for any reason (for example HTTP 402, no usage credits), negotiation uses a labeled hardcoded offer and the run continues.

## Deploy on Vercel

Deploy the frontend and backend as **two projects from the same repository**:
backend Root Directory = repository root; frontend Root Directory = `frontend`
(enable including source files outside that directory). Vercel uses managed
PostgreSQL, such as Neon, while local development keeps SQLite. Set frontend
`NEXUS_API_URL` to the backend origin, and backend `PUBLIC_URL` / `CORS_ORIGINS`
to the frontend origin. See the [complete deployment guide](docs/DEPLOYMENT.md)
for exact settings, environment variables, PayPal return URLs and verification.
Vercel workflows run inside the request and replay results afterward; local
development retains background execution and live WebSockets.

## Run Locally

Requirements: Node 22.12+ (tested with 22.23), Python 3.12+ (tested with 3.12.8), and npm. SQLite needs no separate service. Configure the provider credentials for actual integrations; without PayPal credentials the API falls back to a simulated payment.

On a fresh checkout, create your local settings file with `Copy-Item .env.example .env`; keep `.env` private and enter provider credentials there.

```powershell
npm ci
npm start
```

Open http://localhost:4200. In another terminal, from the project root:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r backend\requirements.lock
.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Reload the frontend, or use **Preferences > Reconnect backend**. The simulation switches to the LangGraph engine. Angular proxies `/api` HTTP and WebSocket traffic to port 8000. API reference: http://localhost:8000/docs. After `npm run build`, FastAPI also serves the built application at http://localhost:8000.

To confirm the real providers from your network, open http://localhost:8000/api/integrations/check. It authenticates to Ollama Cloud, checks the Elasticsearch `nexus-events-v1` index, and requests a PayPal sandbox OAuth token without exposing credentials or creating a payment.

The root `.env` file contains private settings and is excluded from Git. Set `OLLAMA_API_KEY`/`OLLAMA_MODEL`, `ELASTICSEARCH_URL`/`ELASTICSEARCH_API_KEY`, and `PAYPAL_CLIENT_ID`/`PAYPAL_CLIENT_SECRET`. Set `PAYPAL_ENV=sandbox`; live mode is rejected. Use the Elasticsearch deployment URL, not its ingest endpoint or ingest token. `PUBLIC_URL` must match the browser origin (normally `http://localhost:4200`), including when testing with a VPN off. Restart the backend after changes. `DATABASE_URL` defaults to the root `nexus.db`; Render uses a persistent disk.

## Test the Actual Integrations

1. Start both services, open **Preferences**, and reconnect the backend. Provider flags indicate configuration, not successful connectivity.
2. Open **Live simulation**, leave **PayPal sandbox** selected, and create a logo mission. The feed records the configured Ollama model and its rationale. A configured Ollama error stops the mission visibly, without substituting a demo offer. Missing AI credentials are explicitly labeled deterministic demo.
3. After verification, click **Create PayPal order**, then **Open PayPal buyer approval**. Use a separate **sandbox personal buyer account**, not the seller account or a real PayPal login.
4. On return, click **I approved on PayPal - authorize**, then **Capture sandbox payment**. Approval is checked server-side; the return URL itself is not proof. Only a completed capture increases sandbox reputation. No real money moves.
5. In **Transactions**, inspect settlement/capture status, select a sandbox row to resume checkout, or use **Elasticsearch audit search** (e.g. `Agreement`). Search requires read access to `nexus-events-v1`; event logging requires write/create-index access. Indexing failures are logged on the backend; SQL events remain available.

Checkout capabilities are held in browser session storage, expire after 24 hours, and are bound to one run. Keep the same tab/session for the PayPal redirect. PayPal secrets and the optional operator token are never sent to the browser. Closing the browser session loses checkout access; an authenticated operator can recover through the API.

## What Works

- Six navigable views with responsive layouts, keyboard-accessible dialogs, reduced-motion support, Lucide icons, Angular Material controls, Tailwind, and ECharts canvas networking.
- A six-stage simulation with live negotiation messages, progress, logo download, verified-delivery approval, reputation changes and persistent browser transaction history.
- AG Grid sorting, column filtering, search, payment-state filter, pagination, and CSV export, backed by live transactions and agent scores when FastAPI is connected.
- A reputation-history view in the trust network, loaded from the backend ledger for the selected agent.
- FastAPI + a compiled LangGraph state machine; persistent SQL events, trust factors, negotiations, verification results, checkout sessions and reputation history.
- Replayable WebSocket events and HTTP recovery after connection loss.
- Ollama Cloud negotiation when configured, with Pydantic-validated JSON, exact contract-price enforcement and visible failures (no configured-provider fallback).
- A browser-only rogue-agent exercise that simulates a post-agreement price change and displays a governance risk report; the simulated attempt cannot change payment, reputation, or backend records.
- Elasticsearch event indexing with stable event IDs, failure isolation and a real audit-search UI/API.
- Connected PayPal **sandbox** Orders v2 checkout, authorization and capture, with per-run capabilities, server-checked buyer approval, amount matching and stable idempotency keys.

## Honest Boundaries

This is a runnable hackathon prototype, **not a certified production financial system**. Simulations make actual PayPal sandbox API calls using test funds and create the order automatically once delivery is verified. Headline overview statistics and initial agents are illustrative seed data. Browser history is local to this browser; backend runs are persisted independently. The artifact is a fixed Nexus SVG, not a generative design service. Three structural checks do not establish creative quality, intellectual property ownership, or task suitability.

The six workflow nodes are real LangGraph nodes. Ollama participates in negotiation only; other decisions are deterministic. Prompts for all six roles are extension points. The rogue-agent exercise is a separate, fixed browser simulation; it does not run hostile agent instructions or alter backend data. PayPal authorization/capture is **not escrow**. Checkout is explicitly initiated by the buyer after verification. The backend is hardwired to PayPal's sandbox API host; no live PayPal host or real-money mode exists.

The app starts with one worker. Runs use in-process tasks and become failed on restart, with recorded events retained. Before public financial deployment: add tenant identity, authorization on all records, distributed rate limiting, a durable job queue/checkpointer, database migrations, reconciliation/webhooks, real service-agent signatures, human dispute resolution, compliance review, abuse prevention and security testing. Never expose the sandbox operator token in a public browser bundle.

## Verification

```powershell
npm run build
npm test
.venv\Scripts\python.exe -m pytest backend\tests -q
```

Backend tests cover workflow events/replay, persistence, independent verification, checkout capability isolation/expiry, mocked provider requests, payment gating, idempotency and capture-gated reputation. Browser tests use mocked API responses and test checkout return/resume, visible provider failures, Elasticsearch search and mobile layout. They use bundled Playwright Chromium, or installed Edge on Windows; otherwise install Chromium with `npx playwright install chromium`. External connectivity and buyer approval must be tested separately with your credentials; these offline checks are not live-provider verification.

## Project Map

```text
src/app/
  app.component.ts/html    six views, navigation, controls and AG Grid
  nexus.service.ts         shared signals, browser workflow and WebSocket client
  network.component.ts     interactive ECharts trust graph
src/styles.css            responsive visual system and motion
backend/
  main.py                 REST, WebSocket, sandbox security and static hosting
  workflow.py             LangGraph nodes, trust formula and verification
  database.py             SQLAlchemy schema, checkout capabilities, SQLite engine and seed registry
  integrations.py         Ollama prompts/client, Elastic and PayPal adapter
  config.py               server-only environment configuration
  tests/test_workflow.py   behavior and payment-policy tests
docs/
  ARCHITECTURE.md          architecture, APIs, schema and event model
  DEPLOYMENT.md            Render and sandbox setup
  DEMO.md                 three-minute presentation
Dockerfile                multi-stage Angular/Python image
render.yaml               Render web service and persistent SQLite disk
```

Read [architecture](docs/ARCHITECTURE.md), [deployment](docs/DEPLOYMENT.md) and the [demo script](docs/DEMO.md) for the full technical and judging narrative. This independent prototype is not an official PayPal product.