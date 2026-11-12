import os
os.environ['DATABASE_URL'] = 'sqlite:///./test-nexus.db'
os.environ['STEP_DELAY'] = '0'
os.environ['OLLAMA_API_KEY'] = ''
os.environ['ELASTICSEARCH_URL'] = ''
os.environ['SANDBOX_API_TOKEN'] = ''

import asyncio
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from backend.database import engine, negotiations, reputation_history, verification_results
from backend.main import app
from backend import workflow as workflow_module
from backend.integrations import PayPalSandbox
from backend.workflow import ARTIFACT, calculate_trust, pay, verify_artifact


def test_full_workflow_and_event_replay():
    with TestClient(app) as client:
        response = client.post('/api/runs', json={'task': 'Create a logo for my startup.', 'budget': 60, 'payment_mode': 'demo'})
        assert response.status_code == 201
        run_id = response.json()['id']
        events = []
        with client.websocket_connect(f'/api/ws/{run_id}') as websocket:
            while True:
                message = websocket.receive_json()
                if message['type'] == 'complete':
                    assert message['transaction']['value'] == 45
                    assert message['transaction']['mode'] == 'demo'
                    break
                assert message['type'] == 'event'
                events.append(message)
        assert [event['sequence'] for event in events] == list(range(1, 13))
        assert [event['stage'] for event in events] == [0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5]
        detail = client.get(f'/api/runs/{run_id}').json()
        assert detail['status'] == 'completed'
        assert len(detail['events']) == 12
        assert client.get(f'/api/runs/{run_id}/artifact').content.decode() == ARTIFACT
        with client.websocket_connect(f'/api/ws/{run_id}') as websocket:
            assert websocket.receive_json()['sequence'] == 1
        with engine.connect() as connection:
            assert connection.execute(select(negotiations.c.agreed).where(negotiations.c.transaction_id == run_id)).scalar_one() == Decimal('45.00')
            assert connection.execute(select(verification_results.c.passed).where(verification_results.c.transaction_id == run_id)).scalar_one() is True
            history = connection.execute(select(reputation_history).where(reputation_history.c.transaction_id == run_id)).mappings().one()
            assert history['after'] >= history['before']


def test_payment_is_blocked_without_verification():
    with pytest.raises(ValueError, match='Payment blocked'):
        asyncio.run(pay({'verified': False, 'run_id': 'invalid'}))


def test_independent_verification_and_invalid_delivery():
    with pytest.raises(ValueError, match='own work'):
        verify_artifact(ARTIFACT, 'aura', 'aura')
    assert verify_artifact('not svg', 'aura', 'verify')['passed'] is False
    assert verify_artifact(ARTIFACT, 'aura', 'verify')['score'] == 100


def test_trust_is_bounded_and_penalizes_disputes():
    agent = dict(jobs=100, success=99, disputes=0, identity_verified=True)
    good, factors = calculate_trust(agent)
    bad, _ = calculate_trust({**agent, 'disputes': 20, 'identity_verified': False})
    assert 0 <= bad < good <= 100
    assert set(factors) == {'reliability', 'experience', 'disputes', 'identity'}


def test_api_policy_and_disabled_sandbox():
    with TestClient(app) as client:
        health = client.get('/api/health').json()
        assert health['payment_mode'] == 'sandbox'
        assert isinstance(health['paypal_sandbox_configured'], bool)
        assert client.post('/api/runs', json={'budget': 10}).status_code == 422
        assert client.post('/api/runs', json={'task': 'Buy a car'}).status_code == 422
        assert client.get('/api/runs/not-a-uuid').status_code == 404
        assert client.post('/api/paypal/not-a-uuid/order').status_code == 503


def test_sandbox_approval_order_and_idempotent_capture(monkeypatch):
    from backend.config import get_settings
    from backend.integrations import PayPalSandbox
    monkeypatch.setattr(get_settings(), 'sandbox_api_token', 'test-only-token')
    calls = []
    order_status = {'value': 'CREATED'}

    async def fake_request(self, method, path, request_id, body=None):
        calls.append((path, request_id, body))
        if path == '/v2/checkout/orders':
            assert body['intent'] == 'AUTHORIZE'
            assert body['purchase_units'][0]['amount']['value'] == '45.00'
            return {'id': 'ORDER-TEST', 'status': 'CREATED',
                    'purchase_units': [{'custom_id': run_id, 'amount': {'currency_code': 'USD', 'value': '45.00'}}],
                    'links': [{'rel': 'payer-action', 'href': 'https://www.sandbox.paypal.com/checkoutnow?token=ORDER-TEST'}]}
        if path == '/v2/checkout/orders/ORDER-TEST':
            return {'id': 'ORDER-TEST', 'status': order_status['value'],
                    'purchase_units': [{'custom_id': run_id, 'amount': {'currency_code': 'USD', 'value': '45.00'}}]}
        if path.endswith('/authorize'):
            return {'purchase_units': [{'payments': {'authorizations': [
                {'id': 'AUTH-TEST', 'status': 'CREATED', 'amount': {'currency_code': 'USD', 'value': '45.00'}}]}}]}
        assert path == '/v2/payments/authorizations/AUTH-TEST/capture'
        return {'id': 'CAPTURE-TEST', 'status': 'COMPLETED', 'amount': {'currency_code': 'USD', 'value': '45.00'}}

    monkeypatch.setattr(PayPalSandbox, 'request', fake_request)
    headers = {'Authorization': 'Bearer test-only-token'}
    with TestClient(app) as client:
        run_id = client.post('/api/runs', json={'budget': 60}).json()['id']
        with client.websocket_connect(f'/api/ws/{run_id}') as websocket:
            while websocket.receive_json()['type'] != 'complete':
                pass
        assert client.post(f'/api/paypal/{run_id}/order').status_code == 401
        assert client.post(f'/api/paypal/{run_id}/capture', headers=headers).status_code == 409
        assert client.post(f'/api/paypal/{run_id}/authorize', headers=headers).status_code == 409
        assert client.post(f'/api/paypal/{run_id}/order', headers=headers).json()['id'] == 'ORDER-TEST'
        assert client.post(f'/api/paypal/{run_id}/order', headers=headers).json()['id'] == 'ORDER-TEST'
        assert client.post(f'/api/paypal/{run_id}/authorize', headers=headers).status_code == 409
        order_status['value'] = 'APPROVED'
        assert client.post(f'/api/paypal/{run_id}/authorize', headers=headers).status_code == 200
        assert client.post(f'/api/paypal/{run_id}/capture', headers=headers).json()['status'] == 'COMPLETED'
        assert client.post(f'/api/paypal/{run_id}/capture', headers=headers).json()['id'] == 'CAPTURE-TEST'
        assert len(calls) == 5


def test_paypal_response_amount_and_run_binding():
    from backend.main import paypal_amount_matches, paypal_purchase_matches
    amount = Decimal('45.00')
    purchase = {'custom_id': 'run-123', 'amount': {'currency_code': 'USD', 'value': '45.00'}}
    assert paypal_purchase_matches({'purchase_units': [purchase]}, 'run-123', amount)
    assert not paypal_purchase_matches({'purchase_units': [purchase]}, 'another-run', amount)
    assert not paypal_amount_matches({'amount': {'currency_code': 'EUR', 'value': '45.00'}}, amount)
    assert not paypal_amount_matches({'amount': {'currency_code': 'USD', 'value': '44.99'}}, amount)

def test_default_run_uses_paypal_sandbox_and_logs_payment_events(monkeypatch):
    run_id = ''
    logged = []

    async def request(self, method, path, request_id, body=None):
        assert path == '/v2/checkout/orders'
        return {'id': 'ORDER-DEFAULT', 'status': 'PAYER_ACTION_REQUIRED',
                'purchase_units': [{'custom_id': run_id, 'amount': {'currency_code': 'USD', 'value': '45.00'}}],
                'links': [{'rel': 'payer-action', 'href': 'https://www.sandbox.paypal.com/checkoutnow?token=ORDER-DEFAULT'}]}

    async def capture_log(event):
        logged.append(event)

    monkeypatch.setattr(PayPalSandbox, 'request', request)
    monkeypatch.setattr(workflow_module, 'log_event', capture_log)
    with TestClient(app) as client:
        run = client.post('/api/runs', json={'task': 'Create a logo', 'budget': 60}).json()
        run_id = run['id']
        assert run['mode'] == 'sandbox' and run['checkout_token']
        with client.websocket_connect(f'/api/ws/{run_id}') as socket:
            while socket.receive_json()['type'] != 'complete':
                pass
        headers = {'Authorization': 'Bearer ' + run['checkout_token']}
        assert client.post(f'/api/paypal/{run_id}/order', headers=headers).json()['id'] == 'ORDER-DEFAULT'
        events = client.get(f'/api/runs/{run_id}').json()['events']
    assert 'PayPal sandbox order ORDER-DEFAULT created' in events[-1]['message']
    assert logged[-1]['message'] == events[-1]['message']
