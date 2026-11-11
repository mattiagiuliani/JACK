# Milestone 10.1 — Business Execution Foundation

The Execution Planner is an offline, deterministic planning boundary. It produces
proposals and never creates runnable engine tasks, changes venture lifecycle,
allocates capital, records expenses, contacts anyone, generates code or deploys.
All money and hours are decimal estimates, with an explicit basis and assumptions.
No market facts, delivery estimates or product scope are inferred from a venture name.

## API

- `POST /execution-plans` requires `Idempotency-Key`, `venture_id`,
  `expected_version`, `actor`, `reason`, optional `decision_id`, and `scope`.
- `GET /execution-plans/{id}` returns the immutable planning audit and review.
- `POST /execution-plans/{id}/review` takes actor, reason and approved/rejected.
  Approval reviews the proposed plan only: `execution_authorized` remains false.

Scope contains objective, proposed requirements with acceptance criteria, tasks,
risks with mitigation and stop rules, exclusions, assumptions, cost limit,
contingency and cost basis. Each task includes requirement references, deliverable,
acceptance criteria, dependencies, priority and its rationale, estimated hours and
cost, estimate basis, assumptions, owner role and human checkpoint. All task costs
use the venture currency. The cost ceiling includes contingency; it must fit both
remaining budget and capital limit. It reserves no funds. Other operating costs
must be explicitly included by the proposer; omitted costs are not presumed zero.

The caller supplies a bounded MVP decomposition as a proposal. This first planner
checks and packages that scope against authoritative persisted evidence; it does
not invent requirements or numerical estimates. Unknown scope must be investigated
before submission. Unknown or duplicate task/requirement IDs, uncovered requirements,
cycles (including self cycles), nonfinite/negative estimates and excess costs are
rejected with 422. At most 100 tasks and requirements are accepted. The output
includes a stable topological task order, using declared priority then task ID
among ready tasks, and total estimated effort. Dependencies take precedence over
priority. Effort is not a calendar duration or a delivery promise.

## Gates and audit

A ready_for_review proposal requires an active validating/experimenting/operating
venture, a persisted linked external Validation report recommending proceed, and a
fresh acknowledged Portfolio Decision with no missing evidence or adverse advice
for this venture. The decision's proposed cost must cover the plan ceiling.
All portfolio snapshot versions must remain current. The existing
Validation model requires all dimensions to have complete corroborated support
before proceed. Its evidence assertions retain their original provenance; the
planner does not independently verify source truth.

Missing portfolio review, inactive lifecycle, rejected validation or exceeded venture
limits produces hold. Otherwise insufficient validation produces experiment. These
outcomes omit the executable scope and total estimate, retain reasons and available
evidence gaps/experiment proposals, and cannot be approved. The request and snapshots
remain available in the audit. Missing decision IDs return 404; stale versions or
key reuse with a different request return 409.

A plan is pending until explicitly reviewed. Review is immutable and compare-and-set;
identical retries return the same record, conflicting reviews return 409. Approval
rechecks all portfolio versions. Approved records are historical reviews, not evergreen
execution permits. A future executor must revalidate evidence, versions, budgets and
separate action-specific approval. This milestone provides no executor.

Audit includes original request, venture history, validation, decision and its review,
planner version, creation time, result and timestamped human review. A unique database
key handles concurrent creation; a loser receives 409 and retries the same key. Reads
and decisions use the existing append-only portfolio histories and SQLite transaction
behavior. No mutable plan update endpoint exists; revisions require a new key.

The API follows existing actor/reason audit conventions; actor names are declarations,
not authenticated identities. Deploy behind the same trusted access boundary as the
existing portfolio API. `ExecutionPlannerAgent` implements execute(Task) -> str for
explicit AgentRegistry/AgentOrchestrator composition. Its PlanningContext must be
resolved by trusted application code. The public API resolves context from persistence
and does not accept caller-supplied evidence-clear flags. There is no auto-registration,
network access, automatic delegation or generation.

## Migration and verification

`101_planning` adds only execution_plans after `098_decisions`; downgrade drops only
that table. Tests run upgrade/downgrade/re-upgrade on a temporary database, preserving
prior decision data. The local jack.db is never migrated during verification.

Run from backend using the project environment:

```
python -m ruff check app tests alembic
python -m ruff format --check app tests alembic
python -m pyright
python -m pytest -q
git diff --check
```

Offline tests cover the ready proposal, explicit review, stale state, hold/experiment,
idempotent retries and conflicts, DAG errors, invalid estimates, concurrent creation,
agent orchestration and migration roundtrip. The pre-existing Starlette/httpx
deprecation warning remains.
