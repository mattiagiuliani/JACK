"""Specialized agents coordinated by JACK's task engine."""

from app.agents.base import Agent
from app.agents.orchestrator import (
    AgentOrchestrator,
    AgentResult,
    AgentWorkflowError,
    WorkflowResult,
)
from app.agents.registry import (
    AgentAlreadyRegisteredError,
    AgentNotFoundError,
    AgentRegistry,
)
from app.agents.validation import (
    Assessment,
    BusinessValidationAgent,
    EvidenceArgument,
    Recommendation,
    ValidationReport,
    ValidationTest,
)

__all__ = [
    "Agent",
    "AgentAlreadyRegisteredError",
    "AgentNotFoundError",
    "AgentRegistry",
    "AgentOrchestrator",
    "AgentResult",
    "AgentWorkflowError",
    "WorkflowResult",
]

from app.agents.research import (
    BusinessResearchAgent,
    ControlledResearchProvider,
    Evidence,
    Hypothesis,
    ResearchProvider,
    ResearchReport,
)

__all__ += [
    "BusinessResearchAgent",
    "ControlledResearchProvider",
    "Evidence",
    "Hypothesis",
    "ResearchProvider",
    "ResearchReport",
]


__all__ += [
    "Assessment",
    "BusinessValidationAgent",
    "EvidenceArgument",
    "Recommendation",
    "ValidationReport",
    "ValidationTest",
]
