import asyncio
import importlib
import json
from pathlib import Path
import tomllib
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import NullPool

from backend import database, main
from backend.config import get_settings
from backend.database import engine, get_run, now, transactions, uid


def test_vercel_entrypoint_exports_backend_app():
    root = Path(__file__).resolve().parents[2]
    config = json.loads((root / 'vercel.json').read_text())
    project = tomllib.loads((root / 'pyproject.toml').read_text())
    assert config['framework'] == 'fastapi'
    assert 'functions' not in config
    assert project['tool']['vercel']['entrypoint'] == 'app:app'
    assert importlib.import_module('app').app is main.app


@pytest.mark.parametrize('scheme', ['postgres', 'postgresql', 'postgresql+psycopg'])
def test_postgres_url_uses_psycopg_and_external_pooling(monkeypatch, scheme):
    monkeypatch.setattr(get_settings(), 'database_url', f'{scheme}://user:password@localhost/nexus?sslmode=require')
    with patch.object(database, 'create_engine') as create:
        database.make_engine()
    url = create.call_args.args[0]
    assert url.drivername == 'postgresql+psycopg'
    assert url.query['sslmode'] == 'require'
    assert create.call_args.kwargs['poolclass'] is NullPool


def test_vercel_rejects_sqlite(monkeypatch):
    monkeypatch.setattr(get_settings(), 'vercel', True)
    with pytest.raises(ValueError, match='persistent PostgreSQL'):
        database.make_engine()


def test_request_bound_workflow_persists_result_without_background_task(monkeypatch):
    monkeypatch.setattr(get_settings(), 'vercel', True)
    with TestClient(main.app) as client:
        assert client.get('/api/health').json()['workflow_transport'] == 'request'
        response = client.post('/api/runs', json={'task': 'Create a logo', 'payment_mode': 'demo'})
        assert response.status_code == 201
        run = response.json()
        assert run['websocket'] is None
        assert run['status'] == 'completed'
        assert not main.tasks
        detail = client.get(f"/api/runs/{run['id']}").json()
        assert len(detail['events']) == 12
        assert detail['transaction']['value'] == 45
    with TestClient(main.app) as client:
        assert client.get(f"/api/runs/{run['id']}").json()['status'] == 'completed'


def test_serverless_cold_start_does_not_fail_another_instances_run(monkeypatch):
    monkeypatch.setattr(get_settings(), 'vercel', True)
    run_id = uid()
    with TestClient(main.app):
        with engine.begin() as connection:
            connection.execute(transactions.insert().values(
                id=run_id, task='Create a logo', budget=60, status='running',
                mode='demo', events=[], payment={}, created_at=now()))
        database.initialize()
        assert get_run(run_id)['status'] == 'running'
        with engine.begin() as connection:
            connection.execute(transactions.delete().where(transactions.c.id == run_id))


def test_request_timeout_is_persisted_and_returned(monkeypatch):
    monkeypatch.setattr(get_settings(), 'vercel', True)

    async def timeout(run_id):
        raise TimeoutError

    monkeypatch.setattr(main, 'execute', timeout)
    with TestClient(main.app) as client:
        run = client.post('/api/runs', json={'payment_mode': 'demo'}).json()
        detail = client.get(f"/api/runs/{run['id']}").json()
        assert detail['status'] == 'failed'
        assert 'deadline' in detail['error']


def test_request_bound_failure_is_visible(monkeypatch):
    monkeypatch.setattr(get_settings(), 'vercel', True)

    async def fail(state):
        raise ValueError('Provider rejected the workflow')

    from backend.workflow import workflow
    monkeypatch.setattr(workflow, 'ainvoke', fail)
    with TestClient(main.app) as client:
        run = client.post('/api/runs', json={'payment_mode': 'demo'}).json()
        assert run['status'] == 'failed'
        assert client.get(f"/api/runs/{run['id']}").json()['error'] == 'Provider rejected the workflow'


def test_postgres_payment_lock_retries_until_acquired(monkeypatch):
    from unittest.mock import MagicMock
    fake_engine = MagicMock()
    fake_engine.dialect.name = 'postgresql'
    connection = fake_engine.begin.return_value.__enter__.return_value
    connection.execute.return_value.scalar_one.side_effect = [False, True]
    monkeypatch.setattr(main, 'engine', fake_engine)

    async def acquire():
        async with main.payment_lock(uid()):
            assert connection.execute.call_count == 2
        assert fake_engine.begin.return_value.__exit__.called

    asyncio.run(acquire())
