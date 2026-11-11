# JACK

Orchestratore privato multi-agente per business digitali. Il backend attuale offre task persistenti, workflow sequenziali, ricerca con provenienza, validazione prudenziale, portafoglio, raccomandazioni e pianificazione MVP. Non sviluppa o distribuisce prodotti autonomamente e non esegue pagamenti o allocazioni di capitale.

[Indice completo e navigabile](docs/milestones/README.md) · [Backend e verifiche](backend/README.md) · [Fonti storiche e lacune](docs/milestones/SOURCES.md)

## Milestone implementate

- [01–08 — Fondamenta e Task Engine](docs/milestones/01-08-core-infrastructure.md)
- [09.1 — Multi-Agent Foundation](docs/milestones/09.1-multi-agent-foundation.md)
- [09.2 — Agent Orchestration](docs/milestones/09.2-agent-orchestration.md)
- [09.3 — Business Research](docs/milestones/09.3-business-research.md)
- [09.4 — Internet Research](docs/milestones/09.4-internet-research.md)
- [09.5 — Commercial Intelligence](docs/milestones/09.5-commercial-intelligence.md)
- [09.6 — Business Validation](docs/milestones/09.6-business-validation.md)
- [09.7 — Business Portfolio](docs/milestones/09.7-business-portfolio.md)
- [09.8 — Portfolio Decision Engine](docs/milestones/09.8-portfolio-decisions.md)
- [10.1 — Execution Planner](docs/milestones/10.1-execution-planner.md)

## Milestone future — proposte

- [10.2 — Development Agent](docs/milestones/10.2-development-agent.md)
- [10.3 — Sandbox & Execution Runtime](docs/milestones/10.3-sandbox-execution-runtime.md)
- [10.4 — QA & Security Agent](docs/milestones/10.4-qa-security-agent.md)
- [10.5 — Deployment Agent](docs/milestones/10.5-deployment-agent.md)
- [10.6 — Product Lifecycle Manager](docs/milestones/10.6-product-lifecycle-manager.md)
- [11.1 — Pricing Intelligence](docs/milestones/11.1-pricing-intelligence.md)
- [11.2 — Payments & Subscriptions](docs/milestones/11.2-payments-subscriptions.md)
- [11.3 — Growth Agent](docs/milestones/11.3-growth-agent.md)
- [11.4 — Marketing Automation](docs/milestones/11.4-marketing-automation.md)
- [11.5 — Customer Support Agent](docs/milestones/11.5-customer-support-agent.md)
- [11.6 — Revenue Analytics](docs/milestones/11.6-revenue-analytics.md)
- [12.1 — Business Operations Agent](docs/milestones/12.1-business-operations-agent.md)
- [12.2 — Financial Intelligence](docs/milestones/12.2-financial-intelligence.md)
- [12.3 — Capital Allocation Engine](docs/milestones/12.3-capital-allocation-engine.md)
- [12.4 — Risk Management Engine](docs/milestones/12.4-risk-management-engine.md)
- [12.5 — Autonomous Decision Policies](docs/milestones/12.5-autonomous-decision-policies.md)
- [12.6 — Business Scaling & Shutdown](docs/milestones/12.6-business-scaling-shutdown.md)
- [13 — Continuous Opportunity Discovery](docs/milestones/13-continuous-opportunity-discovery.md)
- [14 — Portfolio Optimization](docs/milestones/14-portfolio-optimization.md)
- [15 — Autonomous Business Ecosystem](docs/milestones/15-autonomous-business-ecosystem.md)

## Uso e documentazione

Il codice e in `backend`. Le istruzioni, gli esempi Python/JSON e le configurazioni esistenti sono conservati nei singoli documenti milestone. I comandi Windows di verifica sono nel README backend. La specifica originale [Execution Planning](backend/EXECUTION_PLANNING.md) resta disponibile.

Il database locale e SQLite (`backend/jack.db`). Le migrazioni sono esplicite: da `backend`, `.venv\Scripts\alembic.exe upgrade head` modifica il database configurato; i test verificano le migrazioni su database temporanei. Le API attuali non implementano autenticazione/RBAC: esporle solo entro un confine di accesso fidato. La ricerca di default e offline e quella live richiede configurazione esplicita.

Per nuove schede usare il [template uniforme](docs/milestones/TEMPLATE.md). Stato delle verifiche di questa riorganizzazione: [VERIFICATION.md](docs/milestones/VERIFICATION.md).
