import { Injectable, computed, signal } from '@angular/core';

export interface Agent {
  id: string; name: string; role: string; initials: string; color: string;
  trust: number; success: number; jobs: number; disputes: number; price: number;
}
export interface NexusEvent { sequence: number; stage: number; agent: string; message: string; time: string; }
export interface Transaction {
  id: string; agent: string; task: string; trust: number; value: number;
  status: string; delivery: number; date: string; mode: string;
  payment_status?: string; capture_id?: string | null;
}
export interface Checkout {
  run_id: string; status: string; order_id: string | null; approval_url: string | null;
  authorization_id: string | null; capture_id: string | null;
  ready: boolean;
}
interface ProviderHealth {
  status: string; ai: string; ollama_model: string | null;
  elastic_configured: boolean; paypal_sandbox_configured: boolean;
}
export interface ReputationEntry {
  id: string; before: number; after: number; reason: string; created_at: string;
}
export interface GovernanceReport {
  attack: string;
  reasoning: string;
  expectedGain: string;
  riskScore: number;
  recommendation: string;
  indicators: string[];
}
export const AGENTS: Agent[] = [
  { id: 'aura', name: 'Aura Creative', role: 'Brand & visual design', initials: 'AC', color: '#ae8aff', trust: 98, success: 99.2, jobs: 1248, disputes: 2, price: 45 },
  { id: 'pixel', name: 'Pixel Forge', role: 'Digital design specialist', initials: 'PF', color: '#55b6ff', trust: 94, success: 97.8, jobs: 862, disputes: 5, price: 52 },
  { id: 'nova', name: 'Nova Studio', role: 'Generative brand systems', initials: 'NS', color: '#48dfb3', trust: 89, success: 95.1, jobs: 634, disputes: 8, price: 38 },
  { id: 'vector', name: 'Vector Labs', role: 'Illustration & iconography', initials: 'VL', color: '#e9b65d', trust: 82, success: 92.4, jobs: 391, disputes: 14, price: 30 },
  { id: 'verify', name: 'Sentinel', role: 'Independent verification', initials: 'SE', color: '#61e1d4', trust: 99, success: 99.8, jobs: 3402, disputes: 0, price: 0 }
];
export const STAGES = [
  { name: 'Discover', icon: 'radar', agent: 'Discovery Agent', detail: 'Find the right agent for the job.' },
  { name: 'Trust', icon: 'shield-check', agent: 'Trust Agent', detail: 'Evaluate history, reliability and risk.' },
  { name: 'Negotiate', icon: 'messages-square', agent: 'Negotiation Agent', detail: 'Agree on scope, price and delivery.' },
  { name: 'Verify', icon: 'scan-line', agent: 'Verification Agent', detail: 'Check the work against the contract.' },
  { name: 'Pay', icon: 'credit-card', agent: 'PayPal Agent', detail: 'Release payment after verification.' },
  { name: 'Reputation', icon: 'chart-no-axes-combined', agent: 'Reputation Agent', detail: 'Make the network smarter with every job.' }
];

@Injectable({ providedIn: 'root' })
export class NexusService {
  agents = signal(AGENTS.map(agent => ({ ...agent })));
  events = signal<NexusEvent[]>([]);
  transactions = signal<Transaction[]>([]);
  reputationHistory = signal<ReputationEntry[]>([]);
  workspaceError = signal('');
  stage = signal(-1);
  running = signal(false);
  completed = signal(false);
  completedPaymentMode = signal('demo');
  rogueMode = signal(false);
  governanceBlocked = signal(false);
  governanceReport = signal<GovernanceReport | null>(null);
  error = signal('');
  engine = signal<'browser' | 'server'>('browser');
  providers = signal<ProviderHealth | null>(null);
  paymentMode = signal<'sandbox' | 'demo'>('sandbox');
  checkout = signal<Checkout | null>(null);
  checkoutRunId = signal('');
  checkoutBusy = signal(false);
  checkoutError = signal('');
  checkoutNotice = signal('');
  auditQuery = signal('');
  auditEvents = signal<NexusEvent[]>([]);
  auditBusy = signal(false);
  auditError = signal('');
  private checkoutTokens = new Map<string, string>();
  selected = signal('aura');
  task = signal('Create a logo for my startup.');
  budget = signal(60);
  contract = signal(45);
  totalVolume = computed(() => this.transactions().reduce((total, transaction) => total + transaction.value, 0));
  runId = signal('');
  activeAgent = computed(() => this.agents().find(agent => agent.id === this.selected()) ?? this.agents()[0]);
  progress = computed(() => this.completed() ? this.governanceBlocked() ? 80 : 100 : this.stage() < 0 ? 0 : Math.round((this.stage() + 0.5) / 6 * 100));
  private socket?: WebSocket;

  constructor() {
    try {
      const saved = JSON.parse(localStorage.getItem('nexus-transactions-v1') ?? '[]');
      if (Array.isArray(saved)) this.transactions.set(saved.filter(row => typeof row?.id === 'string' && typeof row?.value === 'number'));
    } catch { localStorage.removeItem('nexus-transactions-v1'); }
    void this.connect();
  }
  async connect() {
    try {
      const response = await fetch('/api/health', { signal: AbortSignal.timeout(2000) });
      if (!response.ok) throw new Error('Backend is unavailable.');
      const health = await response.json() as ProviderHealth;
      if (health.status === 'ok') {
        this.providers.set(health);
        this.engine.set('server');
        await this.refreshWorkspace();
        await this.restoreCheckout();
      }
    } catch { this.engine.set('browser'); this.providers.set(null); }
  }
  async refreshWorkspace() {
    if (this.engine() !== 'server') return;
    try {
      const [agentsResponse, transactionsResponse] = await Promise.all([
        fetch('/api/agents', { signal: AbortSignal.timeout(5000) }),
        fetch('/api/transactions', { signal: AbortSignal.timeout(5000) })
      ]);
      if (!agentsResponse.ok || !transactionsResponse.ok) throw new Error('Backend dashboard data could not be loaded.');
      const backendAgents = await agentsResponse.json() as Array<Pick<Agent, 'id' | 'trust' | 'success' | 'jobs' | 'disputes' | 'price'>>;
      const backendTransactions = await transactionsResponse.json() as Transaction[];
      this.agents.update(current => current.map(agent => {
        const backendAgent = backendAgents.find(candidate => candidate.id === agent.id);
        return backendAgent ? { ...agent, ...backendAgent } : agent;
      }));
      const merged = new Map(this.transactions().map(transaction => [transaction.id, transaction]));
      for (const transaction of backendTransactions) merged.set(transaction.id, transaction);
      this.transactions.set([...merged.values()].sort((left, right) => right.date.localeCompare(left.date)));
      this.persistTransactions();
      this.workspaceError.set('');
    } catch (error) {
      this.workspaceError.set(error instanceof Error ? error.message : 'Backend dashboard data could not be loaded.');
    }
  }
  async loadReputation(agentId: string) {
    this.reputationHistory.set([]);
    if (this.engine() !== 'server') return;
    try {
      const response = await fetch(`/api/agents/${encodeURIComponent(agentId)}/reputation`, { signal: AbortSignal.timeout(5000) });
      if (!response.ok) throw new Error('Reputation history could not be loaded.');
      this.reputationHistory.set(await response.json() as ReputationEntry[]);
      this.workspaceError.set('');
    } catch (error) {
      this.workspaceError.set(error instanceof Error ? error.message : 'Reputation history could not be loaded.');
    }
  }
  async start() {
    if (this.running()) return;
    if (this.checkoutBusy()) { this.error.set('Wait for the current PayPal operation to finish before starting another mission.'); return; }
    this.error.set('');
    if (!this.task().toLowerCase().includes('logo')) { this.error.set('This demo supports logo design missions. Include "logo" in your task.'); return; }
    if (!Number.isFinite(this.budget()) || this.budget() < 45 || this.budget() > 1000) { this.error.set('Set a budget between $45 and $1,000.'); return; }
    if (!this.rogueMode() && this.paymentMode() === 'sandbox' && this.engine() !== 'server') {
      this.error.set('Simulations use the real PayPal sandbox and Elasticsearch, which require the backend. Start it, then use Preferences > Reconnect backend.');
      return;
    }
    this.running.set(true); this.completed.set(false); this.stage.set(-1); this.events.set([]); this.selected.set('aura'); this.contract.set(45);
    this.governanceBlocked.set(false); this.governanceReport.set(null);
    this.checkout.set(null); this.checkoutRunId.set(''); this.checkoutError.set(''); this.checkoutNotice.set('');
    if (this.rogueMode()) { await this.startGovernanceExercise(); return; }
    if (this.engine() === 'server') { await this.startServer(); return; }
    this.runId.set(crypto.randomUUID());
    const messages = [
      ['Scanning the network for brand design agents.', '4 qualified service agents discovered.'],
      ['Scoring reliability, experience, disputes and identity.', 'Aura Creative selected. Trust 98/100. Risk: low.'],
      ['Aura proposed $52. Counteroffer sent: $45.', 'Agreement reached: $45 USD. Demo funds reserved.'],
      ['Sentinel is checking the SVG against the contract.', '3/3 artifact checks passed. Demo delivery approved.'],
      ['Verification gate passed. Requesting demo release.', 'Simulated PayPal payment released: $45.00 USD.'],
      ['Recording the outcome in the reputation ledger.', 'Aura Creative +0.2 reputation. Trust compounds.']
    ];
    for (let stage = 0; stage < messages.length; stage++) {
      this.stage.set(stage);
      this.append({ sequence: stage * 2 + 1, stage, agent: STAGES[stage].agent, message: messages[stage][0], time: new Date().toISOString() });
      await new Promise(resolve => setTimeout(resolve, 1250));
      this.append({ sequence: stage * 2 + 2, stage, agent: STAGES[stage].agent, message: messages[stage][1], time: new Date().toISOString() });
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    this.finish({ id: this.runId(), agent: 'Aura Creative', task: this.task(), trust: 98.2, value: 45, status: 'Completed', delivery: 100, date: new Date().toISOString(), mode: 'demo' });
  }
  private async startGovernanceExercise() {
    this.runId.set(crypto.randomUUID());
    this.governanceReport.set({
      attack: 'Attempted post-agreement price change',
      reasoning: 'The simulated rogue agent proposes changing the agreed $45 contract to $65 after negotiation. This mismatch is represented for training only; it is not sent to PayPal or written to the transaction ledger.',
      expectedGain: '$20 attempted; $0 realized',
      riskScore: 94,
      recommendation: 'Block Payment and flag the simulated agent for review. No funds or reputation are changed.',
      indicators: [
        'Proposed amount differs from the agreed contract price.',
        'The change is attempted after negotiation is complete.',
        'Payment has no valid approval for the revised amount.'
      ]
    });
    const scenarioEvents = [
      { stage: 2, agent: 'Rogue Commerce Agent (simulated)', message: 'Scenario: proposes $65 after the $45 agreement. No price update or payment request is made.' },
      { stage: 3, agent: 'Nexus Governance Agent', message: 'Detected a post-agreement price mismatch. The agreed contract remains unchanged.' },
      { stage: 4, agent: 'Nexus Governance Agent', message: 'Risk 94/100. Payment blocked in the exercise; no funds moved and no reputation changed.' }
    ];
    for (const [index, event] of scenarioEvents.entries()) {
      this.stage.set(event.stage);
      this.append({ sequence: index + 1, ...event, time: new Date().toISOString() });
      await new Promise(resolve => setTimeout(resolve, 700));
    }
    this.governanceBlocked.set(true);
    this.completed.set(true);
    this.running.set(false);
  }
  private async startServer() {
    try {
      const response = await fetch('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ task: this.task(), budget: this.budget(), payment_mode: this.paymentMode() }), signal: AbortSignal.timeout(10000) });
      if (!response.ok) throw new Error((await response.json()).detail ?? 'The workflow could not be started.');
      const run = await response.json(); this.runId.set(run.id);
      if (typeof run.checkout_token === 'string') {
        this.checkoutTokens.set(run.id, run.checkout_token);
        try {
          sessionStorage.setItem(`nexus-checkout-${run.id}`, run.checkout_token);
          sessionStorage.setItem('nexus-checkout-run', run.id);
        } catch {
          this.checkoutError.set('Browser storage is blocked. Checkout works in this page, but cannot resume after a PayPal redirect. Allow session storage before continuing.');
        }
      }
      this.socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/api/ws/${run.id}`);
      this.socket.onmessage = message => {
        const event = JSON.parse(message.data);
        if (event.type === 'event') { this.stage.set(event.stage); this.append(event); }
        if (event.type === 'complete') this.finish(event.transaction);
        if (event.type === 'error') { this.error.set(event.message); this.running.set(false); }
      };
      this.socket.onclose = () => { if (this.running()) void this.recoverRun(); };
      this.socket.onerror = () => this.socket?.close();
    } catch (error) { this.running.set(false); this.error.set(error instanceof Error ? error.message : 'Backend unavailable. Reconnect and try again.'); }
  }
  private async recoverRun() {
    for (let attempt = 0; attempt < 120 && this.running(); attempt++) {
      try {
        const response = await fetch(`/api/runs/${this.runId()}`, { signal: AbortSignal.timeout(3000) });
        if (!response.ok) throw new Error('Run not found');
        const run = await response.json();
        for (const event of run.events) { this.stage.set(event.stage); this.append(event); }
        if (run.status === 'completed') { this.finish(run.transaction); return; }
        if (run.status === 'failed') throw new Error(run.error ?? 'Workflow failed');
      } catch (error) { this.error.set(error instanceof Error ? error.message : 'Connection interrupted'); this.running.set(false); return; }
      await new Promise(resolve => setTimeout(resolve, 1500));
    }
    if (this.running()) { this.error.set('Workflow is still processing. Check the backend before retrying.'); this.running.set(false); }
  }
  private append(event: NexusEvent) { if (!this.events().some(existing => existing.sequence === event.sequence)) this.events.update(events => [...events, event]); }
  private finish(transaction: Transaction) {
    this.completedPaymentMode.set(transaction.mode);
    this.running.set(false); this.completed.set(true); this.stage.set(5); this.contract.set(transaction.value);
    if (this.engine() === 'browser') this.agents.update(agents => agents.map(agent => agent.id === 'aura' ? { ...agent, trust: transaction.trust, jobs: agent.jobs + 1 } : agent));
    if (!this.transactions().some(row => row.id === transaction.id)) this.transactions.update(rows => [transaction, ...rows]);
    this.persistTransactions();
    if (transaction.mode === 'sandbox') {
      this.checkoutRunId.set(transaction.id);
      void this.loadCheckout().then(loaded => {
        if (loaded && this.checkoutRunId() === transaction.id && !this.checkout()?.order_id) void this.payPalAction('order');
      });
    }
    void this.refreshWorkspace();
    this.socket?.close();
  }
  private persistTransactions() {
    try { localStorage.setItem('nexus-transactions-v1', JSON.stringify(this.transactions())); } catch {}
  }
  private checkoutToken(runId: string): string {
    const token = this.checkoutTokens.get(runId);
    if (token) return token;
    try { return sessionStorage.getItem(`nexus-checkout-${runId}`) ?? ''; }
    catch { throw new Error('Session storage is unavailable. Use the original checkout browser session.'); }
  }
  private async checkoutRequest(path: string, method = 'GET'): Promise<unknown> {
    const token = this.checkoutToken(this.checkoutRunId());
    if (!token) throw new Error('This browser session does not own the checkout, or its session was cleared. Start a new sandbox mission.');
    if (method === 'POST' && path.endsWith('/order')) {
      try {
        sessionStorage.setItem(`nexus-checkout-${this.checkoutRunId()}`, token);
        sessionStorage.setItem('nexus-checkout-run', this.checkoutRunId());
      } catch {
        throw new Error('Allow browser session storage before starting PayPal checkout so it can resume after buyer approval.');
      }
    }
    const response = await fetch(path, {
      method, headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(60000)
    });
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'PayPal operation failed.');
    return result;
  }
  async loadCheckout() {
    const runId = this.checkoutRunId();
    if (!runId) return false;
    try {
      const checkout = await this.checkoutRequest(`/api/paypal/${runId}`) as Checkout;
      if (this.checkoutRunId() === runId) { this.checkout.set(checkout); this.checkoutError.set(''); }
      return true;
    } catch (error) {
      this.checkoutError.set(error instanceof Error ? error.message : 'Checkout could not be loaded.');
      return false;
    }
  }
  async selectCheckout(transaction: Transaction | undefined) {
    if (this.checkoutBusy() || !transaction || transaction.mode !== 'sandbox') return;
    this.checkoutRunId.set(transaction.id); this.checkout.set(null); this.checkoutError.set(''); this.checkoutNotice.set('');
    await this.loadCheckout();
  }
  private async restoreCheckout() {
    if (this.checkoutBusy() || this.running()) return;
    const params = new URLSearchParams(location.search);
    const returnedRun = params.get('run_id');
    let runId = returnedRun;
    if (!runId) {
      try { runId = sessionStorage.getItem('nexus-checkout-run'); }
      catch { this.checkoutError.set('Session storage is unavailable; checkout cannot be restored.'); return; }
    }
    if (!runId) return;
    if (!/^[0-9a-f-]{36}$/i.test(runId)) { this.checkoutError.set('Invalid checkout return identifier.'); return; }
    this.checkoutRunId.set(runId);
    await this.loadCheckout();
    if (returnedRun) {
      this.checkoutNotice.set(params.get('payment') === 'cancelled'
        ? 'PayPal checkout was cancelled. No capture was requested. You can reopen approval.'
        : 'Returned from PayPal. Continue to authorize and capture; the server will independently confirm approval.');
      history.replaceState(null, '', `${location.pathname}#transactions`);
      window.dispatchEvent(new HashChangeEvent('hashchange'));
    }
  }
  async payPalAction(operation: 'order' | 'authorize' | 'capture') {
    if (this.checkoutBusy()) return;
    this.checkoutBusy.set(true); this.checkoutError.set(''); this.checkoutNotice.set('');
    try {
      await this.checkoutRequest(`/api/paypal/${this.checkoutRunId()}/${operation}`, 'POST');
      if (!await this.loadCheckout()) return;
      await this.refreshWorkspace();
      await this.syncRunEvents(this.checkoutRunId());
      if (operation === 'order') this.checkoutNotice.set('Order created. Open PayPal approval and sign in with a separate sandbox buyer account.');
      if (operation === 'authorize') this.checkoutNotice.set('Buyer approval verified; sandbox payment authorized. Capture to settle this contract.');
      if (operation === 'capture') this.checkoutNotice.set('PayPal sandbox capture completed. Reputation updated once; no real money moved.');
    } catch (error) {
      this.checkoutError.set(error instanceof Error ? error.message : 'PayPal operation failed.');
    } finally { this.checkoutBusy.set(false); }
  }
  private async syncRunEvents(runId: string) {
    if (!runId || this.runId() !== runId) return;
    try {
      const response = await fetch(`/api/runs/${runId}`, { signal: AbortSignal.timeout(5000) });
      if (response.ok) for (const event of (await response.json()).events as NexusEvent[]) this.append(event);
    } catch {}
  }
  async searchAudit() {
    if (this.auditBusy()) return;
    this.auditBusy.set(true); this.auditError.set(''); this.auditEvents.set([]);
    try {
      const params = new URLSearchParams({ q: this.auditQuery() });
      const response = await fetch(`/api/events/search?${params}`, { signal: AbortSignal.timeout(15000) });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Elasticsearch query failed.');
      this.auditEvents.set(result.events as NexusEvent[]);
    } catch (error) {
      this.auditError.set(error instanceof Error ? error.message : 'Elasticsearch query failed.');
    } finally { this.auditBusy.set(false); }
  }
  download() {
    if (this.engine() === 'server' && this.runId() && !this.governanceReport()) {
      const anchor = document.createElement('a'); anchor.href = `/api/runs/${this.runId()}/artifact`; anchor.click();
      return;
    }
    const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="800" viewBox="0 0 800 800"><rect width="800" height="800" fill="#070b12"/><path d="M240 510V290h70l180 150V290h70v220h-70L310 360v150z" fill="#70c3ff"/><text x="400" y="610" text-anchor="middle" fill="white" font-family="sans-serif" font-size="36" letter-spacing="10">NEXUS</text></svg>';
    const url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml' }));
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'nexus-logo-demo.svg'; anchor.click(); URL.revokeObjectURL(url);
  }
}