"""Frago 原生非阻塞派发与跨内核会话流回投引擎 (Async Dispatch & Session Callback)。

设计目标：
1. 调用方身份自识别：屏蔽 5 套 CLI Agent（claude / codex / opencode / agy / coreagent）环境变量差异，
   自动识别发起命令的父会话 ID（``caller_session_id``）。
2. 默认秒级非阻塞回执：``frago employee invoke/ask`` 与 Employee 会话发起的 ``frago agent`` / ``frago agent send``
   默认不阻塞当前 CLI 工具调用，秒级返回 ``[dispatched]`` 回执并立即退出 0。
3. 后台独立守护盯梢与多跳屏障：由脱离父进程会话组的后台 watcher 进程执行目标会话回合；
   若目标会话（如同侪员工 B）在回合内又异步派发了下属 Worker，则自动等待子派发收口后再提取最终结论。
4. 跨内核会话流回投：通过 ``workbench_queue`` + ``session_send`` 将结构化回传报文投递回发起方会话流，
   在发起方回合空闲时自动唤醒新回合。
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import os
import re
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from frago.employee.store import frago_home
from frago.ontology import (
    ActionContractError,
    build_finalize_dispatch_job_contract,
    build_record_callback_delivery_outcome_contract,
    ontological_action,
)
from frago.session.self_id import (
    SESSION_IDENTITY_ENV,
    _resolve_bound_session_id,
    resolve_self,
)

# 测试钩子：允许单测拦截后台进程拉起与回投动作
_async_spawner_override: Callable[[Path], None] | None = None
_callback_sender_override: Callable[[str, str, str | None], bool] | None = None


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def dispatch_store_dir() -> Path:
    """异步派发任务账本目录：``~/.frago/sessions/async_dispatches``。"""
    d = frago_home() / "sessions" / "async_dispatches"
    d.mkdir(parents=True, exist_ok=True)
    return d


def dispatch_logs_dir() -> Path:
    """异步派发 watcher 日志目录：``~/.frago/logs/async_dispatches``。"""
    d = frago_home() / "logs" / "async_dispatches"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclasses.dataclass
class AsyncDispatchJob:
    """单次异步派发任务记录。"""

    job_id: str
    kind: str  # "employee" | "worker" | "drive_send"
    mode: str  # "invoke" | "ask" | "new" | "resume" | "send"
    caller_session_id: str
    caller_employee_id: str | None
    caller_cwd: str | None
    target_session_id: str
    target_name: str | None
    employee_id: str | None
    agent: str
    cwd: str
    prompt: str
    task_summary: str
    resume: str | None = None
    model: str | None = None
    timeout: int | None = None
    env_list: list[str] = dataclasses.field(default_factory=list)
    status: str = "pending"  # "pending" | "running" | "delivering" | "completed" | "failed" | "superseded"
    superseded_by: str | None = None
    exit_code: int = 0
    output: str = ""
    error: str = ""
    delivery_state: str = "queued"  # "queued" | "delivering" | "delivered" | "failed"
    delivery_attempts: int = 0
    delivery_error: str | None = None
    delivered_at: str | None = None
    created_at: str = dataclasses.field(default_factory=_utc_now)
    updated_at: str = dataclasses.field(default_factory=_utc_now)
    completed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AsyncDispatchJob:
        fields = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in data.items() if k in fields}
        if "delivery_state" not in filtered and "status" in data:
            st = str(data.get("status") or "").strip().lower()
            if st == "completed":
                filtered["delivery_state"] = "delivered"
            elif st == "failed":
                filtered["delivery_state"] = "failed"
            elif st in {"pending", "running", "delivering"}:
                filtered["delivery_state"] = "queued"
        return cls(**filtered)


def save_dispatch_job(job: AsyncDispatchJob) -> Path:
    """持久化异步派发任务单。"""
    job.updated_at = _utc_now()
    path = dispatch_store_dir() / f"{job.job_id}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(job.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)
    return path


def load_dispatch_job(job_id_or_path: str | Path) -> AsyncDispatchJob | None:
    """读取异步派发任务单。"""
    path = (
        Path(job_id_or_path)
        if isinstance(job_id_or_path, Path) or str(job_id_or_path).endswith(".json")
        else dispatch_store_dir() / f"{job_id_or_path}.json"
    )
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return AsyncDispatchJob.from_dict(data)
    except Exception:
        return None
    return None


_RECORD_DELIVERY_OUTCOME_CONTRACT = build_record_callback_delivery_outcome_contract()
_FINALIZE_DISPATCH_JOB_CONTRACT = build_finalize_dispatch_job_contract()


@ontological_action(_RECORD_DELIVERY_OUTCOME_CONTRACT)
def record_callback_delivery_outcome(
    job_id: str,
    from_state: str,
    to_state: str,
    reason: str | None = None,
    *,
    # `prior_delivery_state` 只给契约谓词读（调用方注入的持久态）；函数体不读它——
    # 它管的是「这次跃迁准不准」，不是「这份任务单怎么写」。
    prior_delivery_state: str | None = None,  # noqa: ARG001
) -> str:
    """挂载 Ring 3 契约护栏的送达结果跃迁记录动作。

    ``prior_delivery_state`` 是**调用方从持久化派发单上读到的当前态**，必须由调用方注入：
    本体层不认业务落点，不自己去磁盘上找这份任务单（那是 ``load_dispatch_job`` 的事，
    落点也只此一处）。不注入或与 ``from_state`` 对不上，契约当场拒绝——这正是「谁都可以
    声称自己是从 queued 来的」这类伪造跃迁的拦截点。
    """
    job = load_dispatch_job(job_id)
    if job is None:
        # 「这份任务单得在」这条判据从前由本体层读盘时顺手兜住；本体层改成纯函数之后，
        # 它落到这里——有存储访问权的是本函数，不是契约谓词。少了它，对一份不存在的
        # 任务单调用本动作会静默返回，看起来像成功。
        raise ActionContractError(
            f"Dispatch job '{job_id}' does not exist; cannot record a delivery outcome for it."
        )
    job.delivery_state = to_state
    if from_state == "delivering":
        job.delivery_attempts = getattr(job, "delivery_attempts", 0) + 1
    if reason:
        job.delivery_error = reason
    if to_state == "delivered":
        job.delivered_at = _utc_now()
    save_dispatch_job(job)
    return to_state


@ontological_action(_FINALIZE_DISPATCH_JOB_CONTRACT)
def finalize_dispatch_job(
    job_id: str,
    exit_code: int | None,
    delivery_state: str,
    job_status: str,
    *,
    prior_delivery_state: str | None = None,  # noqa: ARG001 — 同上：只给契约谓词读
) -> str:
    """挂载 Ring 3 契约护栏的派发单终态收口动作。

    ``prior_delivery_state`` 同 :func:`record_callback_delivery_outcome`：由调用方从
    ``load_dispatch_job`` 读到的持久态注入，本体层不读盘。
    """
    job = load_dispatch_job(job_id)
    if job is None:
        # 同 record_callback_delivery_outcome：任务单必须在，这条判据随本体层去读盘
        # 一起移到了这里（有存储访问权的地方）。
        raise ActionContractError(
            f"Dispatch job '{job_id}' does not exist; cannot finalize it."
        )
    job.exit_code = int(exit_code or 0)
    job.delivery_state = delivery_state
    job.status = job_status
    job.completed_at = _utc_now()
    save_dispatch_job(job)
    return job_status


def list_dispatch_jobs(
    *,
    caller_session_id: str | None = None,
    target_session_id: str | None = None,
    active_only: bool = False,
) -> list[AsyncDispatchJob]:
    """按条件检索异步派发任务单。"""
    root = dispatch_store_dir()
    jobs: list[AsyncDispatchJob] = []
    for p in sorted(root.glob("*.json")):
        job = load_dispatch_job(p)
        if job is None:
            continue
        if caller_session_id and job.caller_session_id != caller_session_id:
            continue
        if target_session_id and job.target_session_id != target_session_id:
            continue
        if active_only and job.status not in ("pending", "running", "delivering"):
            continue
        jobs.append(job)
    return jobs


def has_pending_async_work(session_id: str) -> bool:
    """判断指定会话是否仍有尚未收口的子异步派发任务。"""
    if not session_id:
        return False
    active = list_dispatch_jobs(caller_session_id=session_id, active_only=True)
    return len(active) > 0


def sync_claimed_target_session_id(
    handle_or_old_sid: str,
    claimed_session_id: str,
    *,
    agent_type: str | None = None,
    cwd: str | None = None,
) -> list[str]:
    """当认领型内核（agy / codex / opencode）将预分配把手绑定到真实原生会话 ID 时，
    立即同步更新对应 AsyncDispatchJob 的 target_session_id 并落盘。
    """
    old_sid = (handle_or_old_sid or "").strip()
    new_sid = (claimed_session_id or "").strip()
    if not old_sid or not new_sid or old_sid == new_sid:
        return []
    updated_job_ids: list[str] = []
    root = dispatch_store_dir()
    for p in sorted(root.glob("*.json")):
        job = load_dispatch_job(p)
        if job is None or job.target_session_id != old_sid:
            continue
        job.target_session_id = new_sid
        if job.target_name == old_sid:
            job.target_name = new_sid
        save_dispatch_job(job)
        updated_job_ids.append(job.job_id)
        with contextlib.suppress(Exception):
            from frago.session.session_origin import record_relation

            record_relation(
                kind="dispatch",
                child_session_id=new_sid,
                parent_session_id=job.caller_session_id,
                agent_type=agent_type or job.agent,
                cwd=cwd or job.cwd,
                prompt_head=job.task_summary,
            )
        if job.employee_id:
            with contextlib.suppress(Exception):
                from frago.employee import get_post, save_post

                rec = get_post(job.employee_id)
                if rec is not None:
                    cleaned = [s for s in rec.active_session_ids if s and s != old_sid]
                    if new_sid not in cleaned:
                        cleaned.append(new_sid)
                    if cleaned != rec.active_session_ids:
                        rec.active_session_ids = cleaned
                        save_post(rec)
    return updated_job_ids


def supersede_active_jobs_for_target(
    target_session_id: str,
    *,
    new_job_id: str,
    caller_session_id: str | None = None,
) -> list[str]:
    """当对同一 target_session_id 发起新的异步派发（如追派续跑）时，将尚未收口的旧派发单标记为 superseded。"""
    if not target_session_id:
        return []
    superseded_ids: list[str] = []
    for old_job in list_dispatch_jobs(
        caller_session_id=caller_session_id,
        target_session_id=target_session_id,
        active_only=True,
    ):
        if old_job.job_id == new_job_id:
            continue
        old_job.status = "superseded"
        old_job.superseded_by = new_job_id
        old_job.completed_at = _utc_now()
        old_job.error = f"Superseded by {new_job_id}"
        save_dispatch_job(old_job)
        superseded_ids.append(old_job.job_id)
    return superseded_ids


def is_job_superseded(job: AsyncDispatchJob) -> tuple[bool, str | None]:
    """检查当前派发单是否已被同一目标会话的后续派发单抢占取代。"""
    on_disk = load_dispatch_job(job.job_id)
    if on_disk is not None and (on_disk.status == "superseded" or on_disk.superseded_by):
        return True, on_disk.superseded_by
    if not job.target_session_id:
        return False, None
    for other in list_dispatch_jobs(
        caller_session_id=job.caller_session_id,
        target_session_id=job.target_session_id,
        active_only=True,
    ):
        if other.job_id == job.job_id:
            continue
        if other.created_at >= job.created_at:
            return True, other.job_id
    return False, None


def resolve_caller_session_id(explicit_caller_sid: str | None = None) -> str | None:
    """解析当前 CLI 命令发起方的会话 ID（跨 5 套 CLI Agent 统一识别）。

    优先级：
    1. 显式传入的 ``--callback-session <sid>``
    2. 环境变量 ``FRAGO_CALLBACK_SESSION_ID``
    3. ``resolve_self()``（覆盖 CLAUDE_CODE_SESSION_ID / ANTIGRAVITY_CONVERSATION_ID /
       CODEX_THREAD_ID / OPENCODE_SESSION_ID / FRAGO_SESSION_ID / FRAGO_LAUNCH_HANDLE）

    注：在 pytest 运行期间，为防止外层宿主会话环境变量污染无关单测，除非显式传入
    ``explicit_caller_sid``、设置了 ``FRAGO_CALLBACK_SESSION_ID`` 或
    ``FRAGO_TEST_ALLOW_ASYNC_DISPATCH=1``，否则默认不读取外层环境身份。
    """
    if explicit_caller_sid and explicit_caller_sid.strip():
        resolved, _ = _resolve_bound_session_id(explicit_caller_sid.strip())
        return resolved or explicit_caller_sid.strip()

    env_cb = os.environ.get("FRAGO_CALLBACK_SESSION_ID", "").strip()
    if env_cb:
        resolved, _ = _resolve_bound_session_id(env_cb)
        return resolved or env_cb

    if os.environ.get("PYTEST_CURRENT_TEST") and os.environ.get("FRAGO_TEST_ALLOW_ASYNC_DISPATCH") != "1":
        return None

    found = resolve_self()
    return found.session_id if found is not None else None


def is_employee_caller_session(caller_session_id: str | None) -> tuple[bool, str | None]:
    """判断发起方会话是否绑定了数字员工（Employee），返回 ``(is_employee, employee_id)``。"""
    env_emp = os.environ.get("FRAGO_EMPLOYEE_ID", "").strip()
    if env_emp:
        return True, env_emp
    if not caller_session_id:
        return False, None
    with contextlib.suppress(Exception):
        from frago.employee import resolve_session_employee_id

        emp_id = resolve_session_employee_id(caller_session_id)
        if emp_id:
            return True, emp_id
    return False, None


def _in_synchronous_recipe_context() -> bool:
    """判断当前是否处于 ``frago recipe run`` 或配方沙箱的同步脚本上下文中。"""
    return bool(
        os.environ.get("FRAGO_CURRENT_RUN", "").strip()
        or os.environ.get("FRAGO_EXECUTION_ID", "").strip()
        or os.environ.get("FRAGO_RECIPE_DATA_DIR", "").strip()
    )


def should_dispatch_employee_async(
    caller_session_id: str | None,
    *,
    wait_for_answer: bool = False,
    force_async: bool = False,
    dry_run: bool = False,
    force_spawn: bool = False,
    explicit_caller_sid: str | None = None,
) -> bool:
    """判定 ``frago employee invoke/ask`` 是否走非阻塞异步派发 + 会话流回投。"""
    if dry_run or force_spawn or wait_for_answer:
        return False
    if not caller_session_id:
        return False
    return not (_in_synchronous_recipe_context() and not (force_async or explicit_caller_sid))


def should_dispatch_worker_async(
    caller_session_id: str | None,
    *,
    wait_for_answer: bool = False,
    force_async: bool = False,
    dry_run: bool = False,
    explicit_caller_sid: str | None = None,
    target_session_id: str | None = None,
) -> bool:
    """判定 ``frago agent`` / ``frago agent send`` 是否走非阻塞异步派发 + 会话流回投。

    触发条件：
    - 未指定 ``--wait`` 且非 ``--dry-run``；
    - 存在有效的 ``caller_session_id``（且不等于目标会话自身）；
    - 调用方是数字员工会话（Employee），或显式指定了 ``--async`` / ``--callback-session``。
    """
    if dry_run or wait_for_answer:
        return False
    if not caller_session_id:
        return False
    if target_session_id and caller_session_id == target_session_id:
        return False
    if _in_synchronous_recipe_context() and not (force_async or explicit_caller_sid):
        return False
    if force_async or explicit_caller_sid:
        return True
    is_emp, _ = is_employee_caller_session(caller_session_id)
    return is_emp


def sanitize_child_env(
    base_env: dict[str, str] | None = None,
    *,
    target_session_id: str | None = None,
    target_employee_id: str | None = None,
) -> dict[str, str]:
    """清洗子进程环境，剥离父会话的身份变量，注入子会话自身身份。"""
    env = dict(base_env if base_env is not None else os.environ)
    for k in SESSION_IDENTITY_ENV:
        env.pop(k, None)
    for extra_k in (
        "FRAGO_CALLBACK_SESSION_ID",
        "FRAGO_EMPLOYEE_ID",
        "FRAGO_LAUNCH_HANDLE",
    ):
        env.pop(extra_k, None)
    if target_session_id:
        env["FRAGO_SESSION_ID"] = target_session_id
    if target_employee_id:
        env["FRAGO_EMPLOYEE_ID"] = target_employee_id
        env["FRAGO_AGENT_ROLE"] = "employee"
    elif env.get("FRAGO_AGENT_ROLE") == "employee":
        env.pop("FRAGO_AGENT_ROLE", None)
    env["FRAGO_ASYNC_DISPATCH_CHILD"] = "1"
    return env


def format_dispatched_receipt(job: AsyncDispatchJob, *, output_format: str = "text") -> str:
    """生成秒级返回的 ``[dispatched]`` 派发回执文本或 JSON。"""
    if output_format == "json":
        payload = {
            "status": "dispatched",
            "job_id": job.job_id,
            "kind": job.kind,
            "mode": job.mode,
            "session_id": job.target_session_id,
            "target_session_id": job.target_session_id,
            "caller_session_id": job.caller_session_id,
            "employee_id": job.employee_id,
            "agent": job.agent,
            "cwd": job.cwd,
            "message": (
                f"Task dispatched in background (job_id={job.job_id}, "
                f"target_session_id={job.target_session_id}). "
                f"Final output will be automatically injected into caller session "
                f"{job.caller_session_id} when completed."
            ),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    if job.kind == "employee":
        return (
            f"[dispatched] job_id={job.job_id} mode=employee_{job.mode} "
            f"employee_id={job.employee_id} target_session_id={job.target_session_id} "
            f"caller_session_id={job.caller_session_id}\n"
            f"status: running_in_background\n"
            f"callback: 同侪员工 {job.employee_id}（会话 {job.target_session_id}）已在后台处理，"
            f"最终结论将在完成后自动投递回当前会话（{job.caller_session_id}）的消息流。"
            f"请先向人类简要同步派发状态并结束当前回合，等待回传报文唤醒。"
        )
    return (
        f"[dispatched] job_id={job.job_id} mode=worker_{job.mode} "
        f"worker_session_id={job.target_session_id} caller_session_id={job.caller_session_id}\n"
        f"status: running_in_background\n"
        f"callback: 下属 Worker 会话（{job.target_session_id}）已在后台执行任务书，"
        f"执行结果将在完成后自动投递回当前会话（{job.caller_session_id}）的消息流。"
        f"请先向人类简要同步派发状态并结束当前回合，等待回传报文唤醒。"
    )


#: 回传正文超过此长度即改为「摘要 + 查全指引」，避免把整篇长报告灌进父会话上下文。
_CALLBACK_BODY_MAX_CHARS = 600
#: 截断时保留的前段字数（核心结论通常开篇即出，尾部多为铺陈与附录）。
_CALLBACK_BODY_HEAD_CHARS = 420


def summarize_callback_body(body: str, target_session_id: str) -> str:
    """把回传正文压成「前段核心内容 + 省略字数提示 + 查全指引」。

    短正文（不超过 ``_CALLBACK_BODY_MAX_CHARS``）原样返回，不丢任何信息；超长正文保留前段
    ``_CALLBACK_BODY_HEAD_CHARS`` 字，并明确告知省略了多少字、到哪里取全文。截断只作用于正文，
    不影响 ``<frago-async-callback>`` 的属性行与小节标题，因此前端解析器不受影响。
    """
    if len(body) <= _CALLBACK_BODY_MAX_CHARS:
        return body
    head = body[:_CALLBACK_BODY_HEAD_CHARS].rstrip()
    omitted = len(body) - len(head)
    # 前段若正好切在 ``` 代码围栏中间，补一个闭合围栏：否则 Markdown 会把省略提示与查全指引
    # 一并当成代码块内容吞掉，父会话反而看不到「去哪里取全文」。
    if head.count("```") % 2 == 1:
        head = f"{head}\n```"
    return (
        f"{head}\n\n"
        f"……（正文过长，此处省略 {omitted} 字。完整内容请用 "
        f"`frago session ask {target_session_id} 「要提取的问题」` 读取目标会话，"
        f"或直接查阅该会话落盘的交付报告。）"
    )


def format_callback_prompt(job: AsyncDispatchJob) -> str:
    """将子任务（同侪员工或下属 Worker）的最终产出封装为回投给父会话的结构化报文。"""
    status_label = "completed" if job.exit_code == 0 and job.status != "failed" else "failed"
    body = (job.output or "").strip()
    if not body and job.error:
        body = f"[执行异常] {job.error.strip()}"
    if not body:
        body = "（目标会话已完成回合，未捕获到额外文本输出，请按需核查目标会话记录。）"
    body = summarize_callback_body(body, job.target_session_id)

    if job.kind == "employee":
        mode_zh = "任务移交 (invoke)" if job.mode == "invoke" else "协查提问 (ask)"
        return (
            f"<frago-async-callback kind=\"employee\" mode=\"{job.mode}\" "
            f"job_id=\"{job.job_id}\" employee_id=\"{job.employee_id or ''}\" "
            f"session_id=\"{job.target_session_id}\" status=\"{status_label}\">\n"
            f"【同侪员工异步回传】来自 `{job.employee_id}`（会话 `{job.target_session_id}`，模式：{mode_zh}）\n"
            f"- 派发单号：`{job.job_id}`\n"
            f"- 原始诉求：{job.task_summary}\n"
            f"- 执行状态：`{status_label}` (exit_code={job.exit_code})\n\n"
            f"### 同侪员工返回结论\n"
            f"{body}\n\n"
            f"---\n"
            f"请基于上述同侪员工回传结论，结合你掌握的领域背景与事务围栏进行复核：\n"
            f"若结论已向人类汇报且内容一致，仅需一句话确认收口，严禁全文复述；"
            f"否则请精炼提炼要点并向人类给出最终结果与决策建议。\n"
            f"</frago-async-callback>"
        )

    mode_zh = {
        "new": "新建 Worker 执行",
        "resume": "复用已有 Worker 续跑",
        "send": "驱动已有 Worker 会话",
    }.get(job.mode, job.mode)
    return (
        f"<frago-async-callback kind=\"worker\" mode=\"{job.mode}\" "
        f"job_id=\"{job.job_id}\" worker_session_id=\"{job.target_session_id}\" "
        f"status=\"{status_label}\">\n"
        f"【下属 Worker 异步回传】来自 Worker 会话 `{job.target_session_id}`（模式：{mode_zh}，内核：`{job.agent}`）\n"
        f"- 派发单号：`{job.job_id}`\n"
        f"- 任务摘要：{job.task_summary}\n"
        f"- 执行状态：`{status_label}` (exit_code={job.exit_code})\n\n"
        f"### Worker 交付结果\n"
        f"{body}\n\n"
        f"---\n"
        f"请作为管理者（Employee）结合领域知识与执行准则审核上述 Worker 产出：\n"
        f"1. 若结论已向人类汇报且内容一致，仅需一句话确认收口，严禁全文复述；"
        f"否则请精炼提炼要点并向人类给出最终结果与决策建议；\n"
        f"2. 若发现遗漏或需补充验证，可继续向该 Worker（`frago agent --resume {job.target_session_id} ...`）追派任务书。\n"
        f"</frago-async-callback>"
    )


def _extract_latest_assistant_output(session_id: str) -> str | None:
    """从目标会话的记录中提取最新一条实质性 assistant 文本（排除纯 [dispatched] 过渡回执）。"""
    with contextlib.suppress(Exception):
        from frago.session.browse import read_session_detail

        detail = read_session_detail(session_id)
        if detail and isinstance(detail.get("messages"), list):
            for msg in reversed(detail["messages"]):
                if not isinstance(msg, dict):
                    continue
                if msg.get("role") != "assistant":
                    continue
                content = str(msg.get("content") or msg.get("text") or "").strip()
                if content and not content.startswith("[dispatched]"):
                    return content
    return None


def wait_for_pending_child_dispatches(
    target_session_id: str,
    *,
    timeout_s: float = 1800.0,
    poll_interval_s: float = 0.5,
) -> str | None:
    """若目标会话在执行过程中又发起了子异步派发（如 Employee B -> Worker W），
    等待所有子派发完成回投且目标会话自身回合再次收口后，返回其最新结论。
    """
    bound_sid = _resolve_bound_session_id(target_session_id)[0]
    if bound_sid:
        target_session_id = bound_sid
    if not has_pending_async_work(target_session_id) and not list_dispatch_jobs(
        caller_session_id=target_session_id, active_only=False
    ):
        return None

    from frago.server.services import workbench_queue

    deadline = time.monotonic() + max(timeout_s, 10.0)
    idle_streak = 0
    while time.monotonic() < deadline:
        pending_children = has_pending_async_work(target_session_id)
        queued_items = False
        with contextlib.suppress(Exception):
            queued_items = len(workbench_queue.list_queue(target_session_id)) > 0
        busy = False
        with contextlib.suppress(Exception):
            busy = workbench_queue.is_session_busy(target_session_id)
        if not pending_children and not queued_items and not busy:
            idle_streak += 1
            if idle_streak >= 2:
                break
        else:
            idle_streak = 0
        time.sleep(poll_interval_s)

    # 提取最新 assistant 文本；若会话记录尚未刷新，也汇总子派发任务单的产出兜底
    latest_text = _extract_latest_assistant_output(target_session_id)
    if latest_text:
        return latest_text

    child_jobs = list_dispatch_jobs(caller_session_id=target_session_id, active_only=False)
    child_outputs = [
        j.output.strip()
        for j in child_jobs
        if j.output and j.output.strip()
    ]
    if child_outputs:
        return "\n\n".join(child_outputs)
    return None


def deliver_callback_to_session(
    caller_session_id: str,
    callback_prompt: str,
    *,
    job_id: str | None = None,
    cwd_hint: str | None = None,
    max_wait_s: float = 1800.0,
    poll_interval_s: float = 0.5,
) -> bool:
    """将结构化回传报文投递回发起方会话流（``workbench_queue`` + ``session_send``）。"""
    if not caller_session_id or not callback_prompt.strip():
        return False

    if _callback_sender_override is not None:
        return bool(_callback_sender_override(caller_session_id, callback_prompt, cwd_hint))

    from frago.server.services import workbench_queue

    jid = job_id
    if not jid and isinstance(callback_prompt, str):
        m = re.search(r'<frago-async-callback[^>]*job_id="([^"]+)"', callback_prompt)
        if m:
            jid = m.group(1)

    item_id: str | None = None
    try:
        item = workbench_queue.enqueue(
            caller_session_id,
            text=callback_prompt,
            prompt=callback_prompt,
            cwd=cwd_hint,
            job_id=jid,
            auto_schedule=False,  # 禁止在短命 watcher 进程中拉起后台 0.3s 守护线程自我竞争！
        )
        item_id = str(item.get("id") or "")
    except Exception:
        item_id = None

    deadline = time.monotonic() + max(max_wait_s, 5.0)
    idle_without_turn_id_ticks = 0

    while time.monotonic() < deadline:
        # 1. 优先检查权威送达回执（派发单磁盘状态与持久化队列回执）
        if jid:
            job = load_dispatch_job(jid)
            if job is not None and job.delivery_state == "delivered":
                return True

        if item_id is not None:
            receipt = workbench_queue.get_queue_delivery_receipt(caller_session_id)
            deliv_items = receipt.get("delivered_items") or []
            deliv_jobs = receipt.get("delivered_job_ids") or []
            if item_id in deliv_items or (jid and jid in deliv_jobs):
                return True

            # 若条目已被显式删除（非送达消费），判定未送达
            removed_items = receipt.get("removed_item_ids") or []
            if item_id in removed_items:
                return False

            # 2. 标准注入尝试：由 watcher 轮询同步触发一次 try_auto_inject
            try:
                outcome = workbench_queue.try_auto_inject(caller_session_id, sync=True)
                if isinstance(outcome, dict) and outcome.get("delivered"):
                    return True
            except Exception:
                pass

            # 再次检查送达回执（可能被服务端巡检或当前注入刚刚标记 delivered）
            receipt_after = workbench_queue.get_queue_delivery_receipt(caller_session_id)
            if item_id in (receipt_after.get("delivered_items") or []) or (
                jid and jid in (receipt_after.get("delivered_job_ids") or [])
            ):
                return True

        # 3. 兜底路径：仅对尚无任何历史记录的新建会话或测试桩会话，在确认不忙且无跨进程注入锁后直接出队投递
        busy = False
        with contextlib.suppress(Exception):
            busy = workbench_queue.is_session_busy(caller_session_id)

        if not busy:
            stop_turn = None
            has_records = False
            blocked_or_injecting = False
            with contextlib.suppress(Exception):
                q_state = workbench_queue.evaluate_queue_state(caller_session_id)
                stop_turn = q_state.get("stop_turn_id")
                has_records = bool(q_state.get("has_records"))
                blocked_or_injecting = bool(
                    q_state.get("blocked_by_card") or q_state.get("injecting")
                )
            if (not stop_turn and not has_records and not blocked_or_injecting) or item_id is None:
                idle_without_turn_id_ticks += 1
                if idle_without_turn_id_ticks >= 2 or item_id is None:
                    sent_ok = False
                    with workbench_queue.cross_process_inject_guard(caller_session_id) as acquired:
                        if acquired:
                            if item_id is not None:
                                r_check = workbench_queue.get_queue_delivery_receipt(caller_session_id)
                                if item_id in (r_check.get("delivered_items") or []) or (
                                    jid and jid in (r_check.get("delivered_job_ids") or [])
                                ):
                                    return True
                            try:
                                sent_ok = bool(
                                    workbench_queue._send_prompt(
                                        caller_session_id,
                                        callback_prompt,
                                        cwd_hint=cwd_hint,
                                    )
                                )
                            except Exception:
                                sent_ok = False
                            if sent_ok and item_id is not None:
                                with contextlib.suppress(Exception):
                                    workbench_queue.remove_item(caller_session_id, str(item_id))
                                    d = workbench_queue.queue_dir(caller_session_id)
                                    st = workbench_queue._read_queue_state(d)
                                    d_items = list(st.get("delivered_items") or [])
                                    d_items.append(item_id)
                                    st["delivered_items"] = d_items[-100:]
                                    if jid:
                                        d_jobs = list(st.get("delivered_job_ids") or [])
                                        d_jobs.append(jid)
                                        st["delivered_job_ids"] = d_jobs[-100:]
                                    workbench_queue._write_queue_state(d, st)
                    if sent_ok:
                        return True
        else:
            idle_without_turn_id_ticks = 0

        time.sleep(poll_interval_s)

    return False


def _spawn_detached_watcher(job_path: Path, *, target_session_id: str, target_employee_id: str | None = None) -> None:
    """拉起脱离父进程会话组的后台 watcher 进程。"""
    if _async_spawner_override is not None:
        _async_spawner_override(job_path)
        return

    if os.environ.get("FRAGO_ASYNC_DISPATCH_INLINE") == "1":
        execute_dispatch_job(job_path)
        return

    child_env = sanitize_child_env(
        os.environ,
        target_session_id=target_session_id,
        target_employee_id=target_employee_id,
    )
    log_file = dispatch_logs_dir() / f"{job_path.stem}.log"
    with open(log_file, "a", encoding="utf-8") as log_fp:
        popen_kwargs: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": log_fp,
            "stderr": log_fp,
            "close_fds": True,
            "env": child_env,
        }
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
                | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            )
        else:
            popen_kwargs["start_new_session"] = True

        subprocess.Popen(
            [sys.executable, "-m", "frago.session.async_dispatch", "--job-file", str(job_path)],
            **popen_kwargs,
        )


def dispatch_employee_turn_async(
    *,
    mode: str,
    caller_session_id: str,
    caller_cwd: str | None,
    employee_id: str,
    target_session_id: str,
    agent: str,
    cwd: str,
    prompt: str,
    task_summary: str,
    resume: str | None,
    model: str | None,
) -> AsyncDispatchJob:
    """登记同侪员工异步派发任务并拉起后台 watcher。"""
    _, caller_emp_id = is_employee_caller_session(caller_session_id)
    job = AsyncDispatchJob(
        job_id=f"disp-{uuid.uuid4().hex[:12]}",
        kind="employee",
        mode=mode,
        caller_session_id=caller_session_id,
        caller_employee_id=caller_emp_id,
        caller_cwd=caller_cwd or os.getcwd(),
        target_session_id=target_session_id,
        target_name=employee_id,
        employee_id=employee_id,
        agent=agent,
        cwd=cwd,
        prompt=prompt,
        task_summary=task_summary[:240],
        resume=resume,
        model=model,
        status="running",
    )
    job_path = save_dispatch_job(job)
    supersede_active_jobs_for_target(
        target_session_id,
        new_job_id=job.job_id,
        caller_session_id=caller_session_id,
    )
    _spawn_detached_watcher(
        job_path,
        target_session_id=target_session_id,
        target_employee_id=employee_id,
    )
    return job


def dispatch_worker_turn_async(
    *,
    mode: str,
    caller_session_id: str,
    caller_cwd: str | None,
    target_session_id: str,
    agent: str,
    cwd: str,
    prompt: str,
    task_summary: str,
    resume: str | None = None,
    model: str | None = None,
    timeout: int | None = None,
    env_list: list[str] | None = None,
) -> AsyncDispatchJob:
    """登记下属 Worker 异步派发任务并拉起后台 watcher。"""
    _, caller_emp_id = is_employee_caller_session(caller_session_id)
    job = AsyncDispatchJob(
        job_id=f"disp-{uuid.uuid4().hex[:12]}",
        kind="worker",
        mode=mode,
        caller_session_id=caller_session_id,
        caller_employee_id=caller_emp_id,
        caller_cwd=caller_cwd or os.getcwd(),
        target_session_id=target_session_id,
        target_name=target_session_id,
        employee_id=None,
        agent=agent,
        cwd=cwd,
        prompt=prompt,
        task_summary=task_summary[:240],
        resume=resume,
        model=model,
        timeout=timeout,
        env_list=list(env_list or []),
        status="running",
    )
    job_path = save_dispatch_job(job)
    supersede_active_jobs_for_target(
        target_session_id,
        new_job_id=job.job_id,
        caller_session_id=caller_session_id,
    )
    _spawn_detached_watcher(
        job_path,
        target_session_id=target_session_id,
        target_employee_id=None,
    )
    return job


def dispatch_drive_send_async(
    *,
    caller_session_id: str,
    caller_cwd: str | None,
    target_session_id: str,
    target_name: str,
    agent: str,
    cwd: str,
    prompt: str,
    timeout: float = 600.0,
) -> AsyncDispatchJob:
    """登记 ``frago agent send`` 异步派发任务并拉起后台 watcher。"""
    _, caller_emp_id = is_employee_caller_session(caller_session_id)
    job = AsyncDispatchJob(
        job_id=f"disp-{uuid.uuid4().hex[:12]}",
        kind="drive_send",
        mode="send",
        caller_session_id=caller_session_id,
        caller_employee_id=caller_emp_id,
        caller_cwd=caller_cwd or os.getcwd(),
        target_session_id=target_session_id,
        target_name=target_name,
        employee_id=None,
        agent=agent,
        cwd=cwd,
        prompt=prompt,
        task_summary=prompt[:240],
        timeout=int(timeout),
        status="running",
    )
    job_path = save_dispatch_job(job)
    supersede_active_jobs_for_target(
        target_session_id,
        new_job_id=job.job_id,
        caller_session_id=caller_session_id,
    )
    _spawn_detached_watcher(
        job_path,
        target_session_id=target_session_id,
        target_employee_id=None,
    )
    return job


def _execute_employee_job(job: AsyncDispatchJob) -> tuple[int, str, str]:
    """在后台 watcher 中执行同侪员工回合。"""
    import inspect

    import frago.cli.employee_commands as emp_cli
    from frago.employee import get_post, save_post
    from frago.session.session_origin import record_relation

    fn = emp_cli._run_agent_turn_for_employee
    sig = inspect.signature(fn)
    kwargs: dict[str, Any] = {
        "cwd": job.cwd,
        "timeout_s": float(job.timeout or 0.0),
    }
    if "session_id" in sig.parameters:
        kwargs["session_id"] = job.target_session_id
    if "employee_id" in sig.parameters:
        kwargs["employee_id"] = job.employee_id

    old_target = job.target_session_id
    real_sid, turn_status, answer_text = fn(job.agent, job.prompt, **kwargs)
    resolved_sid = (
        (_resolve_bound_session_id(real_sid)[0] if real_sid else None)
        or _resolve_bound_session_id(old_target)[0]
        or real_sid
        or old_target
    )
    if resolved_sid and resolved_sid != old_target:
        job.target_session_id = resolved_sid
        if job.target_name == old_target:
            job.target_name = resolved_sid
        save_dispatch_job(job)
    elif resolved_sid:
        job.target_session_id = resolved_sid

    with contextlib.suppress(Exception):
        record_relation(
            kind="dispatch",
            child_session_id=job.target_session_id,
            parent_session_id=job.caller_session_id,
            agent_type=job.agent,
            cwd=job.cwd,
            prompt_head=job.task_summary,
        )

    if job.employee_id and job.target_session_id:
        with contextlib.suppress(Exception):
            rec = get_post(job.employee_id)
            if rec is not None:
                cleaned_ids = [
                    s for s in rec.active_session_ids if s and s != old_target
                ]
                if job.target_session_id not in cleaned_ids:
                    cleaned_ids.append(job.target_session_id)
                if cleaned_ids != rec.active_session_ids:
                    rec.active_session_ids = cleaned_ids
                    save_post(rec)

    ok = turn_status in ("ok", "needs_input")
    clean_ans = str(answer_text or "").strip()
    if ok:
        err = ""
    else:
        err = (
            f"Employee turn ended with status '{turn_status}': {clean_ans}"
            if clean_ans
            else f"Employee turn ended with status '{turn_status}'"
        )
    return (0 if ok else 1), clean_ans, err


def _execute_worker_job(job: AsyncDispatchJob) -> tuple[int, str, str]:
    """在后台 watcher 中执行下属 Worker 回合。"""
    import frago.cli.agent_command as agent_cli
    from frago.session.session_origin import record_relation

    old_target = job.target_session_id
    real_sid, turn_status, answer_text = agent_cli._run_worker_turn_sync(
        job.prompt,
        agent_type=job.agent,
        session_id=job.target_session_id,
        native_session_id=bool(job.resume),
        cwd=job.cwd,
        timeout=int(job.timeout or 0),
        model=job.model,
        env_list=job.env_list,
    )
    resolved_sid = (
        (_resolve_bound_session_id(real_sid)[0] if real_sid else None)
        or _resolve_bound_session_id(old_target)[0]
        or real_sid
        or old_target
    )
    if resolved_sid and resolved_sid != old_target:
        job.target_session_id = resolved_sid
        if job.target_name == old_target:
            job.target_name = resolved_sid
        save_dispatch_job(job)
    elif resolved_sid:
        job.target_session_id = resolved_sid

    with contextlib.suppress(Exception):
        record_relation(
            kind="dispatch",
            child_session_id=job.target_session_id,
            parent_session_id=job.caller_session_id,
            agent_type=job.agent,
            cwd=job.cwd,
            prompt_head=job.task_summary,
        )

    ok = turn_status == "ok"
    clean_ans = str(answer_text or "").strip()
    if ok:
        err = ""
    else:
        err = (
            f"Worker turn ended with status '{turn_status}': {clean_ans}"
            if clean_ans
            else f"Worker turn ended with status '{turn_status}'"
        )
    return (0 if ok else 1), clean_ans, err


def _execute_drive_send_job(job: AsyncDispatchJob) -> tuple[int, str, str]:
    """在后台 watcher 中执行 ``frago agent send`` 并等待目标回合完成。"""
    from frago.agent_driver.driver import load_driver
    from frago.cli.drive_command import (
        _bind_session,
        _refresh_tmux_name,
        _resolve_or_die,
        _try_clear_residual_input,
        make_runner,
    )

    name = job.target_name or job.target_session_id
    try:
        entry = _resolve_or_die(name)
        runner = make_runner()
        driver = load_driver(entry.agent_type)
        session = _bind_session(entry, driver, runner)
        pane = session.capture_pane()
        healed = False
        if not driver.ready_signal.matches(pane):
            pane, healed = _try_clear_residual_input(session, driver, pane)
        if not (healed or driver.ready_signal.matches(pane)):
            return 1, "", f"Session {name!r} is not ready for input"
        result = session.send(
            job.prompt,
            timeout_s=float(job.timeout) if job.timeout and job.timeout > 0 else None,
        )
        _refresh_tmux_name(entry, session)
        ok = result.status == "ok"
        return (0 if ok else 1), str(result.text or "").strip(), ("" if ok else f"status={result.status}")
    except Exception as exc:
        return 1, "", str(exc)


def execute_dispatch_job(job_path: Path) -> AsyncDispatchJob | None:
    """后台 watcher 主流程：执行目标回合 -> 等待子级联任务 -> 组装报文并回投父会话。"""
    job = load_dispatch_job(job_path)
    if job is None:
        return None

    superseded, sup_by = is_job_superseded(job)
    if superseded:
        job.status = "superseded"
        job.superseded_by = sup_by or job.superseded_by
        job.completed_at = job.completed_at or _utc_now()
        save_dispatch_job(job)
        return job

    orig_env = dict(os.environ)
    try:
        # 清洗当前后台进程环境变量，确保子回合内 resolve_self() 指向 target_session_id
        cleaned = sanitize_child_env(
            os.environ,
            target_session_id=job.target_session_id,
            target_employee_id=job.employee_id,
        )
        for k in list(os.environ.keys()):
            if k in SESSION_IDENTITY_ENV or k in ("FRAGO_CALLBACK_SESSION_ID", "FRAGO_EMPLOYEE_ID", "FRAGO_LAUNCH_HANDLE"):
                os.environ.pop(k, None)
        for k, v in cleaned.items():
            os.environ[k] = v

        job.status = "running"
        save_dispatch_job(job)

        try:
            if job.kind == "employee":
                rc, out, err = _execute_employee_job(job)
            elif job.kind == "drive_send":
                rc, out, err = _execute_drive_send_job(job)
            else:
                rc, out, err = _execute_worker_job(job)

            superseded, sup_by = is_job_superseded(job)
            if superseded:
                job.status = "superseded"
                job.superseded_by = sup_by or job.superseded_by
                job.completed_at = _utc_now()
                job.error = f"Superseded by {job.superseded_by}" if job.superseded_by else "Superseded"
                save_dispatch_job(job)
                return job

            # 多跳屏障：若目标会话（如同侪员工 B）在回合内又发起了子异步派发，等待其收口并提取最终结论
            cascaded_out = wait_for_pending_child_dispatches(
                job.target_session_id,
                timeout_s=float(job.timeout or 1800.0),
            )
            if cascaded_out:
                out = cascaded_out

            job.exit_code = int(rc)
            job.output = out or ""
            job.error = err or ""
            job.status = "running"
            save_dispatch_job(job)
        except Exception as exc:
            superseded, sup_by = is_job_superseded(job)
            if superseded:
                job.status = "superseded"
                job.superseded_by = sup_by or job.superseded_by
                job.completed_at = _utc_now()
                job.error = f"Superseded by {job.superseded_by}" if job.superseded_by else "Superseded"
                save_dispatch_job(job)
                return job
            job.exit_code = 1
            job.error = str(exc)
            job.status = "running"
            save_dispatch_job(job)

        superseded, sup_by = is_job_superseded(job)
        if superseded:
            job.status = "superseded"
            job.superseded_by = sup_by or job.superseded_by
            job.completed_at = _utc_now()
            save_dispatch_job(job)
            return job

        callback_prompt = format_callback_prompt(job)
        delivered = False
        delivery_err: str | None = None
        try:
            delivered = deliver_callback_to_session(
                job.caller_session_id,
                callback_prompt,
                job_id=job.job_id,
                cwd_hint=job.caller_cwd,
            )
        except Exception as exc:
            delivered = False
            delivery_err = str(exc)

        cur_job = load_dispatch_job(job.job_id) or job
        if delivered:
            if cur_job.delivery_state != "delivered":
                if cur_job.delivery_state == "queued":
                    record_callback_delivery_outcome(
                        job.job_id,
                        from_state="queued",
                        to_state="delivering",
                        prior_delivery_state=cur_job.delivery_state,
                    )
                    cur_job = load_dispatch_job(job.job_id) or cur_job
                if cur_job.delivery_state == "delivering":
                    record_callback_delivery_outcome(
                        job.job_id,
                        from_state="delivering",
                        to_state="delivered",
                        prior_delivery_state=cur_job.delivery_state,
                    )
            target_status = "completed" if job.exit_code == 0 else "failed"
            finalize_dispatch_job(
                job.job_id,
                exit_code=job.exit_code,
                delivery_state="delivered",
                job_status=target_status,
                prior_delivery_state="delivered",
            )
        else:
            from frago.server.services import workbench_queue

            remaining = workbench_queue.list_queue(job.caller_session_id)
            has_item = any(it.get("job_id") == job.job_id for it in remaining)
            if has_item:
                if cur_job.delivery_state == "delivering":
                    record_callback_delivery_outcome(
                        job.job_id,
                        from_state="delivering",
                        to_state="queued",
                        reason=delivery_err or "Watcher wait window elapsed; retained in queue for patrol",
                        prior_delivery_state=cur_job.delivery_state,
                    )
            else:
                if cur_job.delivery_state == "queued":
                    record_callback_delivery_outcome(
                        job.job_id,
                        from_state="queued",
                        to_state="delivering",
                        prior_delivery_state=cur_job.delivery_state,
                    )
                    cur_job = load_dispatch_job(job.job_id) or cur_job
                if cur_job.delivery_state == "delivering":
                    record_callback_delivery_outcome(
                        job.job_id,
                        from_state="delivering",
                        to_state="failed",
                        reason=delivery_err or "Callback delivery could not be confirmed",
                        prior_delivery_state=cur_job.delivery_state,
                    )
                finalize_dispatch_job(
                    job.job_id,
                    exit_code=job.exit_code,
                    delivery_state="failed",
                    job_status="failed",
                    prior_delivery_state="failed",
                )

        reloaded = load_dispatch_job(job.job_id)
        if reloaded is not None:
            job = reloaded
        sys.stderr.write(
            f"[{_utc_now()}] [watcher-finalize] job={job.job_id} worker_rc={job.exit_code} "
            f"delivery_state={job.delivery_state} job_status={job.status} error={job.delivery_error or job.error}\n"
        )
        sys.stderr.flush()
        return job
    finally:
        os.environ.clear()
        os.environ.update(orig_env)


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    job_file: str | None = None
    i = 0
    while i < len(args):
        if args[i] == "--job-file" and i + 1 < len(args):
            job_file = args[i + 1]
            i += 2
        else:
            i += 1
    if not job_file:
        return 2
    job = execute_dispatch_job(Path(job_file))
    return 0 if job is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
