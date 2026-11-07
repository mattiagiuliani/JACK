from app.agents.base import Agent


class AgentNotFoundError(LookupError):
    """Raised when an agent is not registered."""


class AgentAlreadyRegisteredError(ValueError):
    """Raised when an agent name is already registered."""


class AgentRegistry:
    """Explicit, in-memory registration; no discovery or agent execution."""

    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}

    def register(self, name: str, agent: Agent) -> None:
        if not name.strip():
            raise ValueError("Agent name cannot be empty")
        if name in self._agents:
            raise AgentAlreadyRegisteredError(f"Agent '{name}' is already registered")
        if not isinstance(agent, Agent):
            raise TypeError("Agent must implement the Agent contract")
        self._agents[name] = agent

    def get(self, name: str) -> Agent:
        try:
            return self._agents[name]
        except KeyError as exc:
            raise AgentNotFoundError(f"Agent '{name}' is not registered") from exc

    def list_agents(self) -> list[str]:
        return sorted(self._agents)
