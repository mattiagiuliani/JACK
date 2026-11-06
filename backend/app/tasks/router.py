from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.tasks.manager import TaskManager, TaskNotFoundError
from app.tasks.models import Task, TaskPriority, TaskStatus
from app.tasks.state_machine import InvalidTaskTransitionError

router = APIRouter(prefix="/tasks", tags=["tasks"])
task_manager = TaskManager()


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1)
    priority: TaskPriority = TaskPriority.MEDIUM


class TaskStatusUpdate(BaseModel):
    status: TaskStatus


@router.post(
    "",
    response_model=Task,
    status_code=status.HTTP_201_CREATED,
)
def create_task(payload: TaskCreate) -> Task:
    return task_manager.create_task(
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
    )


@router.get("", response_model=list[Task])
def list_tasks() -> list[Task]:
    return task_manager.list_tasks()


@router.get("/{task_id}", response_model=Task)
def get_task(task_id: UUID) -> Task:
    try:
        return task_manager.get_task(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        ) from exc


@router.patch("/{task_id}/status", response_model=Task)
def update_task_status(
    task_id: UUID,
    payload: TaskStatusUpdate,
) -> Task:
    try:
        return task_manager.update_status(
            task_id,
            payload.status,
        )
    except TaskNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        ) from exc
    except InvalidTaskTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
