# Deployment

## Vercel: Separate Frontend and Backend

Create **two Vercel projects connected to the same Git repository**. No Docker or
Uvicorn start command is needed. SQLite remains the local default, but Vercel
requires managed PostgreSQL: deployed files are read-only and temporary storage
is neither durable nor shared. Existing local SQLite data is not automatically
copied; the cloud database starts with the seed agents.

### 1. Create a database

Create a Neon PostgreSQL database at <https://neon.tech>, either directly or
through Vercel Marketplace. Copy its **pooled connection string**, including
`sslmode=require`. Keep it private. Free-tier limits and pricing can change.

### 2. Deploy the backend first

Import the repository as a Vercel project (for example `nexus-api`):

| Setting | Value |
| --- | --- |
| Root Directory | Repository root (leave empty) |
| Framework Preset | FastAPI |
| Build Command | Empty; root `vercel.json` configures this |
| Output Directory | Default; do not set an Angular output directory |
| Python | 3.12, pinned by `.python-version` |

The root `requirements.txt` installs the locked backend dependencies, and
`pyproject.toml` identifies `backend.main:app` as the entrypoint. Do not run
`npm run build` in the backend project.

Add these **backend-only** environment variables for Production:

```text
DATABASE_URL=postgresql://USER:PASSWORD@YOUR-POOLED-HOST/neondb?sslmode=require
PUBLIC_URL=https://YOUR-FRONTEND.vercel.app
CORS_ORIGINS=https://YOUR-FRONTEND.vercel.app
STEP_DELAY=0
PAYPAL_ENV=sandbox
PAYPAL_CLIENT_ID=YOUR_SANDBOX_CLIENT_ID
PAYPAL_CLIENT_SECRET=YOUR_SANDBOX_CLIENT_SECRET
OLLAMA_API_KEY=YOUR_OLLAMA_KEY
OLLAMA_MODEL=gpt-oss:120b
OLLAMA_TIMEOUT=90
ELASTICSEARCH_URL=YOUR_ELASTICSEARCH_ENDPOINT
ELASTICSEARCH_API_KEY=YOUR_ELASTICSEARCH_KEY
```

Ollama and Elasticsearch are optional. PayPal credentials are required for
sandbox checkout; without them only explicitly selected demo payment works.
`SANDBOX_API_TOKEN` is an optional server-side operator override; never add it
to the frontend. Vercel automatically supplies `VERCEL=1`.

If you do not yet know the frontend URL, use the expected project domain and
correct it after step 3. Deploy, then open
`https://YOUR-BACKEND.vercel.app/api/health` and `/docs`.
Startup creates the schema and seed records. `/api/health` must return
`status: "ok"` and `workflow_transport: "request"`.

### 3. Deploy the frontend

Import the **same repository again** as a second project (for example
`nexus-web`):

| Setting | Value |
| --- | --- |
| Root Directory | `frontend` |
| Include source files outside Root Directory in the Build Step | **Enabled** |
| Framework Preset | Other |
| Node.js | 22.x |
| Install Command | From `frontend/vercel.json`: `npm --prefix .. ci` |
| Build Command | From config: `npm --prefix .. run build -- --output-path frontend/dist` |
| Output Directory | `dist/browser` |

The `frontend` directory holds deployment configuration only; Angular source and
the npm lockfile stay in the repository root.

Set this **frontend-only** environment variable before deploying:

```text
NEXUS_API_URL=https://YOUR-BACKEND.vercel.app
```

Use the backend origin only, **without `/api`**. This public URL is embedded at
build time, so redeploy the frontend whenever it changes. Do not put database,
PayPal, Ollama or Elasticsearch credentials in this project. Missing or invalid
backend URL configuration fails the Vercel frontend build explicitly.

### 4. Connect the final domains

In the backend project's settings, set:

```text
PUBLIC_URL=https://YOUR-ACTUAL-FRONTEND.vercel.app
CORS_ORIGINS=https://YOUR-ACTUAL-FRONTEND.vercel.app
```

Use exact origins with no paths or trailing slash. `PUBLIC_URL` is where PayPal
returns the buyer, **not the backend URL**. `CORS_ORIGINS` accepts comma-separated
trusted origins if you also need a custom domain or local frontend. Redeploy
the backend after changing these values.

The backend must be publicly reachable by the browser: Vercel Deployment
Protection must not intercept API requests/preflight with a login page. Check
the project's protection settings. CORS is not authentication; this hackathon
API has no tenant login and should use sandbox credentials only.

For previews, explicitly configure the frontend preview's `NEXUS_API_URL` and
allow its exact origin on the intended backend. Do not allow arbitrary
`*.vercel.app` origins. Use a separate database/backend for isolated previews;
otherwise preview runs share production sandbox data.

### 5. Verify the connected deployment

1. Open the frontend and reconnect under **Preferences**. It should show
   **FastAPI engine connected**.
2. Check browser Network requests target the backend domain without CORS errors.
3. Run a logo mission. On Vercel, the API completes the workflow before returning;
   the UI then replays persisted events using HTTP, without requiring WebSockets.
   The event feed is not streamed live during that request.
4. Verify logo download, transactions, audit search (if configured), and reload
   persistence.
5. Complete PayPal sandbox approval using a separate sandbox buyer account.
   Confirm it returns to the frontend, then authorize and capture in the same
   browser session. Only a completed capture increases sandbox reputation.
6. Inspect backend logs and `/api/integrations/check` for provider connectivity.

The function limit is configured to 300 seconds, with a 240-second workflow
deadline and a 270-second browser request timeout. Use Fluid compute and verify
your plan supports that duration. `STEP_DELAY=0` avoids artificial waits.
Network interruptions, process termination or redeploys can still interrupt
work; this is **not a durable job queue**. Cold starts do not mark another
instance's runs failed. A forcibly terminated run may remain `running`; inspect
logs and start a new mission rather than assuming it completed. PostgreSQL
coordinates payment operations across instances; stable PayPal request IDs
still protect provider retries.

Schema creation is automatic, schema migration is not. Back up the database
and introduce migrations before changing deployed tables. Local tests do not
prove Vercel, Neon or credentialed provider connectivity.

References:
[FastAPI on Vercel](https://vercel.com/docs/frameworks/backend/fastapi),
[monorepos](https://vercel.com/docs/monorepos),
[function limits](https://vercel.com/docs/functions/limitations).

## Render Alternative

## Deployment Shape

One Docker web service serves the compiled Angular SPA, REST endpoints and WebSockets on the same origin. SQLite stores the workflow and checkout-session tables on a persistent Render disk. Elastic Cloud and Ollama Cloud are configured external integrations. This avoids cross-origin WebSocket and frontend API URL configuration.

1. Push the repository to your Git provider. No credentials should be committed.
2. In Render, choose **New > Blueprint** and select the repository's `render.yaml`.
3. Review the paid Starter web-service plan and persistent disk; the blueprint creates billable resources.
4. Set `PUBLIC_URL` to the final HTTPS service URL and `CORS_ORIGINS` to that exact origin. Set optional integration values or leave them empty.
5. Add an Ollama Cloud API key and a cloud-available model name to enable model negotiation. Add Elasticsearch URL/API key for searchable logs.
6. Deploy. The multi-stage Dockerfile runs `npm ci`, builds Angular, installs locked Python dependencies and starts one Uvicorn worker as a non-root user.
7. Verify `/api/health`, `/docs`, the overview and a full simulation. Inspect health response mode flags; configured does not mean an external provider has been tested.

Do not increase Uvicorn workers or Render instance count without replacing in-process workflow execution and sandbox payment locks. Startup marks interrupted runs failed. Database events and previous transactions survive restarts; graph execution does not automatically resume. Set up database backups, retention policies and migrations before handling meaningful persistent data.

## PayPal Sandbox Setup

1. In the [PayPal Developer Dashboard](https://developer.paypal.com/dashboard/), create or select a REST app under **Sandbox**. Copy its sandbox client ID and secret, and use a separate sandbox personal account as the buyer.
2. Set `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET` and `PAYPAL_ENV=sandbox` in the root `.env`, or Render environment settings. An optional strong `SANDBOX_API_TOKEN` enables operator recovery; never enter it in a public browser bundle. Restart the backend after local settings change.
3. In the UI run a logo mission to completion. The API accepts `payment_mode: "sandbox"`; it returns a random `checkout_token` once, with only its SHA-256 hash stored server-side. The UI keeps it in session storage. Capabilities are bound to one run and expire after 24 hours.
4. Click **Create PayPal order**, then **Open PayPal buyer approval**. Alternatively call `POST /api/paypal/{run_id}/order` with an `Authorization` bearer header containing the per-run checkout token or operator token. Open the returned PayPal `payer-action`/`approve` link in the same browser session and approve using a separate sandbox buyer account.
5. After PayPal returns to `PUBLIC_URL`, click **I approved on PayPal - authorize**, or call `POST /api/paypal/{run_id}/authorize`. The backend fetches the order from PayPal and checks approval, run ID, currency and exact contract amount before authorizing. Returning from PayPal does not by itself approve or settle anything.
6. Click **Capture sandbox payment**, or call `POST /api/paypal/{run_id}/capture`. The backend checks completed status, currency and amount. Capture persistence and the single reputation update commit together. The transaction center shows settlement and capture references.
7. Inspect the sandbox buyer/seller transaction in the Developer Dashboard. Repeating an operation returns its persisted result; stable `PayPal-Request-Id` values protect retries if a provider response is lost.

The adapter always calls `api-m.sandbox.paypal.com`; `PAYPAL_ENV=live` is rejected. PayPal client credentials and the operator token remain server-side. The browser receives only its per-run checkout capability and sanitized payment state. Authorization is not escrow: PayPal recommends capturing an authorization within three days for the honor period, and authorizations may expire after 29 days.

Sandbox missions create the PayPal order automatically after verified delivery and wait for buyer approval; reputation stays unchanged until completed capture. Sandbox payment references persist under `transactions.payment.sandbox`; no buyer credentials are stored. Selecting a sandbox transaction resumes checkout only in the owning browser session (or through authenticated operator recovery). This integration does not implement marketplace payouts, webhooks, reconciliation or live seller onboarding.

## Local Infrastructure

SQLite needs no separate service. Local runs use the root `nexus.db`; Render uses `/var/data/nexus.db` on its persistent disk. Startup creates missing tables, but does not migrate existing schemas. The service is configured for one worker and one instance because SQLite and in-process workflow execution are not intended for horizontal scaling.

The root `.env` is loaded regardless of the backend's current working directory. Configure `OLLAMA_API_KEY`, `OLLAMA_MODEL` and optionally `OLLAMA_TIMEOUT` (90 seconds by default) for Ollama Cloud. If Ollama fails (no credits, timeout, network, invalid output), negotiation uses a hardcoded offer labeled with the failure reason, and the run continues. Never commit `.env` or put server credentials in the frontend.

Use an Elastic Cloud deployment or an independently managed Elasticsearch 8 cluster. Set `ELASTICSEARCH_URL` to the Elasticsearch endpoint, not the ingest endpoint; use `ELASTICSEARCH_API_KEY`, not an ingest token. Grant index write/create access and search read access to `nexus-events-v1`. The transaction center calls `/api/events/search`; search failures are explicit, while indexing outages log warnings and do not discard SQL events. New documents are eventually searchable after Elastic refresh. No unsecured Elasticsearch server is provisioned on Render.

## Release Gates

```powershell
npm ci
npm run build
.venv\Scripts\python.exe -m pip install -r backend\requirements.lock
.venv\Scripts\python.exe -m pytest backend\tests -q
npm test
```

Browser checks in `tests/checkout.test.mjs` use mocked APIs and bundled Chromium (or installed Edge on Windows). If neither is installed, run `npx playwright install chromium`. Test the final Render URL on desktop/mobile and verify provider logs manually. Docker/Render and credentialed external checks require their respective environments; offline tests are not evidence of live-provider connectivity.

## PayPal References

- [Get started with PayPal REST APIs](https://developer.paypal.com/get-started/)
- [Orders v2: create an order](https://developer.paypal.com/api/orders/v2/orders-create/)
- [Orders v2: authorize payment for an order](https://developer.paypal.com/api/orders/v2/orders-authorize/)
- [Payments v2: capture an authorized payment](https://developer.paypal.com/api/payments/v2/authorizations-capture/)
- [REST API authentication](https://developer.paypal.com/api/rest/authentication/)
