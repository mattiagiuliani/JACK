from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.tasks.executor import TaskExecutor
from app.tasks.manager import TaskManager, TaskNotFoundError
from app.tasks.models import Task, TaskPriority, TaskStatus
from app.tasks.operations import build_registry
from app.tasks.registry import (
    OperationNotFoundError,
    OperationRegistry,
)
from app.tasks.repository import TaskRepository
from app.tasks.state_machine import InvalidTaskTransitionError

router = APIRouter(prefix="/tasks", tags=["tasks"])


def get_task_manager(
    session: Annotated[Session, Depends(get_db)],
) -> TaskManager:
    return TaskManager(TaskRepository(session))


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1)
    priority: TaskPriority = TaskPriority.MEDIUM


class TaskStatusUpdate(BaseModel):
    status: TaskStatus


class ExecuteTaskRequest(BaseModel):
    operation: str = Field(min_length=1)


@router.post(
    "",
    response_model=Task,
    status_code=status.HTTP_201_CREATED,
)
def create_task(
    payload: TaskCreate,
    manager: Annotated[TaskManager, Depends(get_task_manager)],
) -> Task:
    return manager.create_task(
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
    )


@router.get("", response_model=list[Task])
def list_tasks(
    manager: Annotated[TaskManager, Depends(get_task_manager)],
) -> list[Task]:
    return manager.list_tasks()


@router.get("/{task_id}", response_model=Task)
def get_task(
    task_id: UUID,
    manager: Annotated[TaskManager, Depends(get_task_manager)],
) -> Task:
    try:
        return manager.get_task(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        ) from exc


@router.patch("/{task_id}/status", response_model=Task)
def update_task_status(
    task_id: UUID,
    payload: TaskStatusUpdate,
    manager: Annotated[TaskManager, Depends(get_task_manager)],
) -> Task:
    try:
        return manager.update_status(task_id, payload.status)
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


operation_registry = build_registry()


def get_operation_registry() -> OperationRegistry:
    return operation_registry


@router.post("/{task_id}/execute", response_model=Task)
def execute_task(
    task_id: UUID,
    payload: ExecuteTaskRequest,
    manager: Annotated[TaskManager, Depends(get_task_manager)],
    registry: Annotated[OperationRegistry, Depends(get_operation_registry)],
) -> Task:
    executor = TaskExecutor(manager, registry)

    try:
        manager.get_task(task_id)
        return executor.execute_registered(task_id, payload.operation)

    except TaskNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        ) from exc

    except OperationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    except InvalidTaskTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
