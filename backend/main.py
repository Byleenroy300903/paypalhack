import asyncio
import hmac
import hashlib
import logging
import secrets
import time
from contextlib import asynccontextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID
from urllib.parse import urlsplit
from typing import Literal
import httpx
from elasticsearch import ApiError
from elastic_transport import TransportError
from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, text
from .config import get_settings
from .database import (agents, checkout_sessions, engine, get_run, initialize, now, negotiations,
                       reputation_history, transaction_view, transactions, uid, verification_results)
from .integrations import PayPalSandbox, check_integrations, search_events
from .workflow import execute, record_event, record_reputation

logging.basicConfig(level=logging.INFO)
tasks: set[asyncio.Task] = set()
payment_locks: dict[str, asyncio.Lock] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize()
    yield
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    engine.dispose()


app = FastAPI(title='PayPal Nexus', version='1.0.0', lifespan=lifespan,
              description='Trust network for autonomous AI commerce. Default runs move simulated funds only.')
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins.split(','), allow_methods=['GET', 'POST'], allow_headers=['Content-Type', 'Authorization'])


class RunRequest(BaseModel):
    task: str = Field(default='Create a logo for my startup.', min_length=5, max_length=240)
    budget: Decimal = Field(default=Decimal('60'), ge=45, le=1000, decimal_places=2)
    # Defaults to the real PayPal sandbox whenever credentials are configured.
    payment_mode: Literal['demo', 'sandbox'] | None = None

    @field_validator('task')
    @classmethod
    def logo_scope(cls, value: str) -> str:
        if 'logo' not in value.lower():
            raise ValueError('This demo supports logo design missions only')
        return value.strip()


def require_run(run_id: str) -> dict:
    try:
        UUID(run_id)
    except ValueError:
        raise HTTPException(404, 'Run not found')
    run = get_run(run_id)
    if run is None:
        raise HTTPException(404, 'Run not found')
    return run


def sandbox_auth(authorization: str = Header(default='')) -> None:
    token = get_settings().sandbox_api_token
    if not token:
        raise HTTPException(503, 'Sandbox payment operations are disabled')
    if not hmac.compare_digest(authorization, f'Bearer {token}'):
        raise HTTPException(401, 'Invalid sandbox authorization')


@app.get('/api/health')
def health():
    with engine.connect() as connection:
        connection.execute(select(agents.c.id).limit(1))
    settings = get_settings()
    return dict(status='ok', payment_mode='sandbox' if settings.paypal_client_id and settings.paypal_client_secret else 'demo',
                workflow_transport='request' if settings.vercel else 'websocket',
                ai='ollama-cloud' if settings.ollama_api_key else 'deterministic-demo',
                elastic_configured=bool(settings.elasticsearch_url),
                paypal_sandbox_configured=bool(settings.paypal_client_id and settings.paypal_client_secret),
                ollama_model=settings.ollama_model if settings.ollama_api_key else None)


@app.get('/api/integrations/check')
async def integration_check():
    return await check_integrations()


def checkout_auth(run_id: str, authorization: str = Header(default='')) -> None:
    settings = get_settings()
    if settings.sandbox_api_token:
        expected = 'Bearer ' + settings.sandbox_api_token
        if hmac.compare_digest(authorization, expected):
            return
    with engine.connect() as connection:
        session = connection.execute(select(checkout_sessions).where(checkout_sessions.c.transaction_id == run_id)).mappings().first()
    if session:
        token = authorization.removeprefix('Bearer ') if authorization.startswith('Bearer ') else ''
        if session['expires_at'] > time.time() and hmac.compare_digest(
                session['token_hash'], hashlib.sha256(token.encode()).hexdigest()):
            return
        raise HTTPException(401, 'Checkout session is invalid or expired. Use the original browser session or an operator token.')
    sandbox_auth(authorization)


@app.get('/api/events/search')
async def event_search(q: str = Query(default='', max_length=200), run_id: UUID | None = None):
    try:
        return dict(events=await search_events(q, str(run_id) if run_id else None))
    except RuntimeError as error:
        raise HTTPException(503, str(error)) from error
    except (ApiError, TransportError, ValueError) as error:
        logging.getLogger('nexus').warning('Elastic search failed: %s', type(error).__name__)
        raise HTTPException(502, 'Elasticsearch search failed. Check connectivity, endpoint and API key permissions.') from error


@app.get('/api/agents')
def list_agents():
    with engine.connect() as connection:
        return [dict(row) for row in connection.execute(select(agents)).mappings()]


@app.post('/api/runs', status_code=201)
async def start_run(request: RunRequest):
    if len(tasks) >= 6:
        raise HTTPException(429, 'Network busy. Try again shortly.')
    settings = get_settings()
    paypal_ready = bool(settings.paypal_client_id and settings.paypal_client_secret)
    payment_mode = request.payment_mode or ('sandbox' if paypal_ready else 'demo')
    if payment_mode == 'sandbox' and not paypal_ready:
        raise HTTPException(503, 'PayPal sandbox credentials are not configured')
    run_id = uid()
    checkout_token = secrets.token_urlsafe(32) if payment_mode == 'sandbox' else None
    with engine.begin() as connection:
        connection.execute(transactions.insert().values(id=run_id, task=request.task, budget=request.budget, value=0, status='running', mode=payment_mode, events=[], payment={}, created_at=now()))
        if checkout_token:
            connection.execute(checkout_sessions.insert().values(transaction_id=run_id,
                token_hash=hashlib.sha256(checkout_token.encode()).hexdigest(), expires_at=time.time() + 86400))
    if settings.vercel:
        try:
            async with asyncio.timeout(240):
                await execute(run_id)
        except TimeoutError:
            logging.getLogger('nexus').warning('Workflow %s exceeded the request deadline', run_id)
            with engine.begin() as connection:
                connection.execute(transactions.update().where(transactions.c.id == run_id).values(
                    status='failed', error='Workflow exceeded the Vercel request deadline. Start a new mission.'))
        return dict(id=run_id, status=require_run(run_id)['status'], mode=payment_mode,
                    websocket=None, checkout_token=checkout_token)
    task = asyncio.create_task(execute(run_id))
    tasks.add(task)
    task.add_done_callback(tasks.discard)
    return dict(id=run_id, status='running', mode=payment_mode, websocket=f'/api/ws/{run_id}', checkout_token=checkout_token)


@app.get('/api/runs/{run_id}')
def run_detail(run_id: str):
    run = require_run(run_id)
    return dict(id=run_id, status=run['status'], events=run['events'], transaction=transaction_view(run), error=run['error'])


@app.get('/api/transactions')
def list_transactions():
    with engine.connect() as connection:
        return [transaction_view(dict(row)) for row in connection.execute(select(transactions).order_by(transactions.c.created_at.desc()).limit(200)).mappings()]


@app.get('/api/agents/{agent_id}/reputation')
def reputation(agent_id: str):
    with engine.connect() as connection:
        if connection.execute(select(agents.c.id).where(agents.c.id == agent_id)).first() is None:
            raise HTTPException(404, 'Agent not found')
        return [dict(row) for row in connection.execute(select(reputation_history).where(reputation_history.c.agent_id == agent_id).order_by(reputation_history.c.created_at.desc()).limit(100)).mappings()]


@app.get('/api/runs/{run_id}/artifact')
def artifact(run_id: str):
    require_run(run_id)
    with engine.connect() as connection:
        artifact = connection.execute(select(verification_results.c.artifact).where(verification_results.c.transaction_id == run_id)).scalar_one_or_none()
    if artifact is None:
        raise HTTPException(404, 'Artifact not yet available')
    return Response(content=artifact, media_type='image/svg+xml', headers={'Content-Disposition': 'attachment; filename=nexus-logo-demo.svg', 'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'"})


@app.websocket('/api/ws/{run_id}')
async def stream_run(websocket: WebSocket, run_id: str):
    if get_run(run_id) is None:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    cursor = 0
    try:
        while True:
            run = get_run(run_id)
            if run is None:
                break
            for event in run['events'][cursor:]:
                await websocket.send_json(event)
                cursor += 1
            if run['status'] == 'completed':
                await websocket.send_json(dict(type='complete', transaction=transaction_view(run)))
                break
            if run['status'] == 'failed':
                await websocket.send_json(dict(type='error', message=run['error']))
                break
            await asyncio.sleep(.25)
        await websocket.close()
    except (WebSocketDisconnect, RuntimeError):
        return


@asynccontextmanager
async def payment_lock(run_id: str):
    if engine.dialect.name == 'postgresql':
        # A transaction-scoped lock also works through Neon's transaction pooler.
        key = int.from_bytes(hashlib.sha256(run_id.encode()).digest()[:8], 'big', signed=True)
        with engine.begin() as connection:
            deadline = time.monotonic() + 15
            while not connection.execute(text('SELECT pg_try_advisory_xact_lock(:key)'), {'key': key}).scalar_one():
                if time.monotonic() >= deadline:
                    raise HTTPException(409, 'Another checkout operation is in progress. Retry shortly.')
                await asyncio.sleep(.1)
            yield
    else:
        lock = payment_locks.setdefault(run_id, asyncio.Lock())
        async with lock:
            yield


async def payment_operation(run_id: str, operation: str) -> dict:
    async with payment_lock(run_id):
        run = require_run(run_id)
        if run['status'] != 'completed':
            raise HTTPException(409, 'A verified, completed contract is required')
        with engine.connect() as connection:
            verification = connection.execute(select(verification_results).where(verification_results.c.transaction_id == run_id)).mappings().first()
        if not verification or not verification['passed'] or verification['verifier_id'] == run['agent_id']:
            raise HTTPException(409, 'Independent verification is required')
        payment = dict(run['payment'])
        sandbox = payment.get('sandbox', {})
        client = PayPalSandbox()
        try:
            if operation == 'create':
                if sandbox.get('order'):
                    return sandbox['order']
                result = await client.create(run_id, Decimal(str(run['value'])))
                if (result.get('status') not in ('CREATED', 'PAYER_ACTION_REQUIRED')
                        or not result.get('id')
                        or not isinstance(result.get('links'), list)
                        or not approval_url(result)
                        or not paypal_purchase_matches(result, run_id, Decimal(str(run['value'])))):
                    raise HTTPException(502, 'PayPal did not return a valid sandbox approval order')
                sandbox['order'] = result
            elif operation == 'authorize':
                if sandbox.get('authorization'):
                    return sandbox['authorization']
                if not sandbox.get('order'):
                    raise HTTPException(409, 'Create and approve the PayPal order first')
                order = await client.get_order(sandbox['order']['id'])
                if order.get('id') != sandbox['order']['id']:
                    raise HTTPException(409, 'PayPal returned a different order')
                if not paypal_purchase_matches(order, run_id, Decimal(str(run['value']))):
                    raise HTTPException(409, 'PayPal order does not match this verified contract')
                if order.get('status') == 'APPROVED':
                    result = await client.authorize(run_id, sandbox['order']['id'])
                elif order.get('status') == 'COMPLETED':
                    result = order
                else:
                    raise HTTPException(409, 'PayPal buyer approval is required before authorization')
                purchase_units = result.get('purchase_units')
                if not isinstance(purchase_units, list) or not purchase_units or not isinstance(purchase_units[0], dict):
                    raise HTTPException(502, 'PayPal returned an invalid authorization response')
                payment_details = purchase_units[0].get('payments')
                if not isinstance(payment_details, dict):
                    raise HTTPException(502, 'PayPal returned an invalid authorization response')
                authorizations = payment_details.get('authorizations')
                if not isinstance(authorizations, list) or not authorizations or not isinstance(authorizations[0], dict):
                    raise HTTPException(502, 'PayPal returned an invalid authorization response')
                authorization = authorizations[0]
                if (not authorization.get('id') or authorization.get('status') != 'CREATED'
                        or not paypal_amount_matches(authorization, Decimal(str(run['value'])))):
                    raise HTTPException(409, 'PayPal authorization did not succeed')
                sandbox['authorization'] = authorization
            else:
                if sandbox.get('capture'):
                    return sandbox['capture']
                if not sandbox.get('authorization'):
                    raise HTTPException(409, 'Buyer approval and authorization are required')
                result = await client.capture(run_id, sandbox['authorization']['id'], Decimal(str(run['value'])))
                if (not result.get('id') or result.get('status') != 'COMPLETED'
                        or not paypal_amount_matches(result, Decimal(str(run['value'])))):
                    raise HTTPException(409, 'PayPal capture is not completed')
                sandbox['capture'] = result
            payment['sandbox'] = sandbox
            with engine.begin() as connection:
                connection.execute(transactions.update().where(transactions.c.id == run_id).values(payment=payment))
                if operation == 'capture' and run['mode'] == 'sandbox':
                    record_reputation(connection, run_id, run['agent_id'], 'Independently verified delivery and completed PayPal sandbox capture')
            if operation == 'create':
                message = f"PayPal sandbox order {result.get('id')} created for ${run['value']} USD. Awaiting buyer approval."
            elif operation == 'authorize':
                message = f"PayPal sandbox buyer approval verified. Authorization {sandbox['authorization'].get('id')} created."
            else:
                message = f"PayPal sandbox capture {result.get('id')} completed. Test funds only; reputation updated."
            await record_event(run_id, 4, message)
            return result
        except RuntimeError as error:
            raise HTTPException(503, str(error))
        except HTTPException:
            raise
        except (httpx.HTTPError, KeyError, ValueError) as error:
            logging.getLogger('nexus').warning('PayPal %s failed: %s', operation, type(error).__name__)
            raise HTTPException(502, 'PayPal sandbox rejected the operation. Confirm buyer approval and retry.')


def approval_url(order: dict) -> str | None:
    for link in order.get('links', []):
        if not isinstance(link, dict) or link.get('rel') not in ('payer-action', 'approve'):
            continue
        href = link.get('href')
        if not isinstance(href, str):
            continue
        parsed = urlsplit(href)
        if parsed.scheme == 'https' and parsed.netloc == 'www.sandbox.paypal.com':
            return href
    return None


@app.get('/api/paypal/{run_id}', dependencies=[Depends(checkout_auth)])
def checkout_status(run_id: str):
    run = require_run(run_id)
    sandbox = run['payment'].get('sandbox', {})
    return dict(run_id=run_id, status=transaction_view(run)['payment_status'],
                ready=run['status'] == 'completed',
                order_id=sandbox.get('order', {}).get('id'),
                approval_url=approval_url(sandbox.get('order', {})),
                authorization_id=sandbox.get('authorization', {}).get('id'),
                capture_id=sandbox.get('capture', {}).get('id'))


def paypal_amount_matches(payment: dict, expected: Decimal) -> bool:
    if not isinstance(payment, dict):
        return False
    amount = payment.get('amount', {})
    if not isinstance(amount, dict):
        return False
    if amount.get('currency_code') != 'USD':
        return False
    try:
        return Decimal(str(amount.get('value'))) == expected
    except (InvalidOperation, ValueError, TypeError):
        return False


def paypal_purchase_matches(order: dict, run_id: str, expected: Decimal) -> bool:
    if not isinstance(order, dict):
        return False
    purchase_units = order.get('purchase_units', [])
    return (isinstance(purchase_units, list) and len(purchase_units) == 1
            and isinstance(purchase_units[0], dict)
            and purchase_units[0].get('custom_id') == run_id
            and paypal_amount_matches(purchase_units[0], expected))


@app.post('/api/paypal/{run_id}/order', dependencies=[Depends(checkout_auth)])
async def create_order(run_id: str):
    return await payment_operation(run_id, 'create')


@app.post('/api/paypal/{run_id}/authorize', dependencies=[Depends(checkout_auth)])
async def authorize_order(run_id: str):
    return await payment_operation(run_id, 'authorize')


@app.post('/api/paypal/{run_id}/capture', dependencies=[Depends(checkout_auth)])
async def capture_payment(run_id: str):
    return await payment_operation(run_id, 'capture')


dist = Path(__file__).resolve().parents[1] / 'dist' / 'nexus' / 'browser'
if dist.exists() and not get_settings().vercel:
    app.mount('/', StaticFiles(directory=dist, html=True), name='frontend')