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
A dedicated orchestrator and routing policy remain future work.

## Checks (Windows, from backend)

```powershell
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m ruff format --check .
.venv\Scripts\python.exe -m pyright
.venv\Scripts\python.exe -m pytest
```
