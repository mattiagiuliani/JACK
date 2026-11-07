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
