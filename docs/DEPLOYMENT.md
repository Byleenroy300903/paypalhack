# Render Deployment

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
