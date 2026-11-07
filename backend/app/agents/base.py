from abc import ABC, abstractmethod

from app.tasks.models import Task


class Agent(ABC):
    """Synchronous worker contract; JACK retains task lifecycle ownership.

    Implementations receive a task snapshot and return a textual result, or
    raise an exception on failure. They must not transition task state.
    Registration does not grant spending or external-action authorization.
    """

    @abstractmethod
    def execute(self, task: Task) -> str:
        """Perform specialized work without changing the stored task."""
