import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { existsSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { resolve, extname, sep } from 'node:path';
import { chromium, expect } from '@playwright/test';

const runId = '93e8ef1d-1d73-4b46-9e57-cc686eb5fba6';
const token = 'unit-test-checkout-capability';
let server;
let browser;
let baseUrl;

before(async () => {
  const root = resolve('dist', 'nexus', 'browser');
  assert.ok(existsSync(resolve(root, 'index.html')), 'Run npm run build before npm test.');
  server = createServer(async (request, response) => {
    const pathname = new URL(request.url, 'http://localhost').pathname;
    const target = resolve(root, `.${pathname === '/' ? '/index.html' : pathname}`);
    if (!target.startsWith(root + sep)) { response.writeHead(403).end(); return; }
    try {
      const body = await readFile(target);
      const types = { '.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css' };
      response.writeHead(200, { 'Content-Type': types[extname(target)] ?? 'application/octet-stream' }).end(body);
    } catch { response.writeHead(404).end(); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  baseUrl = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch(!existsSync(chromium.executablePath()) && process.platform === 'win32' ? { channel: 'msedge' } : {});
});

after(async () => {
  await browser?.close();
  await new Promise(resolve => server ? server.close(resolve) : resolve());
});

async function workspace({ savedCheckout = true, failedOrder = false, failedSearch = false } = {}) {
  const context = await browser.newContext();
  if (savedCheckout) await context.addInitScript(({ runId, token }) => {
    sessionStorage.setItem(`nexus-checkout-${runId}`, token);
    sessionStorage.setItem('nexus-checkout-run', runId);
  }, { runId, token });
  const state = { order: false, approved: false, authorized: false, captured: false, calls: [] };
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== baseUrl) { await route.abort(); return; }
    if (!url.pathname.startsWith('/api/')) { await route.continue(); return; }
    const path = url.pathname;
    const json = body => route.fulfill({ json: body });
    if (path === '/api/health') return json({ status: 'ok', ai: 'ollama-cloud', ollama_model: 'gpt-oss:120b', elastic_configured: true, paypal_sandbox_configured: true });
    if (path === '/api/agents' || path.endsWith('/reputation')) return json([]);
    if (path === '/api/transactions') return json(savedCheckout ? [{
      id: runId, agent: 'Aura Creative', task: 'Create a logo', trust: state.captured ? 98.2 : 98,
      value: 45, status: 'Completed', delivery: 100, date: '2026-11-11', mode: 'sandbox',
      payment_status: state.captured ? 'captured' : 'awaiting_approval'
    }] : []);
    if (path === '/api/events/search') {
      state.calls.push({ path, query: url.searchParams.get('q') });
      if (failedSearch) return route.fulfill({ status: 502, json: { detail: 'Elasticsearch search failed. Check connectivity.' } });
      return json({ events: [{ agent: 'Negotiation Agent', message: 'Agreement indexed in Elasticsearch.', sequence: 1, stage: 2, time: '2026-11-11T12:00:00Z' }] });
    }
    if (path === '/api/runs' && route.request().method() === 'POST') {
      const request = route.request().postDataJSON();
      assert.equal(request.payment_mode, 'sandbox');
      return route.fulfill({ status: 201, json: { id: runId, mode: 'sandbox', checkout_token: token } });
    }
    if (path.startsWith(`/api/paypal/${runId}`)) {
      assert.equal(route.request().headers().authorization, `Bearer ${token}`);
      state.calls.push({ path });
      if (path.endsWith('/order')) {
        if (failedOrder) return route.fulfill({ status: 502, json: { detail: 'PayPal sandbox rejected the operation.' } });
        state.order = true;
      }
      if (path.endsWith('/authorize')) {
        assert.ok(state.approved);
        state.authorized = true;
      }
      if (path.endsWith('/capture')) {
        assert.ok(state.authorized);
        state.captured = true;
      }
      return json({
        run_id: runId, ready: true, status: state.captured ? 'captured' : state.authorized ? 'authorized' : 'awaiting_approval',
        order_id: state.order ? 'ORDER' : null,
        approval_url: state.order ? 'https://www.sandbox.paypal.com/checkoutnow?token=ORDER' : null,
        authorization_id: state.authorized ? 'AUTH' : null, capture_id: state.captured ? 'CAPTURE' : null
      });
    }
    throw new Error(`Unexpected API request: ${path}`);
  });
  return { context, page: await context.newPage(), state };
}

test('checkout resumes after buyer return and captures only after explicit authorization', async () => {
  const { context, page, state } = await workspace();
  try {
    await page.goto(`${baseUrl}/#transactions`);
    await page.getByRole('button', { name: 'Create PayPal order', exact: true }).click();
    await expect(page.getByRole('link', { name: 'Open PayPal buyer approval' })).toHaveAttribute('href', /www\.sandbox\.paypal\.com/);
    assert.ok(!state.captured);
    state.approved = true;
    await page.goto(`${baseUrl}/?payment=approved&run_id=${runId}#transactions`);
    await expect(page.getByText('Returned from PayPal.', { exact: false })).toBeVisible();
    await page.getByRole('button', { name: 'I approved on PayPal - authorize' }).click();
    await page.getByRole('button', { name: 'Capture sandbox payment', exact: true }).click();
    await expect(page.getByText('Captured in PayPal sandbox:', { exact: false })).toBeVisible();
    assert.equal(state.calls.filter(call => call.path.endsWith('/capture')).length, 1);
    await page.setViewportSize({ width: 390, height: 844 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Checkout must fit a mobile viewport');
  } finally { await context.close(); }
});

test('provider payment failures are visible without advancing checkout', async () => {
  const { context, page, state } = await workspace({ failedOrder: true });
  try {
    await page.goto(`${baseUrl}/#transactions`);
    await page.getByRole('button', { name: 'Create PayPal order', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('PayPal sandbox rejected');
    await expect(page.getByRole('button', { name: 'I approved on PayPal - authorize' })).toHaveCount(0);
    assert.ok(!state.order && !state.authorized && !state.captured);
  } finally { await context.close(); }
});

test('audit search uses the Elasticsearch API and reports provider outages', async () => {
  for (const failedSearch of [false, true]) {
    const { context, page, state } = await workspace({ savedCheckout: false, failedSearch });
    try {
      await page.goto(`${baseUrl}/#transactions`);
      await page.getByRole('textbox', { name: 'Search Elasticsearch audit events' }).fill('agreement');
      await page.getByRole('button', { name: 'Search Elasticsearch', exact: true }).click();
      if (failedSearch) await expect(page.getByRole('alert')).toContainText('Elasticsearch search failed');
      else await expect(page.getByText('Agreement indexed in Elasticsearch.')).toBeVisible();
      assert.equal(state.calls.at(-1).query, 'agreement');
    } finally { await context.close(); }
  }
});

test('sandbox missions request the backend and surface Ollama failure without a demo settlement', async () => {
  const { context, page } = await workspace({ savedCheckout: false });
  try {
    await page.routeWebSocket('**/api/ws/**', socket => {
      setTimeout(() => socket.send(JSON.stringify({ type: 'error', message: 'Ollama Cloud negotiation failed. No simulated offer was substituted.' })), 100);
    });
    await page.goto(`${baseUrl}/#simulation`);
    await expect(page.getByText('FastAPI engine connected')).toBeVisible();
    await page.getByRole('button', { name: 'Create logo', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('Ollama Cloud negotiation failed');
    await expect(page.getByText('DELIVERY VERIFIED', { exact: true })).toHaveCount(0);
  } finally { await context.close(); }
});
