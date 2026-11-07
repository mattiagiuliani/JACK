from app.tasks.registry import OperationRegistry


def market_research() -> str:
    return "Market research operation executed"


def build_registry() -> OperationRegistry:
    registry = OperationRegistry()
    registry.register("market_research", market_research)
    return registry
