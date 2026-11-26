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
    """一条定时任务。字段取自 schedules.json，外加服务端现算状态与员工档案摘要。"""

    id: str
    name: str
    kind: str
    employee_id: str | None = None
    employee_title: str | None = None
    employee_kernel: str | None = None
    employee_cwd: str | None = None
    employee_missing: bool = False
    session_title_template: str | None = None
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
    last_session_id: str | None = None
    last_session_title: str | None = None
    last_run: dict[str, Any] | None = None
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


class ScheduleWriteRequest(BaseModel):
    """WebUI 结构化创建 / 编辑定时任务表单请求体。"""

    name: str
    kind: str = "employee"
    employee_id: str | None = None
    session_title_template: str | None = None
    prompt: str | None = None
    recipe: str | None = None
    command: str | None = None
    cwd: str | None = None
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
    notify: ScheduleNotify = ScheduleNotify()
    enabled: bool = True


class SchedulePreviewRequest(BaseModel):
    name: str = ""
    kind: str = "employee"
    employee_id: str | None = None
    session_title_template: str | None = None
    cron: str | None = None
    interval_seconds: int | None = None
    run_count: int = 0
    count: int = 3


class SchedulePreviewRun(BaseModel):
    seq: int
    triggered_at: str
    session_title: str


class SchedulePreviewResponse(BaseModel):
    runs: list[SchedulePreviewRun]


def _to_item(service: SchedulerService, raw: dict[str, Any]) -> ScheduleItem:
    enabled = raw.get("enabled", True)
    next_run = service._next_run_at(raw) if enabled else None
    history = raw.get("history") or []
    latest_history = history[-1] if history else None

    last_session_id = raw.get("last_session_id")
    if not last_session_id and latest_history:
        last_session_id = latest_history.get("session_id")

    last_session_title = raw.get("last_session_title")
    if not last_session_title and latest_history:
        last_session_title = latest_history.get("session_title")

    last_run = raw.get("last_run")
    if not last_run and latest_history:
        last_run = latest_history

    kind = raw.get("kind") or (
        "employee"
        if raw.get("employee_id")
        else ("recipe" if (raw.get("recipe") or raw.get("recipe_name")) else "prompt")
    )
    emp_id = str(raw.get("employee_id") or "").strip() or None
    emp_title: str | None = None
    emp_kernel: str | None = None
    emp_cwd: str | None = None
    emp_missing = False
    if emp_id:
        try:
            from frago.employee.store import get_post

            rec = get_post(emp_id)
            if rec is None:
                emp_missing = True
            else:
                emp_title = rec.title or None
                emp_kernel = rec.agent_kernel or None
                emp_cwd = rec.cwd or None
        except Exception:  # noqa: BLE001
            emp_missing = False

    fields = {k: v for k, v in raw.items() if k in ScheduleItem.model_fields}
    fields.update(
        kind=kind,
        employee_id=emp_id,
        employee_title=emp_title,
        employee_kernel=emp_kernel,
        employee_cwd=emp_cwd,
        employee_missing=emp_missing,
        recipe=raw.get("recipe") or raw.get("recipe_name"),
        next_run_at=next_run.isoformat() if next_run else None,
        running=raw["id"] in service._active_schedule_ids,
        last_session_id=last_session_id,
        last_session_title=last_session_title,
        last_run=last_run,
    )
    return ScheduleItem(**fields)


def _find(service: SchedulerService, schedule_id: str) -> dict[str, Any]:
    for s in service.list_schedules():
        if s["id"] == schedule_id:
            return s
    raise HTTPException(status_code=404, detail=f"schedule {schedule_id} not found")


def _validate_write_request(req: ScheduleWriteRequest) -> dict[str, Any]:
    kind = (req.kind or "").strip().lower()
    if kind not in ("employee", "recipe", "command", "prompt"):
        raise HTTPException(status_code=422, detail=f"不支持的执行形态：{req.kind}")

    name = (req.name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="任务名称不能为空")

    cron_expr = (req.cron or "").strip() or None
    interval = req.interval_seconds
    if cron_expr and interval:
        raise HTTPException(status_code=422, detail="cron 与 interval_seconds 只能二选一")
    if not cron_expr and (interval is None or int(interval) <= 0):
        raise HTTPException(status_code=422, detail="必须提供有效的 cron 表达式或大于 0 的 interval_seconds")
    if cron_expr:
        try:
            from croniter import croniter

            croniter(cron_expr)
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=422, detail=f"无效的 cron 表达式：{exc}") from exc

    if req.overlap not in ("skip", "queue"):
        raise HTTPException(status_code=422, detail="overlap 只能是 skip 或 queue")
    if req.timeout <= 0:
        raise HTTPException(status_code=422, detail="timeout 必须大于 0 秒")
    if req.notify.on not in ("change", "always", "failure", "never"):
        raise HTTPException(status_code=422, detail=f"无效的通知策略：{req.notify.on}")

    emp_id = (req.employee_id or "").strip().lstrip("@") or None
    recipe = (req.recipe or "").strip() or None
    command = (req.command or "").strip() or None
    prompt = (req.prompt or "").strip() or None

    if kind == "employee":
        if not emp_id:
            raise HTTPException(status_code=422, detail="employee 形态必须选择绑定的数字员工")
        from frago.employee.store import get_post

        if get_post(emp_id) is None:
            raise HTTPException(status_code=422, detail=f"数字员工 @{emp_id} 不存在或已被删除")
    elif kind == "recipe":
        if not recipe:
            raise HTTPException(status_code=422, detail="recipe 形态必须指定配方名")
    elif kind == "command":
        if not command:
            raise HTTPException(status_code=422, detail="command 形态必须填写 Shell 命令")
    elif kind == "prompt":
        if not prompt:
            raise HTTPException(status_code=422, detail="prompt 形态必须填写提示词任务")

    return {
        "name": name,
        "kind": kind,
        "employee_id": emp_id if kind == "employee" else None,
        "session_title_template": (req.session_title_template or "").strip() or None,
        "prompt": prompt or "",
        "recipe": recipe if kind == "recipe" else None,
        "command": command if kind == "command" else None,
        "cwd": (req.cwd or "").strip() or None,
        "instructions": (req.instructions or "").strip() or None,
        "allowed_tools": list(req.allowed_tools or []),
        "disallowed_tools": list(req.disallowed_tools or []),
        "params": dict(req.params or {}),
        "interval_seconds": int(interval) if interval else None,
        "cron": cron_expr,
        "overlap": req.overlap,
        "timeout": int(req.timeout),
        "start_at": req.start_at,
        "end_at": req.end_at,
        "notify": req.notify.model_dump(),
        "enabled": req.enabled,
    }


@router.get("/schedules", response_model=ScheduleListResponse)
async def api_list_schedules() -> ScheduleListResponse:
    """全部定时任务，顺序与 `frago schedule list` 一致（按创建先后）。"""
    service = SchedulerService.get_instance()
    return ScheduleListResponse(
        schedules=[_to_item(service, s) for s in service.list_schedules()],
        scheduler_running=service.is_running(),
    )


@router.post("/schedules/preview", response_model=SchedulePreviewResponse)
async def api_preview_schedule_runs(request: SchedulePreviewRequest) -> SchedulePreviewResponse:
    """实时预览动态会话标题模板在未来 N 次触发时的渲染结果。"""
    service = SchedulerService.get_instance()
    emp_id = (request.employee_id or "").strip().lstrip("@") or None
    emp_title: str | None = None
    if emp_id:
        try:
            from frago.employee.store import get_post

            rec = get_post(emp_id)
            if rec is not None and rec.title:
                emp_title = rec.title
        except Exception:  # noqa: BLE001
            pass

    runs = service.preview_next_runs(
        {
            "name": request.name,
            "kind": request.kind,
            "employee_id": emp_id,
            "session_title_template": request.session_title_template,
            "cron": request.cron,
            "interval_seconds": request.interval_seconds,
            "run_count": request.run_count,
        },
        count=request.count,
        employee_title=emp_title,
    )
    return SchedulePreviewResponse(runs=[SchedulePreviewRun(**r) for r in runs])


@router.post("/schedules/create", response_model=ScheduleItem)
async def api_create_schedule_structured(request: ScheduleWriteRequest) -> ScheduleItem:
    """结构化创建一条定时任务（支持原生绑定数字员工与动态会话标题模板）。"""
    clean = _validate_write_request(request)
    service = SchedulerService.get_instance()
    created = service.add_schedule(
        recipe_name=clean["recipe"],
        interval_seconds=clean["interval_seconds"],
        params=clean["params"],
        start_at=clean["start_at"],
        end_at=clean["end_at"],
        name=clean["name"],
        prompt=clean["prompt"],
        cron=clean["cron"],
        overlap=clean["overlap"],
        timeout=clean["timeout"],
        command=clean["command"],
        cwd=clean["cwd"],
        notify=clean["notify"],
        instructions=clean["instructions"],
        allowed_tools=clean["allowed_tools"],
        disallowed_tools=clean["disallowed_tools"],
        employee_id=clean["employee_id"],
        session_title_template=clean["session_title_template"],
    )
    if not clean["enabled"]:
        service.update_schedule(created["id"], enabled=False)
        created = _find(service, created["id"])
    return _to_item(service, created)


@router.get("/schedules/{schedule_id}", response_model=ScheduleItem)
async def api_get_schedule(schedule_id: str) -> ScheduleItem:
    """获取单条定时任务详情。"""
    service = SchedulerService.get_instance()
    return _to_item(service, _find(service, schedule_id))


@router.put("/schedules/{schedule_id}", response_model=ScheduleItem)
async def api_update_schedule(schedule_id: str, request: ScheduleWriteRequest) -> ScheduleItem:
    """结构化编辑一条定时任务（含执行形态切换、员工重绑、标题模板调整）。"""
    service = SchedulerService.get_instance()
    _find(service, schedule_id)
    clean = _validate_write_request(request)
    updated = service.update_schedule(schedule_id, **clean)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"schedule {schedule_id} not found")
    return _to_item(service, updated)


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

    接口不等它跑完就返回：四种形态最长都可以跑到超时上限（默认 2 小时），浏览器等不了
    那么久。结果照常写进执行记录，界面刷新就能看到。
    """
    service = SchedulerService.get_instance()
    target = _find(service, schedule_id)

    lock = service._get_schedule_lock(schedule_id)
    if schedule_id in service._active_schedule_ids or lock.locked():
        raise HTTPException(status_code=409, detail="上一次触发还没结束，等它跑完再点")

    kind = target.get("kind") or (
        "employee"
        if target.get("employee_id")
        else ("recipe" if target.get("recipe") else "prompt")
    )
    triggered_at = _now_utc().isoformat()
    service._active_schedule_ids.add(schedule_id)

    async def run() -> None:
        await service.run_manual(target, triggered_at=triggered_at)

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
