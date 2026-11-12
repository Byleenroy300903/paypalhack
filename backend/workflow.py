import asyncio
from decimal import Decimal
from typing import TypedDict
from defusedxml.ElementTree import fromstring
from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.engine import Connection
from .config import get_settings
from .database import (agents, engine, get_run, negotiations, now, reputation_history,
                       transactions, trust_scores, uid, verification_results)
from .integrations import log_event, negotiate_with_ollama

ARTIFACT = '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="800" viewBox="0 0 800 800"><rect width="800" height="800" fill="#070b12"/><path d="M240 510V290h70l180 150V290h70v220h-70L310 360v150z" fill="#70c3ff"/><text x="400" y="610" text-anchor="middle" fill="white" font-family="sans-serif" font-size="36" letter-spacing="10">NEXUS</text></svg>'
AGENT_NAMES = ['Discovery Agent', 'Trust Agent', 'Negotiation Agent', 'Verification Agent', 'PayPal Agent', 'Reputation Agent']


class RunState(TypedDict, total=False):
    run_id: str
    task: str
    budget: str
    candidates: list[dict]
    selected: dict
    price: str
    verified: bool
    paid: bool
    payment_mode: str


def calculate_trust(agent: dict) -> tuple[float, dict]:
    jobs = max(0, agent['jobs'])
    factors = dict(reliability=max(0, min(100, agent['success'])), experience=100 * jobs / (jobs + 50),
                   disputes=max(0, 100 - 2000 * agent['disputes'] / max(1, jobs)), identity=100 if agent['identity_verified'] else 0)
    score = round(.45 * factors['reliability'] + .25 * factors['experience'] + .20 * factors['disputes'] + .10 * factors['identity'], 1)
    return score, factors


def verify_artifact(artifact: str, producer_id: str, verifier_id: str) -> dict:
    if producer_id == verifier_id:
        raise ValueError('An agent cannot verify its own work')
    try:
        root = fromstring(artifact)
        checks = {'svg_format': root.tag == '{http://www.w3.org/2000/svg}svg',
                  'dimensions': root.attrib.get('viewBox') == '0 0 800 800',
                  'vector_content': any(child.tag.endswith('}path') for child in root)}
    except Exception:
        checks = dict(svg_format=False, dimensions=False, vector_content=False)
    return dict(passed=all(checks.values()), score=round(sum(checks.values()) / 3 * 100), checks=checks)


async def record_event(run_id: str, stage: int, message: str) -> dict:
    with engine.begin() as connection:
        row = connection.execute(select(transactions).where(transactions.c.id == run_id).with_for_update()).mappings().one()
        event = dict(type='event', sequence=len(row['events']) + 1, stage=stage, agent=AGENT_NAMES[stage], message=message, time=now(), run_id=run_id)
        connection.execute(transactions.update().where(transactions.c.id == run_id).values(events=[*row['events'], event]))
    await log_event(event)
    return event


async def emit(state: RunState, stage: int, message: str) -> None:
    await record_event(state['run_id'], stage, message)
    await asyncio.sleep(get_settings().step_delay)


async def discover(state: RunState) -> dict:
    await emit(state, 0, 'Scanning the network for brand design agents.')
    with engine.connect() as connection:
        candidates = [dict(row) for row in connection.execute(select(agents).where(agents.c.id != 'verify')).mappings()]
    await emit(state, 0, f'{len(candidates)} qualified service agents discovered.')
    return {'candidates': candidates}


async def trust(state: RunState) -> dict:
    await emit(state, 1, 'Evaluating reliability, experience, disputes and identity.')
    scored = []
    with engine.begin() as connection:
        for agent in state['candidates']:
            score, factors = calculate_trust(agent)
            connection.execute(trust_scores.insert().values(id=uid(), agent_id=agent['id'], transaction_id=state['run_id'], score=score, factors=factors, created_at=now()))
            if score >= 85 and Decimal(str(agent['price'])) <= Decimal(state['budget']):
                scored.append((score, agent))
        if not scored:
            raise ValueError('No agent meets both the trust threshold and budget policy')
        selected = max(scored, key=lambda pair: pair[0])[1]
        connection.execute(transactions.update().where(transactions.c.id == state['run_id']).values(agent_id=selected['id'], trust=selected['trust']))
    await emit(state, 1, f"{selected['name']} selected. Trust {selected['trust']}/100. Risk: low.")
    return {'selected': selected}


async def negotiate(state: RunState) -> dict:
    price = Decimal(str(state['selected']['price'])).quantize(Decimal('.01'))
    await emit(state, 2, f"{state['selected']['name']} proposed ${price + 7}. Counteroffer sent: ${price}.")
    offer, model = await negotiate_with_ollama(state['task'], Decimal(state['budget']), price)
    with engine.begin() as connection:
        connection.execute(negotiations.insert().values(id=uid(), transaction_id=state['run_id'], agent_id=state['selected']['id'], proposal=price + 7, agreed=price,
            turns=[{'speaker': 'service', 'price': str(price + 7)}, {'speaker': 'user', 'price': str(price)}, {'speaker': 'service', **offer}], model=model))
        connection.execute(transactions.update().where(transactions.c.id == state['run_id']).values(value=price, payment={'mode': state.get('payment_mode', 'demo'), 'status': 'agreed', 'amount': str(price)}))
    await emit(state, 2, f'Agreement: ${price} USD. Contract price locked. Negotiation engine: {model}. {offer["rationale"]}')
    return {'price': str(price)}


async def verify(state: RunState) -> dict:
    await emit(state, 3, 'Sentinel is independently checking the demo SVG artifact.')
    result = verify_artifact(ARTIFACT, state['selected']['id'], 'verify')
    with engine.begin() as connection:
        connection.execute(verification_results.insert().values(id=uid(), transaction_id=state['run_id'], verifier_id='verify', artifact=ARTIFACT, **result))
        connection.execute(transactions.update().where(transactions.c.id == state['run_id']).values(delivery=result['score']))
    await emit(state, 3, f"{sum(result['checks'].values())}/3 structural checks passed. Creative quality requires human review.")
    return {'verified': result['passed']}


async def pay(state: RunState) -> dict:
    if not state.get('verified'):
        raise ValueError('Payment blocked: independent verification did not pass')
    sandbox_mode = state.get('payment_mode') == 'sandbox'
    await emit(state, 4, 'Verification gate passed. Preparing PayPal sandbox checkout.' if sandbox_mode else 'Verification gate passed. Requesting simulated payment release.')
    with engine.begin() as connection:
        verified = connection.execute(select(verification_results.c.passed).where(verification_results.c.transaction_id == state['run_id'])).scalar_one()
        if not verified:
            raise ValueError('Payment blocked by persisted verification result')
        if sandbox_mode:
            connection.execute(transactions.update().where(transactions.c.id == state['run_id']).values(payment={'mode': 'sandbox', 'status': 'awaiting_approval', 'amount': state['price']}))
    if sandbox_mode:
        await emit(state, 4, f"PayPal sandbox checkout ready: ${state['price']} USD. Buyer approval required; nothing has been captured.")
        return {'paid': False}
    with engine.begin() as connection:
        connection.execute(transactions.update().where(transactions.c.id == state['run_id']).values(payment={'mode': 'demo', 'status': 'released', 'amount': state['price'], 'reference': f"DEMO-{state['run_id'][:8]}"}))
    await emit(state, 4, f"Simulated PayPal payment released: ${state['price']} USD. No real money moved.")
    return {'paid': True}


async def reputation(state: RunState) -> dict:
    if state.get('payment_mode') == 'sandbox' and not state.get('paid'):
        await emit(state, 5, 'Verified delivery recorded. Reputation is pending sandbox settlement.')
        await emit(state, 5, 'Approve the order on PayPal, then authorize and capture. Reputation updates only after completed capture.')
        return {}
    if not state.get('paid'):
        raise ValueError('Reputation cannot increase without a settled outcome')
    await emit(state, 5, 'Recording the verified outcome in the reputation ledger.')
    with engine.begin() as connection:
        agent, after = record_reputation(connection, state['run_id'], state['selected']['id'], 'Verified demo delivery and simulated settlement')
    await emit(state, 5, f"{agent['name']} reputation {agent['trust']} → {after}. Trust compounds.")
    return {}


def record_reputation(connection: Connection, run_id: str, agent_id: str, reason: str) -> tuple[dict, float]:
    agent = dict(connection.execute(select(agents).where(agents.c.id == agent_id).with_for_update()).mappings().one())
    existing = connection.execute(select(reputation_history).where(reputation_history.c.transaction_id == run_id)).mappings().first()
    if existing:
        return agent, existing['after']
    after = round(min(99.9, agent['trust'] + .2), 1)
    connection.execute(reputation_history.insert().values(id=uid(), transaction_id=run_id, agent_id=agent_id,
        before=agent['trust'], after=after, reason=reason, created_at=now()))
    connection.execute(agents.update().where(agents.c.id == agent_id).values(trust=after, jobs=agent['jobs'] + 1))
    connection.execute(transactions.update().where(transactions.c.id == run_id).values(trust=after))
    return agent, after


graph_builder = StateGraph(RunState)
for name, action in [('discover', discover), ('trust', trust), ('negotiate', negotiate), ('verify', verify), ('pay', pay), ('reputation', reputation)]:
    graph_builder.add_node(name, action)
graph_builder.add_edge(START, 'discover')
graph_builder.add_edge('discover', 'trust')
graph_builder.add_edge('trust', 'negotiate')
graph_builder.add_edge('negotiate', 'verify')
graph_builder.add_conditional_edges('verify', lambda state: 'pay' if state.get('verified') else 'blocked', {'pay': 'pay', 'blocked': END})
graph_builder.add_edge('pay', 'reputation')
graph_builder.add_edge('reputation', END)
workflow = graph_builder.compile()


async def execute(run_id: str) -> None:
    row = get_run(run_id)
    if row is None:
        return
    try:
        result = await workflow.ainvoke({'run_id': run_id, 'task': row['task'], 'budget': str(row['budget']), 'payment_mode': row['mode']})
        if not result.get('paid') and not (row['mode'] == 'sandbox' and result.get('verified')):
            raise ValueError('Verification failed. Payment was not released.')
        with engine.begin() as connection:
            connection.execute(transactions.update().where(transactions.c.id == run_id).values(status='completed'))
    except Exception as error:
        with engine.begin() as connection:
            connection.execute(transactions.update().where(transactions.c.id == run_id).values(status='failed', error=str(error)))