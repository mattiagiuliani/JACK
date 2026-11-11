# JACK backend

JACK is a private multi-agent orchestrator for digital businesses. Future economic
autonomy requires explicit risk limits and authorization controls.

## Milestone 09.1: Multi-Agent Foundation

- `app.agents.Agent` is a synchronous abstract contract: `execute(task: Task) -> str`.
  Agents receive task snapshots, return text, and raise exceptions on failure.
- `AgentRegistry` registers instances under explicit, nonblank, case-sensitive names.
  Names are preserved exactly, matching `OperationRegistry`; duplicates are rejected.
  Lookup returns the registered instance; listing returns a sorted copy of names.
- `TaskManager` owns state and persistence. `TaskExecutor` owns claims, completion,
  failures, and conflict handling. Existing operations and HTTP APIs are unchanged.

An agent can use the existing executor without a new execution path:

```python
agent = agents.get("research")  # Resolve before claiming the task.
completed = executor.execute(task.id, lambda: agent.execute(manager.get_task(task.id)))
```

The snapshot is fetched inside the operation, after the task is claimed. Registry
membership is not authorization to spend money or perform external actions. Agents
must respect separately granted controls. This foundation adds no economic policy
engine, automatic discovery, parallel execution, or production business agents.
Explicit orchestration is available in Milestone 09.2 below; automatic routing remains future work.

## Checks (Windows, from backend)

```powershell
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m ruff format --check .
.venv\Scripts\python.exe -m pyright
.venv\Scripts\python.exe -m pytest
```

## Milestone 09.2: Agent Orchestration Engine

`AgentOrchestrator(manager, agents)` delegates to registered agents using the
existing TaskExecutor. `delegate(task.id, "research")` runs one agent;
`execute_workflow(task.id, ["research", "validation"])` runs a sequential plan.
All names are resolved before claiming the task. Empty plans are rejected.
Each agent receives a fresh RUNNING snapshot with the previous textual output in
`Task.result` (None for the first step); local snapshot mutations are isolated.

Both methods return a `WorkflowResult` containing the task ID, ordered
`AgentResult` steps (agent, output, error), and a success flag. The same report is
stored as JSON in the existing textual task result, requiring no schema or API
changes. On agent exception or non-string output, execution stops immediately;
the failed task stores the partial report including the failed step.
`TaskExecutionError` chains `AgentWorkflowError`, whose `result` exposes that
report and whose cause is the original agent exception. Existing claim and
finalization conflict behavior is preserved. Reports are persisted, but do not
provide resumable workflows or automatic retries.

This coordinator performs no paid AI calls and adds no spending authorization,
production agents, automatic routing, or HTTP execution endpoints. Register only
agents authorized for the intended work; registration is not a permission grant.

## Milestone 09.3 — Business Research Agent

`BusinessResearchAgent` implements the existing `Agent.execute(Task) -> str`
contract. The topic is `task.description` (trimmed); output is a JSON
`ResearchReport`. It never changes task state and does not consume preceding
workflow output as instructions. The existing orchestrator owns execution,
errors, sequential handoff and persistence. Existing HTTP APIs and the legacy
`market_research` operation are unchanged.

```python
from app.agents import AgentOrchestrator, AgentRegistry, BusinessResearchAgent
from app.tasks.manager import TaskManager

manager = TaskManager()
registry = AgentRegistry()
registry.register("business_research", BusinessResearchAgent())
task = manager.create_task("Business research", "JACK research demo")
workflow = AgentOrchestrator(manager, registry).delegate(task.id, "business_research")
# ResearchReport.model_validate_json(workflow.steps[0].output)
```

The default provider is deterministic and entirely offline, with no API keys,
paid services or additional dependencies. Only `JACK research demo` matches the
controlled corpus in `app/agents/research_corpus.py`. Its `fixture://` locator
identifies the local document and constant; it is explicitly synthetic, not a
market source. Other topics return an empty evidence set with limitations.
Absence of fixture evidence says nothing about a real market.

Reports separate quoted evidence from hypotheses, require explicit limitations,
reject duplicate evidence IDs and dangling hypothesis references, and preserve
source title, URI, excerpt and provenance. Evidence statements must appear in
the quoted excerpt. Hypotheses require a validation step. These checks enforce
structure and traceability, not source truth or current Internet verification.
No demand, competitor, price or market-size claims are generated.

Future retrieval adapters implement `ResearchProvider.research(topic)` and are
injected into `BusinessResearchAgent(provider)`. They must return a validated
report for that topic with external HTTPS sources and explicit limitations.
Adapters remain responsible for actual retrieval, source verification, freshness,
timeouts and authorization for any network usage or cost. Provider failures
propagate through the existing orchestrator to the Task Engine; they are never
silently replaced with invented findings. No Internet adapter is enabled here.

Validation: `.venv/Scripts/ruff check .`, `.venv/Scripts/ruff format --check .`,
`.venv/Scripts/pyright`, `.venv/Scripts/python -m pytest` from `backend`.

## Milestone 09.4 — opt-in Internet research

`BusinessResearchAgent(provider=...)`, `execute(Task) -> str`, registry,
orchestrator and HTTP/task lifecycle contracts are unchanged. Default operation
remains offline. Evidence has optional additive provenance fields; old evidence
remains valid and absent fields are omitted from agent output. No migration,
paid API, new dependency, secret or startup network request is introduced.

### Live configuration

Set environment variables (or use the existing `.env`):

```dotenv
RESEARCH_PROVIDER=crossref
RESEARCH_USER_AGENT=JACK/0.1 (https://github.com/mattiagiuliani/JACK)
RESEARCH_TIMEOUT=8
RESEARCH_INTERVAL=1
RESEARCH_RETRIES=1
RESEARCH_MAX_RESULTS=3
```

Use an accurate, contactable project URL or email for your deployment. The
example identifies this repository. Missing/invalid live configuration fails
validation instead of silently switching to fabricated/offline results. Restart
after changing settings because the existing loader caches them. Use
`RESEARCH_PROVIDER=controlled` to restore offline operation. No API key is needed.

From `backend`, explicitly run:

```powershell
.venv/Scripts/python.exe -c "from app.agents.research_web import configured_research_provider; print(configured_research_provider().research('market research').model_dump_json(indent=2))"
```

Two source adapters implement the existing `ResearchProvider` boundary:

- `crossref`: searches scholarly works, then fetches DOI records containing
  metadata and available abstracts. Publisher pages and paywalls are not fetched.
  Missing abstracts explicitly fall back to title-only evidence. Publication
  dates preserve supplied year/month/day precision; unknown dates stay absent.
- `wikipedia`: searches and retrieves introductory encyclopedia extracts;
  `RESEARCH_LANGUAGE=en` selects en/it/de/fr/es. **Currently blocked by observed
  robots policy**, as described below. Revision modification dates are distinct
  from original publication dates. Cached extracts may differ from the reported
  latest revision; the revision link is not an exact historical extract guarantee.

These are source-specific Internet search/retrieval adapters, **not a general web
search engine or sufficient market validation**. Coverage excludes much commercial
web content. They do not infer demand, competitors, pricing or market size.
Add further permitted adapters through the existing provider boundary; do not
silently replace failed real searches with fixtures.

### Provenance, safety and failure behavior

Quotes retain source URLs, retrieval API URLs, search URLs, UTC retrieval times,
and supplied publication/revision dates. They are untrusted source assertions,
not independently verified facts. Hypotheses remain empty. Missing evidence
never means missing demand. Retain attribution and inspect applicable reuse
terms: Wikipedia text is CC BY-SA; Crossref abstracts can have author/publisher
copyright even though most bibliographic metadata is unrestricted.

The injectable transport enables offline tests. Network access permits only
HTTPS and exact source origins/paths; userinfo, arbitrary ports, redirects and
foreign/private DNS addresses are rejected. The socket connects directly to a
validated public IP with hostname-verified TLS, preventing DNS rebinding.
Environment proxies, cookies and credentials are not used. DOI/source links are
reported, not followed. Response sizes are bounded. Timeout applies to socket
operations, not a hard total deadline; OS DNS timing is outside that limit.

Requests are serialized/rate limited per transport instance. Reuse one provider
per worker and coordinate quotas across workers. Bounded network retries (0–2)
use backoff; 429/503 and Wikipedia maxlag/ratelimited halt further retrieval
without shortening Retry-After. Results deduplicate by page ID/normalized DOI.
Search errors fail the task through the existing engine. Individual record
failures produce explicit partial-report limitations; systemic backpressure fails
rather than masquerading as a complete report.

robots.txt is retrieved each run and checked before search/content requests.
A 404 means unavailable robots and permits access (RFC 9309 §2.3.1.3); all other
HTTP failures, invalid encoding, denial or stricter crawl rates fail closed.
No denial bypass is implemented. Review source terms before deployment:

- [Crossref access](https://www.crossref.org/documentation/retrieve-metadata/rest-api/access-and-authentication/)
- [Crossref API and reuse](https://www.crossref.org/documentation/retrieve-metadata/rest-api/)
- [Wikimedia API etiquette](https://www.mediawiki.org/wiki/API:Etiquette)
- [Wikimedia usage policy](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_API_Usage_Guidelines)

No LLM, script, HTML rendering or tool invocation executes remote instructions.
Abstract markup is reduced to text. Downstream LLMs must independently isolate
all quoted text, including titles, as untrusted data. This adapter cannot ensure
prompt-injection safety for arbitrary later consumers of `task.result`.

### Actual live attempts — separate from mock tests

2026-11-11, Europe/Rome:

- 02:23:54: Wikipedia, `market research`, one result, zero retries, five-second
  timeout. HTTPS robots retrieval succeeded but `/w/api.php` was disallowed.
  Raised `RetrievalError` before search/content. No evidence was produced.
- 02:27:48–02:27:52: Crossref, `market research`, one result, zero retries,
  eight-second timeout. Robots returned 404; search and DOI retrieval succeeded.
  DOI `10.1177/1470785320941417`, publication date `2020-07-02`. No abstract was
  supplied, so the report explicitly contains title-only evidence. This verifies
  connectivity/retrieval, not the truth of any market claim. Full unmodified
  report: `research-live-crossref.json` (not a test fixture).

### Offline verification

From `backend`:

```powershell
.venv/Scripts/ruff.exe check app tests
.venv/Scripts/pyright.exe
.venv/Scripts/python.exe -m pytest -q
```

Mocks cover provenance, date precision, duplicate results, missing content,
robots denial/rate/404 rules, API errors, partial failure, private DNS, pinned TLS,
redirect rejection, bounded network retries, size limits and configuration.

## Milestone 09.5 — Commercial Market Intelligence

09.4 baseline: `c08b248` (`feat(research): add live research providers`).
Wikipedia remains encyclopedia context; Crossref remains scholarly metadata.
Neither is repurposed as commercial demand evidence. Existing agent, task APIs,
`ResearchProvider`, `Evidence` and `ResearchReport` contracts are unchanged.

The opt-in `commercial` provider composes `MarketSource` policy validation,
`PublicPageAdapter` retrieval/quote verification, and
`CommercialResearchProvider` aggregation. No generated data or LLM calls.
Source categories are reviewer-assigned and encoded in evidence IDs:
`customer_problem:…`, `competitor:…`, `public_price:…`, `demand_signal:…`.
Every observation retains the exact short quote, page URL, retrieval URL and UTC
retrieval time. Source title is supplied by the reviewer. Dates not supplied by
sources remain unknown. Hypotheses remain a separate existing report field and
are empty: quotes never prove demand, representative customer pain, market size
or willingness to pay. Missing categories are explicitly reported.

### Configuration

Default remains `RESEARCH_PROVIDER=controlled`. For public commercial collection:

- Set `RESEARCH_PROVIDER=commercial`.
- Set `RESEARCH_USER_AGENT` to an identifying agent with a real contact URL.
- Set `MARKET_SOURCES_JSON` to a JSON array of reviewed source objects.
- `RESEARCH_MAX_RESULTS` limits the configured source count (default 3, hard cap 5).
- `RESEARCH_INTERVAL` (default 1 second, minimum 1) and `RESEARCH_TIMEOUT`
  (default 8 seconds) retain their existing meanings.

Each object requires `topic` (exact task description match), `category`, `url`,
`title`, `quote` (1–160 characters, matching normalized static page text),
`terms_url`, `review_note`, `terms_reviewed: true`, `privacy_reviewed: true`.
Supply real reviewed values; there are intentionally no preapproved commercial
sites or example market assertions. An empty array performs no network calls
and returns explicit evidence gaps. Arrays beyond the result budget fail before
network access. Unrelated topics perform no network calls.

Before adding a source, review its current terms and reuse conditions at
`terms_url`, document the decision/context in `review_note`, and confirm public,
free automated access and a non-personal quotation. These flags are operator
attestations, not an automatic terms checker or legal permission. Do not configure
paid endpoints, login pages, personal profiles, private forums or sensitive data.
The report includes the terms review URL; retain the reviewed configuration as
an audit record. Email/phone-like quotes are rejected, but this heuristic cannot
detect all personal data. Only the selected quote is retained, not the page body.

### Retrieval and safety limits

At most two GETs per configured source (robots plus one page), no retries in the
configured commercial pipeline, at most ten GETs per research execution. Each
response is capped at 64,000 bytes; no paid API, key, LLM, browser execution,
link traversal, discovery search, cookies, credentials, environment proxy or
redirect following. Per-origin transports share a lock and minimum interval
within one provider instance. Multiple processes/instances are not globally rate
limited; operators must serialize scheduled runs. Limits apply per execution,
not as a persistent daily quota. Timeout is per socket operation, not an overall
wall-clock deadline; streaming peers can extend execution time.

HTTPS URLs must have no credentials, query, fragment or nonstandard port.
The exact configured page URLs and robots URLs form the allowlist. Existing
transport checks every DNS address is public, pins the validated destination,
verifies TLS and rejects redirects, including redirects to private networks.
Terms URLs are provenance only and are not automatically fetched.

Robots are checked before every page. Denial, unavailable network/server,
invalid UTF-8 or size overflow prevents collection. Existing transport treats a
robots 404 as unavailable/allow, following RFC 9309 section 2.3.1.3
(https://www.rfc-editor.org/rfc/rfc9309.html). Unsupported wildcard/end-anchor
rules conservatively block commercial collection; restrictive crawl-delay or
request-rate rules also block instead of increasing traffic. 429/503 stops the
remaining pipeline, with an explicit partial-report limitation.

Only normalized static UTF-8 HTML text is searched; script/style/template text
is excluded. This is not a browser visibility check or semantic verification.
JavaScript-only pages, other encodings, changed quotes, blocked sites or large
pages yield no observation. Prices are quoted as stated; taxes, currency,
region, billing period and promotional conditions require source review. No
sentiment scoring, competitor ranking, automatic price parsing or inferred
trends. Remote text is untrusted data, including any apparent instructions.

### Validation

`tests/test_research_market.py` uses synthetic pages and injected transports,
never live websites. It covers provenance/contract compatibility, deduplication,
category gaps, topic isolation, robots denial/rate/wildcard rules, changed or
script-only quotes, invalid encoding, byte limits, privacy review, unsafe URLs,
private DNS, allowlist enforcement, shared rate limiting and request budgets.
Run from `backend`:

```powershell
.venv/Scripts/ruff.exe check .
.venv/Scripts/ruff.exe format --check .
.venv/Scripts/pyright.exe
.venv/Scripts/python.exe -m pytest -q
```

No live commercial retrieval was performed for this milestone. Real sources
must be selected and reviewed before opting in; offline test assertions are
synthetic and are never presented as market findings.

## Milestone 09.6 — Business Validation Agent

`BusinessValidationAgent.execute(Task) -> str` consumes a `ResearchReport` JSON
from `Task.result` and returns a `ValidationReport` JSON. The topic must match
`Task.description`. Missing/malformed input fails through the existing task
engine. Existing research, orchestration and HTTP contracts are unchanged.

Explicit registration and workflow (with an existing manager and task):

```python
from app.agents import (
    AgentOrchestrator,
    AgentRegistry,
    BusinessResearchAgent,
    BusinessValidationAgent,
    ControlledResearchProvider,
)

registry = AgentRegistry()
registry.register("research", BusinessResearchAgent(ControlledResearchProvider()))
registry.register("validation", BusinessValidationAgent())
result = AgentOrchestrator(manager, registry).execute_workflow(
    task.id, ["research", "validation"]
)
```

The controlled provider makes this example deterministic and offline. Validation
itself never calls a provider or network service. An explicitly configured live
Research Agent keeps its existing retrieval policy; validation adds no paid API.

The frozen Pydantic report contains the original research, four assessments
(demand, willingness to pay, feasibility, competition), supporting/opposing
arguments with checked evidence IDs, contextual observations, missing data,
confidence with rationale, proposed tests and a reasoned recommendation.
Unknown references, incomplete dimensions and unsupported recommendation claims
are rejected. Source assertions and hypotheses remain untrusted data.

No numeric score or probability is calculated. `insufficient` means no direct
validation evidence; `limited` denotes provisional direct evidence;
`corroborated` denotes direct relevant results independently reviewed, not an
observation-count threshold. The current offline agent always reports
`insufficient`: it cannot semantically establish support or contradiction from
public-page text. Reviewer-assigned commercial categories route observations
only. Public prices do not prove willingness to pay, anecdotes do not establish
prevalence, and missing sources do not prove absent demand or competition.
Controlled fixtures never establish real business confidence.

Recommendation policy: no real observations -> `hold`; external observations ->
`experiment` (a proposal to design tests, not evidence of viability). Models also
represent `proceed` only with complete corroborated support in all dimensions,
and `reject` only with corroborated contrary evidence. This agent does not emit
these latter verdicts; interpretation of future direct experiment results needs
an explicitly reviewed assessment process. All recommendations require human
review and authorize no investment, purchase, price change or other economic
action. Test plans require approval and pre-agreed acceptance/stop rules; they
contain neither invented results nor arbitrary conversion thresholds.

Validation checks:

```powershell
.venv/Scripts/ruff.exe check app tests
.venv/Scripts/pyright.exe
.venv/Scripts/python.exe -m pytest -q
```

Unit tests cover deterministic fixtures, commercial observations, untrusted
text, missing data, invalid inputs/references, confidence/recommendation guards
and task immutability. Integration tests cover Research -> Validation with SQLite
persistence and failure handling through the existing orchestrator/task engine.

## Milestone 09.7 - Business Portfolio Foundation

Portafoglio multi-business persistente, separato da Task Engine e Agent
Orchestrator senza modificare i loro contratti. Ogni venture conserva identita,
descrizione/topic, valuta contabile fissa, stato, budget, capitale massimo,
speso registrato e versione. Nessuno scoring o investimento automatico.

### Persistenza e avvio

Da backend eseguire `.venv\Scripts\alembic.exe upgrade head` prima di usare le API.
La migrazione `097_portfolio` aggiunge `ventures` e `portfolio_events`; non viene
applicata automaticamente. I test usano solo database temporanei.
Snapshot ed eventi sono JSON validati Pydantic. Importi Decimal serializzati come
stringhe, massimo 24 cifre e 6 decimali: nessun arrotondamento binario o cambio
implicito. Valute nel formato a tre lettere maiuscole, senza catalogo ISO esterno.
Nessuna aggregazione automatica tra valute, periodi o KPI non comparabili.

### API e idempotenza

- `POST /ventures`: `{actor, reason, venture: {name, description, currency,
  capital_limit, budget}}`; crea in stato `idea`, versione 1.
- `GET /ventures` e `GET /ventures/{id}`: elenco e snapshot corrente.
- `POST /ventures/{id}/commands`: `{actor, reason, expected_version, change}`.
- `GET /ventures/{id}/history`: eventi ordinati con autore dichiarato, motivo,
  data UTC, richiesta completa e snapshot risultante. KPI e report sono negli eventi.

Ogni scrittura richiede `Idempotency-Key`: 1-200 caratteri ASCII tra lettere,
cifre, `_`, `.`, `:`, `-`. Chiavi globali persistenti. Stessa chiave e richiesta:
risposta originale anche dopo altri aggiornamenti. Riuso per altro corpo o venture:
409. Versione attesa, aggiornamento SQL condizionale e vincoli univoci prevengono
aggiornamenti persi e duplicati. Snapshot, audit e ricevuta sono atomici.
Per conflitto concorrente, riprovare la stessa richiesta con la stessa chiave per
recuperare un eventuale risultato gia registrato. Se occorre cambiare versione o
corpo, rileggere lo stato e usare una nuova chiave. 404: venture assente;
409: conflitto/transizione/limite; 422: dati non validi.

`change.kind` seleziona:

- `transition`: `status`. Percorso `idea -> researching -> validating ->
  experimenting -> operating`; `experimenting -> validating` consente nuovi test.
  Ogni stato attivo puo chiudersi; ogni stato salvo `idea` puo andare in `paused`.
  La ripresa torna solo allo stato precedente. `closed` e terminale.
  Nessuna raccomandazione causa transizioni automatiche.
- `limits`: `capital_limit`, `budget`, con speso <= budget <= capitale, non negativi.
- `expense`: `amount`, `currency`, `incurred_at` con fuso, `description`,
  `external_reference`. Registra spese gia sostenute senza effettuare transazioni.
  Valuta uguale alla venture e riferimento unico per venture anche con chiavi
  diverse. Registrazioni oltre budget/capitale rifiutate: aggiornare esplicitamente
  i limiti prima di registrarle. Rettifiche, rimborsi e riconciliazione sono futuri;
  questa fondazione non e un sistema contabile completo.
- `metric`: `name`, `value` anche negativo, `unit`, `basis` (`observed`/`estimated`),
  `period_start`, `period_end`, `source`, `methodology`. Periodi con fuso e ordinati.
  `unit=money` richiede `currency`, altre unita la omettono. Ogni rilevazione resta
  nell'audit; stime e KPI non incrementano lo speso. Nessun ROI automatico.
- `assessment`: `task_id`, `report` ValidationReport completo, `evidence_ids`.
  Richiede task completato con WorkflowResult riuscito, report identico a un output
  dello stesso workflow e topic uguale alla descrizione della venture. ID evidenza
  presenti nel ResearchReport incluso. Lo snapshot conserva assessment, evidenze
  e provenienza anche se cambia il task originale. Restano i vincoli della 09.6
  sui dati fixture e sulla revisione umana.

Autore e motivo sono dichiarazioni dell'operatore, non identita autenticate.
Come le API task, questa fondazione non introduce autenticazione/RBAC. L'audit e
append-only attraverso il servizio, non antimanomissione contro accesso SQL diretto.
Una sessione dedicata per richiesta. Grandi portafogli richiederanno paginazione e
proiezioni SQL dei dati economici oggi salvati negli eventi. Nessun pagamento,
chiamata di rete, approvazione o allocazione automatica di capitale.

Verifiche: `python -m pytest`, `ruff check .`, `ruff format --check .`, `pyright`.
16 nuovi test offline deterministici coprono multi-business, persistenza,
idempotenza, lifecycle, pausa/ripresa, versioni stale, CAS concorrente e rollback,
limiti/precisione monetaria, KPI osservati/stimati, workflow Research-Validation,
report alterati/riferimenti mancanti e upgrade/downgrade della migrazione.

## Milestone 09.8 - Portfolio Decision Engine

API aggiuntive, senza modificare i contratti task o venture della 09.7:

- `POST /portfolio-decisions` con `Idempotency-Key`: registra una comparazione
  consultiva tra 2-50 venture, non esegue operazioni economiche.
- `GET /portfolio-decisions/{id}`: restituisce report immutabile e revisione.
- `POST /portfolio-decisions/{id}/review`: registra una sola revisione umana
  con `actor`, `reason`, `outcome` (`acknowledged` o `rejected`). Ripetere la
  stessa revisione e idempotente; cambiarla restituisce 409. Una venture cambiata
  prima della verifica di revisione richiede un nuovo report (409).

Esempio del corpo di creazione (sostituire gli ID con venture esistenti):

```json
{
  "actor": "owner",
  "reason": "Confronto del prossimo esperimento",
  "candidates": [
    {"venture_id": "00000000-0000-0000-0000-000000000001",
     "expected_version": 7, "proposed_cost": "10"},
    {"venture_id": "00000000-0000-0000-0000-000000000002",
     "expected_version": 4, "proposed_cost": "20"}
  ],
  "criteria": [{
    "name": "profit", "unit": "money", "currency": "EUR",
    "period_start": "2026-10-01T00:00:00Z",
    "period_end": "2026-10-31T00:00:00Z",
    "minimum": "10",
    "rationale": "Minimo concordato dall'operatore per questo periodo"
  }],
  "available_capital": {"EUR": "100"}
}
```

I criteri sono minimi dichiarati dall'operatore, con motivazione obbligatoria:
nessun punteggio, peso, classifica o soglia economica inventata dal motore.
Ogni KPI e confrontabile solo per nome, unita, valuta e periodo identici.
Serve esattamente una misura osservata per criterio; duplicati ambigui,
periodi futuri o sole stime comportano astensione. Le stime rimangono separate
nei confronti e nel report. Non vengono calcolati ROI o conversioni valutarie.

Regole conservative, nell'ordine:

1. Venture paused/closed: `abstain`, senza riattivazione.
2. Costo proposto oltre budget/capitale residuo (sottratto lo speso), o somma
   dei costi proposti oltre il capitale dichiarato nella stessa valuta:
   `suspend`, proposta di sospendere il piano e richiedere priorita umane.
3. Ultima validazione esterna con rigetto corroborato: `suspend`.
4. Evidenze reali, KPI o capitale mancanti: `abstain`.
5. Supporto incompleto/provvisorio o KPI sotto il minimo: `investigate`.
6. Venture operating con tutti i minimi soddisfatti e validazione esterna
   completa, supportata e corroborata: `expand` se costo positivo, altrimenti
   `maintain`. Altri stati attivi: `investigate`.

Un vincolo economico noto puo quindi bloccare un piano anche con dati mancanti.
`suspend` ed `expand` sono raccomandazioni, mai transizioni o autorizzazioni.
La revisione `acknowledged` non approva spese, non prenota capitale e non cambia
venture. Il capitale disponibile e dichiarato dal chiamante, non un saldo
verificato o riservato. Nessuna chiamata di rete, pagamento o agente esecutivo.

Il report conserva richiesta, autore/motivo, versione motore, data UTC,
snapshot e storie complete (incluse fonti, metodi, evidenze e limitazioni della
validazione), motivazioni e confronti per valuta e KPI. L'ultima validazione
collegata sostituisce quelle precedenti ai fini della raccomandazione;
fixture e semplici osservazioni di pagine pubbliche non sostengono espansione.
Le versioni attese proteggono da richieste obsolete; chiavi riutilizzate con
corpi diversi danno 409, risorse mancanti 404, input non validi 422.

Come nella 09.7, autore e revisore sono dichiarati, senza autenticazione/RBAC;
l'audit e immutabile attraverso il servizio, non contro accesso SQL diretto.
La revisione attesta gli snapshot al controllo di versione, non blocca futuri
aggiornamenti concorrenti e non sostituisce una verifica prima di azioni reali.
Storie complete possono crescere: paginazione e limiti di dimensione sono
necessari prima di usare questa fondazione con grandi portafogli.

Migrazione `098_decisions` dopo `097_portfolio`: aggiunge solo
`portfolio_decisions`, con richiesta/report e revisione persistenti.
I test usano database temporanei: verificano l'intera catena Alembic, dati
09.7 preservati, scrittura/lettura del report, downgrade e nuovo upgrade.
Il database locale non viene migrato dalle verifiche.
