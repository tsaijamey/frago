"""定时任务（`frago schedule`）的接口。

定时任务存在 ``~/.frago/schedules.json``，服务端进程里跑着的调度器每一轮都重读这份
文件。这里的每个接口都直接调调度器自己的方法——命令行 `frago schedule list / toggle /
remove` 调的也是这几个，所以界面上看到的字段、判定「下次什么时候跑」的算法，与命令行
和调度器实际触发时一模一样。

**接口必须留在事件循环线程上（``async def``，不进线程池）。** 调度器的「读文件→改→
写文件」中间不让出执行权，这里的启停和删除也一样；两边都在同一个线程上排队，就不会
出现一边读完、另一边写完、前一边再把旧内容写回去的覆盖。

**新建不在这里写文件。** 它把用户那句话交给 agent，由 agent 去敲 `frago schedule add`
——那条命令自带的校验（配方存在、cron 合法、通知落点已配置）只有走命令行才生效。
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from frago.server.services.scheduler_service import SchedulerService, _now_utc

router = APIRouter()

# 手动触发的执行挂在这里，别让事件循环把还没跑完的任务当垃圾回收掉。
_manual_runs: set[asyncio.Task] = set()


class ScheduleNotify(BaseModel):
    on: str = "never"
    to: str | None = None
    context: dict[str, Any] = {}


class ScheduleItem(BaseModel):
    """一条定时任务。字段取自 schedules.json，外加两项服务端现算的状态。"""

    id: str
    name: str
    kind: str
    prompt: str | None = None
    recipe: str | None = None
    command: str | None = None
    cwd: str | None = None
    # 自然语言任务交给 CoreAgent 时用的说明书，以及允许 / 禁止的工具调用（Claude Code 权限规则写法）。
    instructions: str | None = None
    allowed_tools: list[str] = []
    disallowed_tools: list[str] = []
    params: dict[str, Any] = {}
    interval_seconds: int | None = None
    cron: str | None = None
    overlap: str = "skip"
    timeout: int = 7200
    start_at: str | None = None
    end_at: str | None = None
    enabled: bool = True
    created_at: str | None = None
    last_run_at: str | None = None
    last_status: str | None = None
    last_success_at: str | None = None
    consecutive_failures: int = 0
    run_count: int = 0
    notify: ScheduleNotify = ScheduleNotify()
    # 最近 50 次执行，早的在前，原样照搬。
    history: list[dict[str, Any]] = []
    # 调度器下一次会在什么时候触发它。停用了就是 None——停用的任务没有「下次」。
    next_run_at: str | None = None
    # 上一次触发还没结束（重叠控制就是看这个跳过的）。
    running: bool = False


class ScheduleListResponse(BaseModel):
    schedules: list[ScheduleItem]
    # 调度器没在跑时，清单上每一条「下次运行」都不会兑现，界面得明说。
    scheduler_running: bool


def _to_item(service: SchedulerService, raw: dict[str, Any]) -> ScheduleItem:
    enabled = raw.get("enabled", True)
    next_run = service._next_run_at(raw) if enabled else None
    fields = {k: v for k, v in raw.items() if k in ScheduleItem.model_fields}
    fields.update(
        kind=raw.get("kind") or ("recipe" if raw.get("recipe") else "prompt"),
        recipe=raw.get("recipe") or raw.get("recipe_name"),
        next_run_at=next_run.isoformat() if next_run else None,
        running=raw["id"] in service._active_schedule_ids,
    )
    return ScheduleItem(**fields)


def _find(service: SchedulerService, schedule_id: str) -> dict[str, Any]:
    for s in service.list_schedules():
        if s["id"] == schedule_id:
            return s
    raise HTTPException(status_code=404, detail=f"schedule {schedule_id} not found")


@router.get("/schedules", response_model=ScheduleListResponse)
async def api_list_schedules() -> ScheduleListResponse:
    """全部定时任务，顺序与 `frago schedule list` 一致（按创建先后）。"""
    service = SchedulerService.get_instance()
    return ScheduleListResponse(
        schedules=[_to_item(service, s) for s in service.list_schedules()],
        scheduler_running=service.is_running(),
    )


@router.post("/schedules/{schedule_id}/toggle", response_model=ScheduleItem)
async def api_toggle_schedule(schedule_id: str) -> ScheduleItem:
    """启用 ↔ 停用，返回改完之后的样子。"""
    service = SchedulerService.get_instance()
    if service.toggle_schedule(schedule_id) is None:
        raise HTTPException(status_code=404, detail=f"schedule {schedule_id} not found")
    return _to_item(service, _find(service, schedule_id))


@router.delete("/schedules/{schedule_id}")
async def api_remove_schedule(schedule_id: str) -> dict[str, str]:
    service = SchedulerService.get_instance()
    if not service.remove_schedule(schedule_id):
        raise HTTPException(status_code=404, detail=f"schedule {schedule_id} not found")
    return {"status": "removed", "id": schedule_id}


@router.post("/schedules/{schedule_id}/run", status_code=202)
async def api_run_schedule(schedule_id: str) -> dict[str, str]:
    """立即跑一次，不改它的正常周期。

    接口不等它跑完就返回：三种形态最长都可以跑到超时上限（默认 2 小时），浏览器等不了
    那么久。结果照常写进执行记录，界面刷新就能看到。
    """
    service = SchedulerService.get_instance()
    target = _find(service, schedule_id)

    if schedule_id in service._active_schedule_ids:
        raise HTTPException(status_code=409, detail="上一次触发还没结束，等它跑完再点")

    kind = target.get("kind") or ("recipe" if target.get("recipe") else "prompt")
    triggered_at = _now_utc().isoformat()

    async def run() -> None:
        service._active_schedule_ids.add(schedule_id)
        try:
            await service._execute_native(target, triggered_at=triggered_at)
        finally:
            service._active_schedule_ids.discard(schedule_id)

    task = asyncio.create_task(run())
    _manual_runs.add(task)
    task.add_done_callback(_manual_runs.discard)
    return {"status": "started", "id": schedule_id, "kind": kind, "triggered_at": triggered_at}


class ScheduleComposeRequest(BaseModel):
    description: str


class ScheduleComposeResponse(BaseModel):
    # agent 跑完却没建出任何一条时为 None（比如同样的任务已经有了）。
    schedule_id: str | None = None
    message: str = ""
    # 它实际敲下去的那条 `frago schedule add`。
    command: list[str] | None = None


@router.post("/schedules", response_model=ScheduleComposeResponse)
async def api_compose_schedule(request: ScheduleComposeRequest) -> ScheduleComposeResponse:
    """把一句话交给 agent，让它建成一条定时任务。十几秒是常态，界面得有等待态。"""
    from frago.server.services.schedule_compose_service import ScheduleComposeService
    from frago.server.services.todo_compose_service import TodoComposeError

    try:
        result = await run_in_threadpool(ScheduleComposeService.compose, request.description)
    except TodoComposeError as exc:
        raise HTTPException(status_code=502, detail=exc.detail) from exc

    return ScheduleComposeResponse(**result)
