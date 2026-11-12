import hashlib
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.config import get_settings
from backend.database import agents, checkout_sessions, engine, get_run, reputation_history, transactions, verification_results
from backend.integrations import PayPalSandbox
from backend.main import app


def completed_sandbox(client):
    response = client.post('/api/runs', json={'task': 'Create a logo', 'budget': 60, 'payment_mode': 'sandbox'})
    assert response.status_code == 201
    run = response.json()
    with client.websocket_connect(f"/api/ws/{run['id']}") as socket:
        while True:
            message = socket.receive_json()
            assert message['type'] != 'error', message
            if message['type'] == 'complete':
                assert message['transaction']['payment_status'] == 'awaiting_approval'
                assert message['transaction']['mode'] == 'sandbox'
                break
    return run


def test_sandbox_checkout_capability_approval_and_single_settlement(monkeypatch):
    approved = False
    calls = []
    run_id = ''

    async def request(self, method, path, request_id, body=None):
        calls.append(path)
        amount = {'currency_code': 'USD', 'value': '45.00'}
        units = [{'custom_id': run_id, 'amount': amount}]
        if path == '/v2/checkout/orders':
            assert body['intent'] == 'AUTHORIZE'
            return {'id': 'ORDER', 'status': 'PAYER_ACTION_REQUIRED', 'purchase_units': units,
                    'links': [{'rel': 'payer-action', 'href': 'https://www.sandbox.paypal.com/checkoutnow?token=ORDER'}]}
        if path == '/v2/checkout/orders/ORDER':
            return {'id': 'ORDER', 'status': 'APPROVED' if approved else 'PAYER_ACTION_REQUIRED', 'purchase_units': units}
        if path.endswith('/authorize'):
            return {'purchase_units': [{'payments': {'authorizations': [{'id': 'AUTH', 'status': 'CREATED', 'amount': amount}]}}]}
        assert path == '/v2/payments/authorizations/AUTH/capture'
        return {'id': 'CAPTURE', 'status': 'COMPLETED', 'amount': amount}

    monkeypatch.setattr(PayPalSandbox, 'request', request)
    with TestClient(app) as client:
        with engine.connect() as connection:
            before = dict(connection.execute(select(agents).where(agents.c.id == 'aura')).mappings().one())
        run = completed_sandbox(client)
        run_id = run['id']
        headers = {'Authorization': f"Bearer {run['checkout_token']}"}
        with engine.connect() as connection:
            session = connection.execute(select(checkout_sessions).where(checkout_sessions.c.transaction_id == run_id)).mappings().one()
            assert session['token_hash'] == hashlib.sha256(run['checkout_token'].encode()).hexdigest()
            assert not connection.execute(select(reputation_history).where(reputation_history.c.transaction_id == run_id)).first()
            assert connection.execute(select(agents.c.jobs).where(agents.c.id == 'aura')).scalar_one() == before['jobs']
        assert 'checkout_token' not in client.get(f'/api/runs/{run_id}').json()
        assert client.get(f'/api/paypal/{run_id}').status_code == 401
        assert client.get(f'/api/paypal/{run_id}', headers={'Authorization': 'Bearer wrong'}).status_code == 401
        assert client.post(f'/api/paypal/{run_id}/capture', headers=headers).status_code == 409
        assert client.post(f'/api/paypal/{run_id}/order', headers=headers).status_code == 200
        assert client.post(f'/api/paypal/{run_id}/order', headers=headers).json()['id'] == 'ORDER'
        assert client.post(f'/api/paypal/{run_id}/authorize', headers=headers).status_code == 409
        approved = True
        assert client.post(f'/api/paypal/{run_id}/authorize', headers=headers).status_code == 200
        assert client.post(f'/api/paypal/{run_id}/capture', headers=headers).status_code == 200
        assert client.post(f'/api/paypal/{run_id}/capture', headers=headers).json()['id'] == 'CAPTURE'
        status = client.get(f'/api/paypal/{run_id}', headers=headers).json()
        assert status['status'] == 'captured'
        assert status['capture_id'] == 'CAPTURE'
        with engine.connect() as connection:
            history = connection.execute(select(reputation_history).where(reputation_history.c.transaction_id == run_id)).mappings().all()
            assert len(history) == 1
            assert 'sandbox capture' in history[0]['reason']
            assert connection.execute(select(agents.c.jobs).where(agents.c.id == 'aura')).scalar_one() == before['jobs'] + 1
        assert calls.count('/v2/checkout/orders') == 1
        assert calls.count('/v2/payments/authorizations/AUTH/capture') == 1
        assert get_run(run_id)['payment']['sandbox']['capture']['id'] == 'CAPTURE'


def test_capability_is_run_bound_and_expires():
    with TestClient(app) as client:
        first = completed_sandbox(client)
        second = completed_sandbox(client)
        headers = {'Authorization': f"Bearer {first['checkout_token']}"}
        assert client.get(f"/api/paypal/{second['id']}", headers=headers).status_code == 401
        with engine.begin() as connection:
            connection.execute(checkout_sessions.update().where(checkout_sessions.c.transaction_id == first['id']).values(expires_at=time.time() - 1))
        assert client.get(f"/api/paypal/{first['id']}", headers=headers).status_code == 401


def test_missing_credentials_and_invalid_mode_are_rejected(monkeypatch):
    monkeypatch.setattr(get_settings(), 'paypal_client_secret', '')
    with TestClient(app) as client:
        assert client.post('/api/runs', json={'payment_mode': 'sandbox'}).status_code == 503
        assert client.post('/api/runs', json={'payment_mode': 'live'}).status_code == 422


def test_failed_verification_cannot_create_order():
    with TestClient(app) as client:
        run = completed_sandbox(client)
        with engine.begin() as connection:
            connection.execute(verification_results.update().where(verification_results.c.transaction_id == run['id']).values(passed=False))
        headers = {'Authorization': f"Bearer {run['checkout_token']}"}
        assert client.post(f"/api/paypal/{run['id']}/order", headers=headers).status_code == 409


@pytest.mark.parametrize('status,value', [('PENDING', '45.00'), ('COMPLETED', '46.00')])
def test_unsettled_or_mismatched_capture_never_records_reputation(monkeypatch, status, value):
    async def capture(self, *args):
        return {'id': 'CAPTURE', 'status': status, 'amount': {'currency_code': 'USD', 'value': value}}

    monkeypatch.setattr(PayPalSandbox, 'capture', capture)
    with TestClient(app) as client:
        run = completed_sandbox(client)
        with engine.begin() as connection:
            connection.execute(transactions.update().where(transactions.c.id == run['id']).values(
                payment={'sandbox': {'authorization': {'id': 'AUTH'}}}))
        headers = {'Authorization': f"Bearer {run['checkout_token']}"}
        assert client.post(f"/api/paypal/{run['id']}/capture", headers=headers).status_code == 409
        assert 'capture' not in get_run(run['id'])['payment']['sandbox']
        with engine.connect() as connection:
            assert not connection.execute(select(reputation_history).where(reputation_history.c.transaction_id == run['id'])).first()


def test_authorization_recovers_when_provider_succeeded_before_local_commit(monkeypatch):
    with TestClient(app) as client:
        run = completed_sandbox(client)
        amount = {'currency_code': 'USD', 'value': '45.00'}
        authorization = {'id': 'AUTH-RECOVERED', 'status': 'CREATED', 'amount': amount}
        with engine.begin() as connection:
            connection.execute(transactions.update().where(transactions.c.id == run['id']).values(
                payment={'sandbox': {'order': {'id': 'ORDER'}}}))

        async def get_order(self, order_id):
            return {'id': order_id, 'status': 'COMPLETED', 'purchase_units': [
                {'custom_id': run['id'], 'amount': amount, 'payments': {'authorizations': [authorization]}}]}

        async def authorize(self, *args):
            pytest.fail('A completed provider authorization must be recovered, not recreated')

        monkeypatch.setattr(PayPalSandbox, 'get_order', get_order)
        monkeypatch.setattr(PayPalSandbox, 'authorize', authorize)
        headers = {'Authorization': f"Bearer {run['checkout_token']}"}
        response = client.post(f"/api/paypal/{run['id']}/authorize", headers=headers)
        assert response.status_code == 200
        assert get_run(run['id'])['payment']['sandbox']['authorization']['id'] == 'AUTH-RECOVERED'
