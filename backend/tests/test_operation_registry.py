import pytest

from app.tasks.registry import (
    OperationAlreadyRegisteredError,
    OperationNotFoundError,
    OperationRegistry,
)


@pytest.fixture
def registry() -> OperationRegistry:
    return OperationRegistry()


def test_register_and_get_operation(
    registry: OperationRegistry,
) -> None:
    def operation() -> str:
        return "Research completed"

    registry.register("market_research", operation)

    assert registry.get("market_research")() == "Research completed"


def test_unknown_operation(
    registry: OperationRegistry,
) -> None:
    with pytest.raises(OperationNotFoundError):
        registry.get("unknown")


def test_duplicate_operation(
    registry: OperationRegistry,
) -> None:
    registry.register("research", lambda: "First")

    with pytest.raises(OperationAlreadyRegisteredError):
        registry.register("research", lambda: "Second")


def test_empty_operation_name(
    registry: OperationRegistry,
) -> None:
    with pytest.raises(ValueError):
        registry.register("   ", lambda: "Result")


def test_list_operations(
    registry: OperationRegistry,
) -> None:
    registry.register("validation", lambda: "Validated")
    registry.register("research", lambda: "Researched")

    assert registry.list_operations() == [
        "research",
        "validation",
    ]
