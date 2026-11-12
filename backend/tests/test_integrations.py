import asyncio
import json
from decimal import Decimal

import httpx
import pytest
from elastic_transport import ConnectionError
from fastapi.testclient import TestClient

from backend import integrations
from backend.config import Settings, get_settings
from backend.main import app


def mock_http(monkeypatch, handler):
    client_type = httpx.AsyncClient
    monkeypatch.setattr(integrations.httpx, 'AsyncClient',
                        lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs))


def test_ollama_cloud_uses_private_key_and_validates_offer(monkeypatch):
    monkeypatch.setattr(get_settings(), 'ollama_api_key', 'unit-test-ollama')
    monkeypatch.setattr(get_settings(), 'ollama_model', 'unit-test-model')

    def handler(request):
        assert str(request.url) == 'https://ollama.com/api/chat'
        assert request.headers['Authorization'] == 'Bearer unit-test-ollama'
        body = json.loads(request.content)
        assert body['model'] == 'unit-test-model'
        assert body['stream'] is False
        # Ollama Cloud does not support the local API's structured-output format parameter.
        assert 'format' not in body
        assert 'schema' in body['messages'][0]['content']
        return httpx.Response(200, json={'message': {'content': '{"price":45,"rationale":"Agreed scope, one revision."}'}})

    mock_http(monkeypatch, handler)
    offer, model = asyncio.run(integrations.negotiate_with_ollama('Create a logo', Decimal('60'), Decimal('45')))
    assert offer['price'] == 45
    assert model == 'unit-test-model'


@pytest.mark.parametrize('status,content', [
    (401, {}),
    (200, {'message': {'content': '{"price":65,"rationale":"Increased price"}'}}),
    (200, {'message': {'content': 'not json'}}),
    (200, {'message': None}),
])
def test_ollama_failures_use_hardcoded_offer(monkeypatch, status, content):
    monkeypatch.setattr(get_settings(), 'ollama_api_key', 'unit-test-ollama')
    mock_http(monkeypatch, lambda request: httpx.Response(status, json=content))
    offer, model = asyncio.run(integrations.negotiate_with_ollama('Create a logo', Decimal('60'), Decimal('45')))
    assert offer['price'] == 45
    assert model.startswith('hardcoded-fallback')


def test_ollama_connection_error_uses_hardcoded_offer(monkeypatch):
    monkeypatch.setattr(get_settings(), 'ollama_api_key', 'unit-test-ollama')

    def handler(request):
        raise httpx.ConnectError('offline')

    mock_http(monkeypatch, handler)
    offer, model = asyncio.run(integrations.negotiate_with_ollama('Create a logo', Decimal('60'), Decimal('45')))
    assert offer['price'] == 45
    assert model == 'hardcoded-fallback (Ollama unavailable: ConnectError)'


def test_paypal_oauth_and_idempotency_headers(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.host == 'api-m.sandbox.paypal.com'
        if request.url.path == '/v1/oauth2/token':
            assert request.headers['Authorization'].startswith('Basic ')
            assert b'grant_type=client_credentials' in request.content
            return httpx.Response(200, json={'access_token': 'unit-test-access-token'})
        assert request.headers['Authorization'] == 'Bearer unit-test-access-token'
        assert request.headers['PayPal-Request-Id'] == 'stable-request'
        return httpx.Response(200, json={'id': 'ORDER', 'status': 'CREATED'})

    mock_http(monkeypatch, handler)
    result = asyncio.run(integrations.PayPalSandbox().request('POST', '/v2/checkout/orders', 'stable-request', {'intent': 'AUTHORIZE'}))
    assert result['id'] == 'ORDER'
    assert len(calls) == 2


def test_live_paypal_configuration_is_rejected():
    with pytest.raises(ValueError):
        Settings(paypal_env='live')


def test_elasticsearch_indexes_stable_ids_and_searches_real_index(monkeypatch):
    monkeypatch.setattr(get_settings(), 'elasticsearch_url', 'https://unit-test.invalid')
    monkeypatch.setattr(get_settings(), 'elasticsearch_api_key', 'unit-test-elastic')
    indexed = []
    searched = []
    event = {'run_id': 'unit-run', 'sequence': 1, 'message': 'Verified', 'agent': 'Sentinel', 'time': '2026-01-01'}

    class FakeElastic:
        def __init__(self, url, **kwargs):
            assert url == 'https://unit-test.invalid'
            assert kwargs['api_key'] == 'unit-test-elastic'

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def index(self, **kwargs):
            indexed.append(kwargs)

        async def search(self, **kwargs):
            searched.append(kwargs)
            return {'hits': {'hits': [{'_source': event}]}}

    monkeypatch.setattr(integrations, 'AsyncElasticsearch', FakeElastic)
    asyncio.run(integrations.log_event(event))
    assert indexed == [{'index': 'nexus-events-v1', 'id': 'unit-run:1', 'document': event}]
    assert asyncio.run(integrations.search_events('Verified', 'unit-run')) == [event]
    assert searched[0]['query']['bool']['filter'] == [{'match_phrase': {'run_id': 'unit-run'}}]
    assert searched[0]['size'] == 50
    with TestClient(app) as client:
        assert client.get('/api/events/search?q=Verified').json()['events'] == [event]
        assert client.get('/api/events/search?run_id=invalid').status_code == 422


def test_elasticsearch_outage_does_not_lose_sql_events_but_search_reports_failure(monkeypatch, caplog):
    monkeypatch.setattr(get_settings(), 'elasticsearch_url', 'https://unit-test.invalid')

    class OfflineElastic:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            raise ConnectionError('offline')

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(integrations, 'AsyncElasticsearch', OfflineElastic)
    asyncio.run(integrations.log_event({'run_id': 'unit-run', 'sequence': 1}))
    assert 'Elastic log delivery failed' in caplog.text
    with TestClient(app) as client:
        assert client.get('/api/events/search').status_code == 502
        run_id = client.post('/api/runs', json={'task': 'Create a logo', 'budget': 60}).json()['id']
        with client.websocket_connect(f'/api/ws/{run_id}') as socket:
            while True:
                message = socket.receive_json()
                assert message['type'] != 'error'
                if message['type'] == 'complete':
                    break
        assert len(client.get(f'/api/runs/{run_id}').json()['events']) == 12


def test_unconfigured_search_is_explicitly_unavailable():
    with TestClient(app) as client:
        assert client.get('/api/events/search').status_code == 503


def test_ollama_failure_still_completes_run_with_hardcoded_offer(monkeypatch):
    monkeypatch.setattr(get_settings(), 'ollama_api_key', 'unit-test-ollama')
    mock_http(monkeypatch, lambda request: httpx.Response(503, json={'error': 'offline'}))
    with TestClient(app) as client:
        run_id = client.post('/api/runs', json={'payment_mode': 'sandbox'}).json()['id']
        with client.websocket_connect(f'/api/ws/{run_id}') as socket:
            while True:
                message = socket.receive_json()
                assert message['type'] != 'error'
                if message['type'] == 'complete':
                    break
        detail = client.get(f'/api/runs/{run_id}').json()
        assert detail['status'] == 'completed'
        assert any('hardcoded-fallback (Ollama HTTP 503)' in event['message'] for event in detail['events'])


def test_integration_check_calls_each_configured_provider(monkeypatch):
    settings = get_settings()
    for name, value in dict(ollama_api_key='unit-test-ollama', ollama_model='unit-test-model',
                            elasticsearch_url='https://elastic.example', elasticsearch_api_key='unit-test-elastic',
                            paypal_client_id='unit-test-client', paypal_client_secret='unit-test-secret').items():
        monkeypatch.setattr(settings, name, value)

    def handler(request):
        if request.url.host == 'ollama.com':
            assert request.url.path == '/api/tags'
            return httpx.Response(200, json={'models': [{'name': 'unit-test-model'}]})
        assert request.url.host == 'api-m.sandbox.paypal.com'
        assert request.url.path == '/v1/oauth2/token'
        return httpx.Response(200, json={'access_token': 'unit-test-access'})

    class FakeIndices:
        async def exists(self, index):
            assert index == 'nexus-events-v1'
            return True

    class FakeElastic:
        def __init__(self, url, **options):
            assert url == 'https://elastic.example'
            assert options['api_key'] == 'unit-test-elastic'
            self.indices = FakeIndices()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def count(self, index):
            return {'count': 12}

    mock_http(monkeypatch, handler)
    monkeypatch.setattr(integrations, 'AsyncElasticsearch', FakeElastic)
    with TestClient(app) as client:
        result = client.get('/api/integrations/check').json()
    assert result['ollama'] == {'configured': True, 'ok': True, 'model': 'unit-test-model', 'model_available': True}
    assert result['elasticsearch'] == {'configured': True, 'ok': True, 'index': 'nexus-events-v1', 'documents': 12}
    assert result['paypal'] == {'configured': True, 'ok': True, 'environment': 'sandbox'}


def test_ollama_402_uses_hardcoded_offer(monkeypatch):
    monkeypatch.setattr(get_settings(), 'ollama_api_key', 'unit-test-ollama')
    mock_http(monkeypatch, lambda request: httpx.Response(402, json={'error': 'Add usage credits'}))
    offer, model = asyncio.run(integrations.negotiate_with_ollama('Create a logo', Decimal('60'), Decimal('45')))
    assert offer['price'] == 45
    assert model.startswith('hardcoded-fallback')
