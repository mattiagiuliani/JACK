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

## Milestone 09.3 â€” Business Research Agent

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
