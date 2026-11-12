# Three-Minute Demo

## Before The Stage

Open the overview at 1440px or larger, start FastAPI and confirm **FastAPI engine connected**. Configure Ollama Cloud, Elasticsearch and PayPal sandbox credentials before presenting. Keep the mission at "Create a logo for my startup." with a $60 budget, and prepare a separate sandbox buyer account. Simulations always use PayPal sandbox and Elasticsearch. If Ollama fails for any reason (for example HTTP 402, no credits), the hardcoded offer is used, the reason is labeled in the event feed, and the run continues. No real money moves in either mode.

## 0:00-0:25 — The Problem

**Show: Overview and trust graph.**

"Humans already use PayPal to pay each other. Soon AI agents will hire other agents. But how does one agent know another agent will deliver? Before autonomous commerce needs payments, it needs trust. This is PayPal Nexus: the trust network for autonomous AI commerce."

## 0:25-0:45 — One Human Intent

**Click: Launch simulation.**

"My startup needs a logo. I set a task and a budget. A team of specialized agents handles the rest. Watch the network and the conversation together."

## 0:45-1:15 — Six Accountable Decisions

**Show: Live simulation and communication feed.**

"Discovery finds four specialists. Trust compares reliability, experience, disputes and identity. Aura wins on track record. Ollama negotiates the fixed $45 contract, with application-enforced budget rules. Sentinel independently checks the delivered SVG. Only after that verification gate is sandbox checkout available. Reputation waits for settlement."

"We are deliberately separating creative judgment from structural checks: this demo verifies format, dimensions and vector content, not whether a human loves the logo."

## 1:15-1:40 — Proof, Not Promises

**Click: Download demo logo, then View transaction.**

"Here is a downloadable sample artifact and the $45 contract. Every event, negotiation and verification result is persisted. Now I create a real PayPal sandbox order, approve it with a sandbox buyer account, authorize it, and capture test funds. The server independently checks approval and the exact amount. The UI displays the capture reference."

Allow extra time for the buyer login and network latency. Do not claim capture or reputation changes before the capture confirmation appears.

## 1:40-2:05 — Trust Compounds

**Click: Trust network. Select Aura, then Vector Labs.**

"Trust is earned, not self-reported. Aura's score increased after verified settlement. Compare its history with an agent with more disputes. The next agent making a purchasing decision gets evidence, not a marketing claim. Independent verification and transparent scoring are the beginning of agent governance."

## 2:05-2:35 — Under The Hood

**Show: How Nexus Works or the architecture diagram.**

"Angular makes the workflow visible. FastAPI streams durable events over WebSockets. LangGraph orchestrates six policy-controlled nodes. SQLite stores the audit trail; the transaction center searches actual Elasticsearch event documents. Ollama Cloud contributes validated negotiation advice, while hard budget and verification rules remain outside the model. PayPal provides connected sandbox payment rails. A model can propose a deal; it cannot bypass a payment gate."

## 2:35-3:00 — The Future

**Click: The bigger picture.**

"Today it's a logo. Tomorrow it's a research agent hiring an analyst, a logistics agent buying capacity, or a startup assembling an entire AI workforce. Humans built trust systems for humans. PayPal Nexus builds trust systems for AI agents. The future isn't just autonomous. It's accountable."

## Judge Questions

**Is this escrow?** No. Demo reservation is simulated; sandbox integration uses PayPal authorization/capture, not regulated escrow.

**Which agents use an LLM?** Negotiation calls Ollama Cloud. Other nodes use deterministic policies; all six have role prompts available for extension.

**What if verification fails?** The graph stops before payment. The PayPal function separately checks persisted verification, and reputation does not increase.

**Can you use real money?** Not in this build. The host is sandbox-only. Live commerce requires stronger identity, compliance, dispute resolution, provider reconciliation and durable execution.

**What is the innovation?** A shared, inspectable trust and reputation layer between autonomous discovery and payment, rather than a single agent with a credit card.