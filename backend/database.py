from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from sqlalchemy import (JSON, Boolean, Column, Float, ForeignKey, Integer, MetaData,
                        Numeric, String, Table, Text, create_engine, select)
from sqlalchemy.engine import make_url
from .config import PROJECT_ROOT, get_settings

metadata = MetaData()
agents = Table('agents', metadata,
    Column('id', String(40), primary_key=True), Column('name', String(100), nullable=False),
    Column('role', String(100), nullable=False), Column('trust', Float, nullable=False),
    Column('success', Float, nullable=False), Column('jobs', Integer, nullable=False),
    Column('disputes', Integer, nullable=False), Column('price', Numeric(12, 2), nullable=False),
    Column('identity_verified', Boolean, nullable=False, default=True))
transactions = Table('transactions', metadata,
    Column('id', String(36), primary_key=True), Column('agent_id', ForeignKey('agents.id')),
    Column('task', Text, nullable=False), Column('budget', Numeric(12, 2), nullable=False),
    Column('value', Numeric(12, 2), nullable=False, default=0), Column('status', String(30), nullable=False),
    Column('mode', String(20), nullable=False, default='demo'), Column('delivery', Float, default=0),
    Column('trust', Float, default=0), Column('events', JSON, nullable=False, default=list),
    Column('payment', JSON, nullable=False, default=dict), Column('error', Text),
    Column('created_at', String(40), nullable=False))
trust_scores = Table('trust_scores', metadata,
    Column('id', String(36), primary_key=True), Column('agent_id', ForeignKey('agents.id'), nullable=False),
    Column('transaction_id', ForeignKey('transactions.id'), nullable=False), Column('score', Float, nullable=False),
    Column('factors', JSON, nullable=False), Column('created_at', String(40), nullable=False))
negotiations = Table('negotiations', metadata,
    Column('id', String(36), primary_key=True), Column('transaction_id', ForeignKey('transactions.id'), nullable=False, unique=True),
    Column('agent_id', ForeignKey('agents.id'), nullable=False), Column('proposal', Numeric(12, 2), nullable=False),
    Column('agreed', Numeric(12, 2), nullable=False), Column('turns', JSON, nullable=False),
    Column('model', String(100), nullable=False))
verification_results = Table('verification_results', metadata,
    Column('id', String(36), primary_key=True), Column('transaction_id', ForeignKey('transactions.id'), nullable=False, unique=True),
    Column('verifier_id', ForeignKey('agents.id'), nullable=False), Column('passed', Boolean, nullable=False),
    Column('score', Float, nullable=False), Column('checks', JSON, nullable=False), Column('artifact', Text, nullable=False))
reputation_history = Table('reputation_history', metadata,
    Column('id', String(36), primary_key=True), Column('transaction_id', ForeignKey('transactions.id'), nullable=False, unique=True),
    Column('agent_id', ForeignKey('agents.id'), nullable=False), Column('before', Float, nullable=False),
    Column('after', Float, nullable=False), Column('reason', Text, nullable=False), Column('created_at', String(40), nullable=False))
checkout_sessions = Table('checkout_sessions', metadata,
    Column('transaction_id', ForeignKey('transactions.id'), primary_key=True),
    Column('token_hash', String(64), nullable=False),
    Column('expires_at', Float, nullable=False))

SEED_AGENTS = [
    dict(id='aura', name='Aura Creative', role='Brand & visual design', trust=98.0, success=99.2, jobs=1248, disputes=2, price=45),
    dict(id='pixel', name='Pixel Forge', role='Digital design specialist', trust=94.0, success=97.8, jobs=862, disputes=5, price=52),
    dict(id='nova', name='Nova Studio', role='Generative brand systems', trust=89.0, success=95.1, jobs=634, disputes=8, price=38),
    dict(id='vector', name='Vector Labs', role='Illustration & iconography', trust=82.0, success=92.4, jobs=391, disputes=14, price=30),
    dict(id='verify', name='Sentinel', role='Independent verification', trust=99.0, success=99.8, jobs=3402, disputes=0, price=0),
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def uid() -> str:
    return str(uuid4())


def make_engine():
    parsed_url = make_url(get_settings().database_url)
    if parsed_url.get_backend_name() != 'sqlite':
        raise ValueError('This application uses SQLite; set DATABASE_URL to a SQLite URL.')
    if parsed_url.database not in (None, '', ':memory:'):
        database_path = Path(parsed_url.database)
        if not database_path.is_absolute():
            database_path = PROJECT_ROOT / database_path
        database_path.parent.mkdir(parents=True, exist_ok=True)
        parsed_url = parsed_url.set(database=str(database_path))
    return create_engine(parsed_url, pool_pre_ping=True, connect_args={'check_same_thread': False})


engine = make_engine()


def initialize() -> None:
    metadata.create_all(engine)
    with engine.begin() as connection:
        for agent in SEED_AGENTS:
            if connection.execute(select(agents.c.id).where(agents.c.id == agent['id'])).first() is None:
                connection.execute(agents.insert().values(**agent, identity_verified=True))
        connection.execute(transactions.update().where(transactions.c.status == 'running').values(status='failed', error='Worker restarted. Start a new demo run.'))


def get_run(run_id: str) -> dict | None:
    with engine.connect() as connection:
        row = connection.execute(select(transactions).where(transactions.c.id == run_id)).mappings().first()
        return dict(row) if row else None


def transaction_view(row: dict) -> dict:
    sandbox = row['payment'].get('sandbox', {})
    payment_status = ('captured' if sandbox.get('capture') else 'authorized' if sandbox.get('authorization')
                      else 'awaiting_approval' if sandbox.get('order') else row['payment'].get('status', 'pending'))
    return dict(id=row['id'], agent=next((agent['name'] for agent in SEED_AGENTS if agent['id'] == row['agent_id']), 'Pending'),
                task=row['task'], trust=row['trust'], value=float(row['value']),
                status='Completed' if row['status'] == 'completed' else row['status'].title(),
                delivery=row['delivery'], date=row['created_at'], mode=row['mode'],
                payment_status=payment_status, capture_id=sandbox.get('capture', {}).get('id'))