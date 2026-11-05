"""员工编制（`frago employee`）的读写接口。

一个员工就是 `~/.frago/employees/<编号>.json` 一个文件，领域层已经把读写、领地校验、
业务语境拼装全做完了（:mod:`frago.employee`）。这一层只做三件事：把请求体翻成领域层
的入参、把领域层的异常翻成状态码、把结果原样序列化出去。

**本机一台机器至少要有一个员工。** 清单为空时先落一个内置的 `stock` 岗位
（见 :func:`~frago.employee.ensure_builtin_stock_employee`）：员工页是点卡片起会话的
入口，一个都没有的话人打开页面看到的是一片空白，而不是一个能直接用的起点。

员工编号不存在一律回 404，不新造一个：人以为自己在改某个岗位的领地，实际改的是一个
刚被凭空建出来的同名岗位，两边的期望当场分岔。唯一自动建岗位的地方是清单那一条，
判据是「一个都没有」，不是「这个名字没有」。
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from frago.employee import (
    DEFAULT_STOCK_EMPLOYEE_SPEC,
    EmployeeOntologyService,
    EmployeePostRecord,
    ensure_builtin_stock_employee,
    get_post,
    ledger_summary,
    list_available_resources,
    list_posts,
    load_ledger,
    scan_data_slot_entries,
)
from frago.ontology import ContractViolationError

router = APIRouter()


def _ledger_payload(member_post_id: str) -> dict[str, Any] | None:
    """该员工账本的一页摘要；从未巡检过时为 None。

    给的是摘要而不是整本账：账本里的活跃事项会随工作推进长到几百条，页面需要的只是
    「有没有账本、同步到哪了、四栏各有几条」，条目正文由 ``frago employee ledger`` 看。
    """
    try:
        ledger = load_ledger(member_post_id)
    except ValueError:
        return None
    if ledger is None:
        return None
    return ledger_summary(ledger)


class EmployeeUpsertRequest(BaseModel):
    """建或改一个员工编制时交上来的那一份。

    字段与 `EmployeePostRecord` 对齐；``work_scope`` 与 ``cwd`` 给 ``None`` 表示「这一栏
    不动」，沿用磁盘上已有的值——改一条领地绑定不该顺手把岗位的工作范畴抹掉。

    ``member_post_id`` 只在新建那一条路上用得到（改的那条路编号在地址里），所以是可选的。
    """

    member_post_id: str = ""
    title: str
    agent_kernel: str = "claude"
    description: str = ""
    work_scope: str | None = None
    cwd: str | None = None
    knowledge_domains: list[str] = []
    recipes: list[str] = []
    data_slots: list[str] = []
    schedule_ids: list[str] = []
    allowed_commands: list[str] | None = None
    skills: list[str] | None = None
    color: str | None = None


class DataEntryRequest(BaseModel):
    """在某个员工领地里新建/登记一个归档目录。"""

    folder_name: str
    summary: str = ""
    slot_path: str | None = None


def _data_summary(data_slots: list[str]) -> dict[str, Any]:
    """员工领地的一行总览：几个槽位、每个槽位下有几项、合计几项。

    只数一层，不递归：槽位下那一层就是一件件工作，再往下是每件工作的内部结构，
    对「这个人手上有多厚」这个问题没有增量。
    """
    slots: list[dict[str, Any]] = []
    total = 0
    for slot in data_slots:
        scan = scan_data_slot_entries(slot, limit=0)
        slots.append(
            {
                "slot_path": slot,
                "exists": scan["exists"],
                "entry_count": scan["total_count"],
            }
        )
        total += scan["total_count"]
    return {"slot_count": len(data_slots), "entry_count": total, "slots": slots}


def _post_payload(record: EmployeePostRecord, *, with_data_summary: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = record.to_dict()
    if with_data_summary:
        payload["data_summary"] = _data_summary(list(record.data_slots))
    return payload


@router.get("/employees")
async def list_employees() -> dict[str, Any]:
    """所有员工，各带一份领地数据总览。

    一个都没有时先落一个内置的 `stock` 岗位再回。这一步写在读接口里是刻意的：员工页
    是这台机器上「点卡片就起会话」的入口，空清单等于页面没法用，而修它不需要问人
    ——内置岗位就是那个起点。
    """
    if not await run_in_threadpool(list_posts):
        await run_in_threadpool(ensure_builtin_stock_employee)
    records = await run_in_threadpool(list_posts)
    return {
        "employees": [_post_payload(r) for r in records],
        "total": len(records),
    }


@router.get("/employees/{member_post_id}")
async def get_employee(member_post_id: str) -> dict[str, Any]:
    """一个员工的详情：编制本身 + 领地数据索引 + 账本摘要 + 新对话会自动带入的那段语境。

    ``business_context_block`` 就是点卡片起会话时拼在第一句话最前面的原文，原样给出来，
    人可以在页面上一眼看清楚「这一场会带着什么起来」，而不用真的开一场去试。

    ``ledger`` 是该员工账本的摘要（同步到哪个时刻、四栏各有几条）。没有账本时为 null，
    这不是错误：岗位刚建好、巡检还没跑过的那个瞬间就是没有。

    ``available_resources`` 是本机此刻能绑给员工的全部资源，**不做职责词筛选**。巡检认领
    的那份给不出「还有哪些没绑上」，而详情弹窗要的正是「他认领到的」与「本机还有的」并排
    摆出来，人才能补绑、改判、撤销上次剔除。它跟着详情一次给完，页面不必再发一次请求。
    """
    service = EmployeeOntologyService()

    def _load() -> dict[str, Any]:
        record = next(
            (r for r in list_posts() if r.member_post_id == member_post_id.strip()),
            None,
        )
        if record is None:
            raise KeyError(f"Employee post '{member_post_id}' does not exist.")
        return {
            "employee": _post_payload(record),
            "managed_data": service.inspect_managed_data(member_post_id),
            "ledger": _ledger_payload(member_post_id),
            "available_resources": list_available_resources(),
            "business_context_block": service.build_business_context_block(member_post_id),
        }

    try:
        return await run_in_threadpool(_load)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


async def _upsert(member_post_id: str, request: EmployeeUpsertRequest) -> dict[str, Any]:
    service = EmployeeOntologyService()
    try:
        record, projection = await run_in_threadpool(
            service.hire,
            member_post_id,
            title=request.title,
            agent_kernel=request.agent_kernel,
            description=request.description,
            work_scope=request.work_scope,
            cwd=request.cwd,
            knowledge_domains=request.knowledge_domains,
            recipes=request.recipes,
            data_slots=request.data_slots,
            schedule_ids=request.schedule_ids,
            allowed_commands=request.allowed_commands,
            skills=request.skills,
            color=request.color,
        )
    except (ValueError, ContractViolationError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if not os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("FRAGO_EMPLOYEE_AUTO_SCHEDULE") == "1":
        def _auto_schedule() -> EmployeePostRecord:
            try:
                from frago.server.services.scheduler_service import SchedulerService

                scheduler = SchedulerService.get_instance()
                service.ensure_ledger_schedule(
                    member_post_id,
                    add_schedule=scheduler.add_schedule,
                    list_schedules=scheduler.list_schedules,
                )
            except Exception:  # noqa: BLE001 - 排程接不上不阻断岗位保存
                pass
            return get_post(member_post_id) or record

        record = await run_in_threadpool(_auto_schedule)

    payload = _post_payload(record)
    payload["post_ontological_id"] = projection.post.ontological_id()
    payload["role_ontological_id"] = projection.employee_role.ontological_id()
    return payload


@router.post("/employees", status_code=201)
async def create_employee(request: EmployeeUpsertRequest) -> dict[str, Any]:
    """新立一个员工编制。编号由调用方定，与 `frago employee hire` 同一条路。"""
    member_post_id = request.member_post_id.strip()
    if not member_post_id:
        raise HTTPException(
            status_code=400,
            detail="创建员工需要 member_post_id：这条路的地址里没有它，请在请求体里给出。",
        )
    return await _upsert(member_post_id, request)


@router.put("/employees/{member_post_id}")
async def update_employee(
    member_post_id: str,
    request: EmployeeUpsertRequest,
) -> dict[str, Any]:
    """改一个已有员工编制。编号不存在回 404，NEVER 顺手新建一个同名的。"""
    if not await run_in_threadpool(
        lambda: any(r.member_post_id == member_post_id.strip() for r in list_posts())
    ):
        raise HTTPException(
            status_code=404,
            detail=f"Employee post '{member_post_id}' does not exist.",
        )
    return await _upsert(member_post_id, request)


@router.post("/employees/{member_post_id}/data", status_code=201)
async def register_employee_data(
    member_post_id: str,
    request: DataEntryRequest,
) -> dict[str, Any]:
    """在员工领地里新建一个归档目录，并写一份 `notebook.md`。

    写入走领域层的领地校验（`data_slot` + `refresh_data` 契约），越界当场拒绝：
    员工只能写进自己纳管的槽位，这是契约管的事，不在这里另判一遍。
    """
    service = EmployeeOntologyService()
    try:
        return await run_in_threadpool(
            service.register_data_entry,
            member_post_id,
            request.folder_name,
            summary=request.summary,
            slot_path=request.slot_path,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ContractViolationError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e


@router.post("/employees/{member_post_id}/sync-ledger")
async def sync_employee_ledger_route(
    member_post_id: str,
    full: bool = False,
) -> dict[str, Any]:
    """手动触发一次该员工的增量巡检记账。

    ``full=true`` 丢掉游标重扫一遍，用于改过岗位职责、想重新认领的场合。默认走增量：
    指纹没变的资源直接跳过，所以第二次点通常是「新增 0」——这不是没干活，是没活可干。

    排程顺手注册（已存在则原样返回），巡检要每天自己跑一次才有意义。
    """
    service = EmployeeOntologyService()

    def _run() -> dict[str, Any]:
        result = service.sync_ledger(member_post_id, full_rescan=full)
        from frago.server.services.scheduler_service import SchedulerService

        scheduler = SchedulerService.get_instance()
        result["schedule"] = service.ensure_ledger_schedule(
            member_post_id,
            add_schedule=scheduler.add_schedule,
            list_schedules=scheduler.list_schedules,
        )
        return result

    try:
        return await run_in_threadpool(_run)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


__all__ = ["DEFAULT_STOCK_EMPLOYEE_SPEC", "router"]
