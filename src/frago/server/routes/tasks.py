"""Task API endpoints.

Provides endpoints for listing and viewing tasks/sessions.
Uses StateManager for unified state access.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from frago.server.models import (
    TaskItemResponse,
    TaskDetailResponse,
    TaskListResponse,
    TaskStepsResponse,
    TaskStepResponse,
    TaskSummaryResponse,
    ToolUsageStatResponse,
)
from frago.server.state import StateManager
from frago.server.services.task_service import TaskService

router = APIRouter()


def _task_item_to_response(task) -> TaskItemResponse:
    """Convert TaskItem to TaskItemResponse."""
    return TaskItemResponse(
        id=task.id,
        title=task.title,
        status=task.status,
        project_path=task.project_path,
        agent_type=task.agent_type,
        started_at=task.started_at or datetime.now(timezone.utc),
        completed_at=task.completed_at,
        duration_ms=task.duration_ms,
        step_count=task.step_count,
        tool_call_count=task.tool_call_count,
        source=task.source,
    )


def _task_detail_to_response(detail) -> TaskDetailResponse:
    """Convert TaskDetail to TaskDetailResponse."""
    steps = [
        TaskStepResponse(
            timestamp=s.timestamp,
            type=s.type,
            content=s.content,
            tool_name=s.tool_name,
            tool_call_id=s.tool_call_id,
            tool_result=s.tool_result,
        )
        for s in detail.steps
    ]

    summary = None
    if detail.summary:
        summary = TaskSummaryResponse(
            total_duration_ms=detail.summary.total_duration_ms,
            user_message_count=detail.summary.user_message_count,
            assistant_message_count=detail.summary.assistant_message_count,
            tool_call_count=detail.summary.tool_call_count,
            tool_success_count=detail.summary.tool_success_count,
            tool_error_count=detail.summary.tool_error_count,
            most_used_tools=[
                ToolUsageStatResponse(name=t.name, count=t.count)
                for t in detail.summary.most_used_tools
            ],
        )

    return TaskDetailResponse(
        id=detail.id,
        title=detail.title,
        status=detail.status,
        project_path=detail.project_path,
        started_at=detail.started_at,
        completed_at=detail.completed_at,
        duration_ms=detail.duration_ms,
        step_count=detail.step_count,
        tool_call_count=detail.tool_call_count,
        steps=steps,
        steps_total=detail.steps_total,
        steps_offset=detail.steps_offset,
        has_more_steps=detail.has_more_steps,
        summary=summary,
    )


@router.get("/tasks", response_model=TaskListResponse)
async def list_tasks(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=100, description="Maximum tasks to return"),
    offset: int = Query(0, ge=0, description="Number of tasks to skip"),
) -> TaskListResponse:
    """List all tasks with optional filtering.

    Args:
        status: Filter by status (running, completed, error, cancelled)
        limit: Maximum number of tasks to return
        offset: Number of tasks to skip for pagination

    Returns:
        List of tasks with total count
    """
    state_manager = StateManager.get_instance()

    # Use StateManager for default queries (no filter)
    if status is None and state_manager.is_initialized():
        all_tasks = state_manager.get_tasks()
        total = state_manager.get_tasks_total()

        # Apply pagination
        paginated = all_tasks[offset : offset + limit]
        tasks = [_task_item_to_response(t) for t in paginated]

        return TaskListResponse(tasks=tasks, total=total)

    # Filtered requests: query storage directly and convert
    result = TaskService.get_tasks(status=status, limit=limit, offset=offset)

    tasks = []
    for t in result.get("tasks", []):
        started_at = t.get("started_at")
        if isinstance(started_at, str):
            started_at = datetime.fromisoformat(started_at)
        elif started_at is None:
            started_at = datetime.now(timezone.utc)

        completed_at = t.get("completed_at")
        if isinstance(completed_at, str):
            completed_at = datetime.fromisoformat(completed_at)

        tasks.append(
            TaskItemResponse(
                id=t.get("id", ""),
                title=t.get("title", ""),
                status=t.get("status", "running"),
                project_path=t.get("project_path"),
                agent_type=t.get("agent_type", "claude"),
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=t.get("duration_ms"),
                step_count=t.get("step_count", 0),
                tool_call_count=t.get("tool_call_count", 0),
                source=t.get("source", "unknown"),
            )
        )

    return TaskListResponse(
        tasks=tasks,
        total=result.get("total", len(tasks)),
    )


@router.get("/tasks/{task_id}", response_model=TaskDetailResponse)
async def get_task(task_id: str) -> TaskDetailResponse:
    """Get task details by ID.

    Uses StateManager for cached access with automatic loading.

    Args:
        task_id: Task identifier

    Returns:
        Task details including steps and summary

    Raises:
        HTTPException: 404 if task not found
    """
    state_manager = StateManager.get_instance()

    # Use StateManager (with caching)
    if state_manager.is_initialized():
        detail = state_manager.get_task_detail(task_id)
        if detail:
            return _task_detail_to_response(detail)

    # Fallback to direct TaskService call
    task = TaskService.get_task(task_id)

    if task is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

    # Convert steps
    steps = []
    for s in task.get("steps", []):
        timestamp = s.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        elif timestamp is None:
            timestamp = datetime.now(timezone.utc)

        steps.append(
            TaskStepResponse(
                timestamp=timestamp,
                type=s.get("type", "assistant"),
                content=s.get("content", ""),
                tool_name=s.get("tool_name"),
                tool_call_id=s.get("tool_call_id"),
                tool_result=s.get("tool_result"),
            )
        )

    # Convert summary if present
    summary = None
    if task.get("summary"):
        s = task["summary"]
        most_used_tools = []
        for t in s.get("most_used_tools", []):
            if hasattr(t, "tool_name"):
                most_used_tools.append(
                    ToolUsageStatResponse(name=t.tool_name, count=t.count)
                )
            else:
                most_used_tools.append(
                    ToolUsageStatResponse(name=t.get("name", ""), count=t.get("count", 0))
                )
        summary = TaskSummaryResponse(
            total_duration_ms=s.get("total_duration_ms", 0),
            user_message_count=s.get("user_message_count", 0),
            assistant_message_count=s.get("assistant_message_count", 0),
            tool_call_count=s.get("tool_call_count", 0),
            tool_success_count=s.get("tool_success_count", 0),
            tool_error_count=s.get("tool_error_count", 0),
            most_used_tools=most_used_tools,
        )

    # Parse started_at and completed_at
    started_at = task.get("started_at")
    if isinstance(started_at, str):
        started_at = datetime.fromisoformat(started_at)

    completed_at = task.get("completed_at")
    if isinstance(completed_at, str):
        completed_at = datetime.fromisoformat(completed_at)

    return TaskDetailResponse(
        id=task.get("id", task_id),
        title=task.get("title", ""),
        status=task.get("status", "running"),
        project_path=task.get("project_path"),
        started_at=started_at,
        completed_at=completed_at,
        duration_ms=task.get("duration_ms"),
        step_count=task.get("step_count", len(steps)),
        tool_call_count=task.get("tool_call_count", 0),
        steps=steps,
        steps_total=task.get("steps_total", len(steps)),
        steps_offset=task.get("steps_offset", 0),
        has_more_steps=task.get("has_more_steps", False),
        summary=summary,
    )


@router.post("/tasks/{task_id}/generate-title")
async def generate_task_title(task_id: str) -> dict:
    """Generate AI title for a single task.

    Uses haiku model via Claude Code CLI to generate a concise title
    based on the session content. Runs asynchronously to avoid blocking.

    Args:
        task_id: Task/session identifier.

    Returns:
        Dictionary with status and title on success, or error message.

    Raises:
        HTTPException: 404 if task not found.
    """
    # Verify task exists
    task = TaskService.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

    title, error = await TaskService.generate_title_for_task_async(task_id)
    if title:
        return {"status": "ok", "title": title}
    return {"status": "error", "error": error or "Failed to generate title"}


@router.get("/tasks/{task_id}/steps", response_model=TaskStepsResponse)
async def get_task_steps(
    task_id: str,
    limit: int = Query(100, ge=1, le=200, description="Maximum steps to return"),
    offset: int = Query(0, ge=0, description="Number of steps to skip"),
) -> TaskStepsResponse:
    """Get task steps with pagination.

    Args:
        task_id: Task identifier
        limit: Maximum number of steps to return
        offset: Number of steps to skip

    Returns:
        Paginated steps with total count

    Raises:
        HTTPException: 404 if task not found
    """
    # Verify task exists
    task = TaskService.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

    result = TaskService.get_task_steps(task_id, limit=limit, offset=offset)

    steps = []
    for s in result.get("steps", []):
        timestamp = s.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        elif timestamp is None:
            timestamp = datetime.now(timezone.utc)

        steps.append(
            TaskStepResponse(
                timestamp=timestamp,
                type=s.get("type", "assistant"),
                content=s.get("content", ""),
                tool_name=s.get("tool_name"),
                tool_call_id=s.get("tool_call_id"),
                tool_result=s.get("tool_result"),
            )
        )

    return TaskStepsResponse(
        steps=steps,
        total=result.get("total", len(steps)),
        has_more=result.get("has_more", False),
    )
