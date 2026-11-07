from collections.abc import Callable

Operation = Callable[[], str]


class OperationNotFoundError(LookupError):
    """Raised when an operation is not registered."""


class OperationAlreadyRegisteredError(ValueError):
    """Raised when an operation name is already registered."""


class OperationRegistry:
    def __init__(self) -> None:
        self._operations: dict[str, Operation] = {}

    def register(self, name: str, operation: Operation) -> None:
        if not name.strip():
            raise ValueError("Operation name cannot be empty")

        if name in self._operations:
            raise OperationAlreadyRegisteredError(
                f"Operation '{name}' is already registered"
            )

        self._operations[name] = operation

    def get(self, name: str) -> Operation:
        try:
            return self._operations[name]
        except KeyError as exc:
            raise OperationNotFoundError(
                f"Operation '{name}' is not registered"
            ) from exc

    def list_operations(self) -> list[str]:
        return sorted(self._operations)
