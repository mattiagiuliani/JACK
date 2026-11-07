from app.tasks.manager import TaskManager
from app.tasks.models import TaskStatus


class TaskRecovery:
    def __init__(self, manager: TaskManager) -> None:
        self.manager = manager

    def recover_interrupted_tasks(self) -> list[str]:
        recovered_ids: list[str] = []

        for task in self.manager.list_tasks():
            if task.status != TaskStatus.RUNNING:
                continue

            self.manager.fail_task(
                task.id,
                "Task interrupted before completion",
            )

            recovered_ids.append(str(task.id))

        return recovered_ids
