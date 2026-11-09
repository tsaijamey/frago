"""frago employee — CLI system-call entrypoint for the Employee ontology.

  frago employee list/show/hire/bind/discover/invoke/govern/context/data/sync-ledger/ledger/rm/schema

Thin CLI wrapper over ``frago.employee`` (`store.py` + `ledger.py` + `service.py`), bound to
`CliCommandActionContract` (`frago.employee.invoke`, `frago.employee.govern`,
`frago.employee.discover`) and guarded by `invoke_domain_employee` and
`govern_employee_domain_assets` kinetic contracts.
"""

from __future__ import annotations

import json
import os
from typing import Any

import click

from frago.employee import (
    EMPLOYEE_POST_SCHEMA,
    VALID_AGENT_KERNELS,
    EmployeeOntologyService,
    delete_post,
    get_post,
    ledger_summary,
    list_posts,
    load_ledger,
)
from frago.ontology import ContractViolationError

from .agent_friendly import AgentFriendlyCommand, AgentFriendlyGroup

_KERNEL_CHOICE = click.Choice(list(VALID_AGENT_KERNELS))
_ASSET_KIND_CHOICE = click.Choice(
    ["knowledge_domain", "recipe", "data_slot", "schedule"]
)
_GOVERN_OP_CHOICE = click.Choice(
    [
        "refresh_data",
        "curate_knowledge",
        "update_recipe",
        "self_alarm",
        "irreversible_delete",
    ]
)


def _print_posts_list(*, as_json: bool = False) -> None:
    posts = list_posts()
    if as_json:
        click.echo(
            json.dumps([p.to_dict() for p in posts], ensure_ascii=False, indent=2)
        )
        return
    if not posts:
        click.echo("No employee posts registered (~/.frago/employees/).")
        return
    for post in posts:
        domains = ", ".join(post.knowledge_domains) or "-"
        recipes = ", ".join(post.recipes) or "-"
        click.echo(
            f"{post.member_post_id}  [{post.agent_kernel}]  {post.title}  "
            f"(domains: {domains}; recipes: {recipes})"
        )


@click.group(name="employee", cls=AgentFriendlyGroup, invoke_without_command=True)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def employee_group(ctx: click.Context, as_json: bool) -> None:
    """Manage domain employee posts (+R) and role bindings (~R) under ~/.frago/employees/."""
    if ctx.invoked_subcommand is not None:
        return
    _print_posts_list(as_json=as_json)


@employee_group.command(name="list", cls=AgentFriendlyCommand)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def employee_list(as_json: bool) -> None:
    """List all registered domain employee posts."""
    _print_posts_list(as_json=as_json)


@employee_group.command(name="schema", cls=AgentFriendlyCommand)
def employee_schema() -> None:
    """Print the self-describing schema for EmployeePostResource (+R) and DomainEmployeeRole (~R)."""
    click.echo(json.dumps(EMPLOYEE_POST_SCHEMA, ensure_ascii=False, indent=2))


@employee_group.command(name="show", cls=AgentFriendlyCommand)
@click.argument("member_post_id")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def employee_show(member_post_id: str, as_json: bool) -> None:
    """Show full details and ontology graph bindings of an employee post."""
    try:
        record = get_post(member_post_id)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from None
    if record is None:
        raise click.ClickException(f"Employee post '{member_post_id}' not found.")
    if as_json:
        click.echo(json.dumps(record.to_dict(), ensure_ascii=False, indent=2))
        return
    click.echo(f"Post (+R):   post:{record.member_post_id} ({record.title})")
    click.echo(
        f"Role (~R):   DomainEmployeeRole:kernel:{record.agent_kernel}@post:{record.member_post_id}"
    )
    if record.description:
        click.echo(f"Description: {record.description}")
    if record.work_scope:
        click.echo(f"WorkScope:   {record.work_scope}")
    if record.cwd:
        click.echo(f"Cwd:         {record.cwd}")
    click.echo(f"Domains:     {', '.join(record.knowledge_domains) or '-'}")
    click.echo(f"Recipes:     {', '.join(record.recipes) or '-'}")
    click.echo(f"DataSlots:   {', '.join(record.data_slots) or '-'}")
    click.echo(f"Skills:      {', '.join(record.skills) or '-'}")
    click.echo(f"Commands:    {', '.join(record.allowed_commands) or '-'}")
    click.echo(f"Schedules:   {', '.join(record.schedule_ids) or '-'}")
    click.echo(f"Sessions:    {', '.join(record.active_session_ids) or '-'}")


@employee_group.command(name="hire", cls=AgentFriendlyCommand)
@click.argument("member_post_id")
@click.option("--title", required=True, help="Display title of the employee post")
@click.option(
    "--kernel",
    "agent_kernel",
    type=_KERNEL_CHOICE,
    default="claude",
    show_default=True,
    help="AgentKernel playing DomainEmployeeRole on this post",
)
@click.option("--description", default="", help="Post charter and responsibilities")
@click.option(
    "--scope",
    "work_scope",
    default=None,
    help="Generalized working scope & methodology (how to handle unenumerated tasks too)",
)
@click.option(
    "--cwd",
    default=None,
    help="Default working directory when a new conversation is started for this post",
)
@click.option(
    "--domain",
    "knowledge_domains",
    multiple=True,
    help="KnowledgeDomain governed by this post (repeatable)",
)
@click.option(
    "--recipe",
    "recipes",
    multiple=True,
    help="RecipeModule governed by this post (repeatable)",
)
@click.option(
    "--slot",
    "data_slots",
    multiple=True,
    help="DataSlot path governed by this post (repeatable)",
)
@click.option(
    "--schedule",
    "schedule_ids",
    multiple=True,
    help="ScheduleRuleSpec ID governing this role (repeatable)",
)
@click.option(
    "--command",
    "allowed_commands",
    multiple=True,
    help="CliCommandActionContract command_path granted to this post (repeatable)",
)
@click.option(
    "--skill",
    "skills",
    multiple=True,
    help="Default Skill name automatically mounted when starting a session (repeatable)",
)
@click.option(
    "--no-schedule",
    "skip_schedule",
    is_flag=True,
    help="Skip auto-registering the daily ledger sync schedule",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def employee_hire(
    member_post_id: str,
    title: str,
    agent_kernel: str,
    description: str,
    work_scope: str | None,
    cwd: str | None,
    knowledge_domains: tuple[str, ...],
    recipes: tuple[str, ...],
    data_slots: tuple[str, ...],
    schedule_ids: tuple[str, ...],
    allowed_commands: tuple[str, ...],
    skills: tuple[str, ...],
    skip_schedule: bool,
    as_json: bool,
) -> None:
    """Create or update an employee post (+R) and bind its AgentKernel role (~R)."""
    svc = EmployeeOntologyService()
    try:
        record, proj = svc.hire(
            member_post_id,
            title=title,
            agent_kernel=agent_kernel,
            description=description,
            work_scope=work_scope,
            cwd=cwd,
            knowledge_domains=knowledge_domains,
            recipes=recipes,
            data_slots=data_slots,
            schedule_ids=schedule_ids,
            allowed_commands=allowed_commands if allowed_commands else None,
            skills=skills if skills else None,
        )
    except (ValueError, ContractViolationError) as exc:
        raise click.ClickException(str(exc)) from None

    if not skip_schedule and (
        not os.environ.get("PYTEST_CURRENT_TEST")
        or os.environ.get("FRAGO_EMPLOYEE_AUTO_SCHEDULE") == "1"
    ):
        try:
            add_schedule, list_schedules = _scheduler_hooks()
            svc.ensure_ledger_schedule(
                record.member_post_id,
                add_schedule=add_schedule,
                list_schedules=list_schedules,
            )
            record = get_post(record.member_post_id) or record
        except Exception:  # noqa: BLE001 - 排程接不上不阻断建岗
            pass

    if as_json:
        payload = record.to_dict()
        payload["post_ontological_id"] = proj.post.ontological_id()
        payload["role_ontological_id"] = proj.employee_role.ontological_id()
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(
        f"Hired {proj.post.ontological_id()} -> {proj.employee_role.ontological_id()}"
    )


@employee_group.command(name="bind", cls=AgentFriendlyCommand)
@click.argument("member_post_id")
@click.option(
    "--kernel",
    "agent_kernel",
    type=_KERNEL_CHOICE,
    default=None,
    help="Switch the AgentKernel (~R) playing DomainEmployeeRole on this post",
)
@click.option(
    "--scope",
    "work_scope",
    default=None,
    help="Replace the generalized working scope & methodology",
)
@click.option(
    "--cwd",
    default=None,
    help="Replace the default working directory for new conversations",
)
@click.option(
    "--domain",
    "knowledge_domains",
    multiple=True,
    help="Additional KnowledgeDomain to bind (repeatable)",
)
@click.option(
    "--recipe",
    "recipes",
    multiple=True,
    help="Additional RecipeModule to bind (repeatable)",
)
@click.option(
    "--slot",
    "data_slots",
    multiple=True,
    help="Additional DataSlot path to bind (repeatable)",
)
@click.option(
    "--schedule",
    "schedule_ids",
    multiple=True,
    help="Additional ScheduleRuleSpec ID to bind (repeatable)",
)
@click.option(
    "--command",
    "allowed_commands",
    multiple=True,
    help="Additional CliCommandActionContract command_path to bind (repeatable)",
)
@click.option(
    "--skill",
    "skills",
    multiple=True,
    help="Additional default Skill name to bind (repeatable)",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def employee_bind(
    member_post_id: str,
    agent_kernel: str | None,
    work_scope: str | None,
    cwd: str | None,
    knowledge_domains: tuple[str, ...],
    recipes: tuple[str, ...],
    data_slots: tuple[str, ...],
    schedule_ids: tuple[str, ...],
    allowed_commands: tuple[str, ...],
    skills: tuple[str, ...],
    as_json: bool,
) -> None:
    """Bind territory assets or reassign the AgentKernel (~R) without changing post identity (+R)."""
    svc = EmployeeOntologyService()
    try:
        record, proj = svc.bind_territory(
            member_post_id,
            agent_kernel=agent_kernel,
            work_scope=work_scope,
            cwd=cwd,
            knowledge_domains=knowledge_domains,
            recipes=recipes,
            data_slots=data_slots,
            schedule_ids=schedule_ids,
            allowed_commands=allowed_commands,
            skills=skills,
        )
    except (KeyError, ValueError, ContractViolationError) as exc:
        raise click.ClickException(str(exc)) from None

    if as_json:
        payload = record.to_dict()
        payload["post_ontological_id"] = proj.post.ontological_id()
        payload["role_ontological_id"] = proj.employee_role.ontological_id()
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(
        f"Updated {proj.post.ontological_id()} -> {proj.employee_role.ontological_id()}"
    )


@employee_group.command(name="discover", cls=AgentFriendlyCommand)
@click.option("--domain", default=None, help="Filter by governed KnowledgeDomain")
@click.option("--recipe", default=None, help="Filter by governed RecipeModule")
@click.option("--slot", "data_slot", default=None, help="Filter by governed DataSlot")
@click.option(
    "--schedule", "schedule_id", default=None, help="Filter by ScheduleRuleSpec ID"
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def employee_discover(
    domain: str | None,
    recipe: str | None,
    data_slot: str | None,
    schedule_id: str | None,
    as_json: bool,
) -> None:
    """Query the ontology graph via SPARQL to find which employee governs an asset."""
    svc = EmployeeOntologyService()
    matched = svc.discover(
        domain=domain,
        recipe=recipe,
        data_slot=data_slot,
        schedule_id=schedule_id,
    )
    if as_json:
        click.echo(
            json.dumps([m.to_dict() for m in matched], ensure_ascii=False, indent=2)
        )
        return
    if not matched:
        click.echo("No matching employee posts found.")
        return
    for post in matched:
        click.echo(f"{post.member_post_id}  [{post.agent_kernel}]  {post.title}")


SPAWN_INCOMPLETE_NOTICE = (
    "【未完成信号】子会话刚刚启动并在后台运行中，当前尚未产出最终结果，严禁将此启动回执当作任务已完成"
)


def _launch_employee_session(
    record: Any,
    query_or_task: str,
) -> dict[str, Any]:
    """为 CLI `frago employee invoke` 拉起真实会话，完整挂载员工语境、默认技能与三角色舞台编排。"""
    import time
    import uuid
    from pathlib import Path

    from frago.server.services import workbench_new_session
    from frago.skills.skill_prompt import embed_skills, load_skills

    svc = EmployeeOntologyService()
    session_cwd = record.cwd.strip() if getattr(record, "cwd", "") else ""
    if not session_cwd:
        fallback = Path.home() / ".frago"
        fallback.mkdir(parents=True, exist_ok=True)
        session_cwd = str(fallback)
    session_cwd = str(Path(session_cwd).expanduser())
    cwd_path = Path(session_cwd)
    frago_root = (Path.home() / ".frago").resolve()
    resolved_cwd = cwd_path.resolve()
    if resolved_cwd == frago_root or frago_root in resolved_cwd.parents:
        cwd_path.mkdir(parents=True, exist_ok=True)

    effective_skills = list(getattr(record, "skills", None) or [])

    if not os.environ.get("PYTEST_CURRENT_TEST"):
        import urllib.error
        import urllib.request

        server_port = os.environ.get("FRAGO_SERVER_PORT", "8093")
        api_base = f"http://127.0.0.1:{server_port}/api/workbench/sessions"
        payload = json.dumps(
            {
                "agent": record.agent_kernel,
                "cwd": session_cwd,
                "text": query_or_task.strip(),
                "employee": record.member_post_id,
                "skills": effective_skills,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            api_base,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            sid = data.get("session_id")
            handle = data.get("handle")
            err = data.get("error")
            if sid is None and handle and not err:
                for _ in range(16):
                    time.sleep(0.5)
                    try:
                        with urllib.request.urlopen(
                            f"{api_base}/pending/{handle}", timeout=5
                        ) as p_resp:
                            p_data = json.loads(p_resp.read().decode("utf-8"))
                        if p_data.get("session_id") or p_data.get("error"):
                            sid = p_data.get("session_id")
                            err = p_data.get("error")
                            break
                    except Exception:  # noqa: BLE001
                        break
            return {
                "session_id": sid,
                "handle": handle,
                "cwd": data.get("cwd") or session_cwd,
                "agent": data.get("agent") or record.agent_kernel,
                "stage_orchestrated": False,
                "completion_state": "error" if err else "running_in_background",
                "is_completed": False,
                "notice": SPAWN_INCOMPLETE_NOTICE if not err else "",
                "error": err,
            }
        except urllib.error.HTTPError as http_exc:
            detail = http_exc.read().decode("utf-8", errors="replace")
            return {
                "session_id": None,
                "handle": None,
                "cwd": session_cwd,
                "agent": record.agent_kernel,
                "stage_orchestrated": False,
                "completion_state": "error",
                "is_completed": False,
                "notice": "",
                "error": f"HTTP {http_exc.code}: {detail}",
            }
        except Exception:  # noqa: BLE001 — 本地服务未启动时降级走进程内直起
            pass

    launch_id = str(uuid.uuid4())
    context_block = svc.build_business_context_block(record.member_post_id)
    prompt = f"{context_block}\n\n{query_or_task.strip()}"

    if effective_skills:
        loaded = load_skills(effective_skills)
        prompt = embed_skills(prompt, loaded, user_text=query_or_task)

    launch = workbench_new_session.start_with_id(
        record.agent_kernel,
        session_cwd,
        prompt,
        session_id=launch_id,
    )
    workbench_new_session.bind_employee(launch.handle, record.member_post_id)

    if launch.session_id is None and not launch.error and not os.environ.get("PYTEST_CURRENT_TEST"):
        for _ in range(16):
            st = workbench_new_session.status(launch.handle)
            if st is not None and (st.session_id or st.error or st.finished):
                launch = st
                break
            time.sleep(0.5)

    return {
        "session_id": launch.session_id,
        "handle": launch.handle,
        "cwd": launch.cwd,
        "agent": launch.agent_type,
        "stage_orchestrated": False,
        "completion_state": "error" if launch.error else "running_in_background",
        "is_completed": False,
        "notice": SPAWN_INCOMPLETE_NOTICE if not launch.error else "",
        "error": launch.error,
    }


def _run_agent_turn_for_employee(
    agent_kernel: str,
    prompt: str,
    *,
    cwd: str,
    timeout_s: float = 0.0,
    session_id: str | None = None,
    employee_id: str | None = None,
) -> tuple[str, str, str]:
    """驱动目标员工内核执行单轮同步问答，返回 `(real_session_id, turn_status, answer_text)`。"""
    import contextlib
    import uuid

    from frago.agent_driver.driver import listed_session_id, runs_on_kernel

    effective_timeout = float(timeout_s) if timeout_s > 0 else None
    emp_id = (employee_id or os.environ.get("FRAGO_EMPLOYEE_ID") or "").strip()

    if runs_on_kernel(agent_kernel):
        from frago.agent_driver import kernel_backend

        sid = session_id or kernel_backend.new_session_id()
        env = {"FRAGO_AGENT_ROLE": "employee", "FRAGO_SESSION_ID": sid}
        if emp_id:
            env["FRAGO_EMPLOYEE_ID"] = emp_id
        turn = kernel_backend.run_turn(
            prompt,
            session_id=sid,
            cwd=cwd,
            timeout_s=effective_timeout,
            env=env,
        )
        return sid, str(turn.status or "ok"), str(turn.text or "").strip()

    from frago.agent_driver import SessionLauncher

    sid = session_id or str(uuid.uuid4())
    native_flag = bool(session_id and agent_kernel == "claude")
    env = {"FRAGO_AGENT_ROLE": "employee"}
    if emp_id:
        env["FRAGO_EMPLOYEE_ID"] = emp_id
    res = SessionLauncher().run(
        prompt,
        agent_type=agent_kernel,
        session_id=sid,
        native_session_id=native_flag,
        cwd=cwd,
        env=env,
        timeout_s=effective_timeout,
    )
    with contextlib.suppress(Exception):
        from frago.agent_driver.transcript import write_turn

        write_turn(sid, agent_kernel, cwd, prompt, res, source="employee-invoke")

    real_sid = sid
    with contextlib.suppress(Exception):
        resolved = listed_session_id(agent_kernel, sid, native_session_id=native_flag)
        if resolved:
            real_sid = resolved
    return real_sid, str(res.status or "ok"), str(res.text or "").strip()


def _build_employee_peer_prompt(
    record: Any,
    query_or_task: str,
    *,
    caller_context_id: str = "cli:owner",
) -> tuple[str, str]:
    """装配目标员工的工作目录与完整 `<frago-employee>` 语境提示词。"""
    from pathlib import Path

    from frago.skills.skill_prompt import embed_skills, load_skills

    svc = EmployeeOntologyService()
    session_cwd = record.cwd.strip() if getattr(record, "cwd", "") else ""
    if not session_cwd:
        fallback = Path.home() / ".frago"
        fallback.mkdir(parents=True, exist_ok=True)
        session_cwd = str(fallback)
    session_cwd = str(Path(session_cwd).expanduser())
    cwd_path = Path(session_cwd)
    frago_root = (Path.home() / ".frago").resolve()
    resolved_cwd = cwd_path.resolve()
    if resolved_cwd == frago_root or frago_root in resolved_cwd.parents:
        cwd_path.mkdir(parents=True, exist_ok=True)

    context_block = svc.build_business_context_block(record.member_post_id)
    prompt = (
        f"{context_block}\n\n"
        f"【跨域同侪协查请求（调用方: {caller_context_id}）】\n"
        f"{query_or_task.strip()}\n\n"
        "请基于你管辖的业务数据底账、知识域、配方工具链与近期会话脉络，"
        "直接给出清晰、可核验的业务结论（若需调配你名下的配方或普通 worker，可先行执行后再汇总交付）。"
    )
    effective_skills = list(getattr(record, "skills", None) or [])
    if effective_skills:
        loaded = load_skills(effective_skills)
        prompt = embed_skills(prompt, loaded, user_text=query_or_task)
    return session_cwd, prompt


def _maybe_record_schedule_session(session_id: str | None) -> None:
    """若在定时任务环境中运行，将本轮主会话编号记入回传文件供调度器捕获。"""
    if not session_id:
        return
    sched_file = os.environ.get("FRAGO_SCHEDULE_SESSION_FILE")
    if sched_file:
        import contextlib
        from pathlib import Path

        with contextlib.suppress(Exception):
            Path(sched_file).write_text(str(session_id).strip(), encoding="utf-8")


def _execute_employee_sync_turn(
    record: Any,
    query_or_task: str,
    *,
    caller_context_id: str = "cli:owner",
    timeout_s: float = 0.0,
) -> dict[str, Any]:
    """装配目标员工完整 `<frago-employee>` 语境块并同步执行一轮推理，返回真实业务结论。"""
    import inspect

    session_cwd, prompt = _build_employee_peer_prompt(
        record,
        query_or_task,
        caller_context_id=caller_context_id,
    )
    turn_kwargs: dict[str, Any] = {
        "cwd": session_cwd,
        "timeout_s": timeout_s,
    }
    sig = inspect.signature(_run_agent_turn_for_employee)
    if "employee_id" in sig.parameters:
        turn_kwargs["employee_id"] = getattr(record, "member_post_id", None)
    real_sid, turn_status, answer_text = _run_agent_turn_for_employee(
        record.agent_kernel,
        prompt,
        **turn_kwargs,
    )
    mapped_status = "needs_input" if turn_status == "needs_input" else "ok"
    err = (
        None
        if turn_status in ("ok", "needs_input")
        else f"Employee turn ended with status '{turn_status}'"
    )
    return {
        "status": mapped_status,
        "session_id": real_sid,
        "cwd": session_cwd,
        "agent": record.agent_kernel,
        "turn_status": turn_status,
        "completion_state": "completed" if turn_status == "ok" else turn_status,
        "is_completed": turn_status == "ok",
        "text": answer_text,
        "answer_summary": (
            answer_text
            or f"DomainEmployeeRole(post:{record.member_post_id}) executed '{query_or_task}'"
        ),
        "error": err,
    }


def _dispatch_employee_async_turn(
    record: Any,
    query_or_task: str,
    *,
    mode: str,
    caller_session_id: str,
    caller_context_id: str = "cli:owner",
    timeout_s: float = 0.0,  # noqa: ARG001
) -> dict[str, Any]:
    """非阻塞异步派发目标员工回合，立即返回 `[dispatched]` 回执并在后台完成后回投至发起方会话流。"""
    import contextlib
    import uuid

    from frago.agent_driver.driver import listed_session_id, runs_on_kernel
    from frago.session.async_dispatch import (
        dispatch_employee_turn_async,
        format_dispatched_receipt,
    )
    from frago.session.session_origin import record_relation

    session_cwd, prompt = _build_employee_peer_prompt(
        record,
        query_or_task,
        caller_context_id=caller_context_id,
    )
    if runs_on_kernel(record.agent_kernel):
        from frago.agent_driver import kernel_backend

        raw_sid = kernel_backend.new_session_id()
    else:
        raw_sid = str(uuid.uuid4())

    target_sid = (
        listed_session_id(record.agent_kernel, raw_sid, native_session_id=False)
        or raw_sid
    )
    with contextlib.suppress(Exception):
        record_relation(
            kind="dispatch",
            child_session_id=target_sid,
            parent_session_id=caller_session_id,
            agent_type=record.agent_kernel,
            cwd=session_cwd,
            prompt_head=query_or_task,
        )

    job = dispatch_employee_turn_async(
        mode=mode,
        caller_session_id=caller_session_id,
        caller_cwd=os.getcwd(),
        employee_id=record.member_post_id,
        target_session_id=target_sid,
        agent=record.agent_kernel,
        cwd=session_cwd,
        prompt=prompt,
        task_summary=query_or_task,
        resume=None,
        model=None,
    )
    receipt_text = format_dispatched_receipt(job, output_format="text")
    return {
        "status": "dispatched",
        "job_id": job.job_id,
        "session_id": target_sid,
        "caller_session_id": caller_session_id,
        "cwd": session_cwd,
        "agent": record.agent_kernel,
        "turn_status": "running_in_background",
        "completion_state": "running_in_background",
        "is_completed": False,
        "text": receipt_text,
        "answer_summary": receipt_text,
        "error": None,
    }


@employee_group.command(name="invoke", cls=AgentFriendlyCommand)
@click.argument("member_post_id")
@click.argument("query_or_task")
@click.option(
    "--asset",
    "requested_asset_id",
    default=None,
    help="Target asset within the employee's territory (e.g. domain:architecture)",
)
@click.option(
    "--caller",
    "caller_context_id",
    default="cli:owner",
    show_default=True,
    help="Caller context identifier",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Validate invocation contract only without spawning a live agent session",
)
@click.option(
    "--spawn",
    "force_spawn",
    is_flag=True,
    help="Force real workbench session launch even under test environment",
)
@click.option(
    "--wait",
    "wait_for_answer",
    is_flag=True,
    help="Synchronously wait for the target employee's real conclusion text",
)
@click.option(
    "--async",
    "force_async",
    is_flag=True,
    help="Non-blocking async dispatch with automatic callback into caller session stream",
)
@click.option(
    "--callback-session",
    "callback_session_id",
    default=None,
    help="Explicit caller session ID to receive the async completion callback",
)
@click.option(
    "--timeout",
    "timeout_s",
    type=float,
    default=0.0,
    help="Timeout in seconds when waiting synchronously (0 = no wall-clock limit)",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def employee_invoke(
    member_post_id: str,
    query_or_task: str,
    requested_asset_id: str | None,
    caller_context_id: str,
    dry_run: bool,
    force_spawn: bool,
    wait_for_answer: bool,
    force_async: bool,
    callback_session_id: str | None,
    timeout_s: float,
    as_json: bool,
) -> None:
    """Invoke a domain employee guarded by the `invoke_domain_employee` kinetic contract."""
    from frago.session.async_dispatch import (
        resolve_caller_session_id,
        should_dispatch_employee_async,
    )

    svc = EmployeeOntologyService()
    in_pytest = bool(os.environ.get("PYTEST_CURRENT_TEST"))
    caller_sid = resolve_caller_session_id(callback_session_id)
    launcher = None
    if not dry_run:
        if should_dispatch_employee_async(
            caller_sid,
            wait_for_answer=wait_for_answer,
            force_async=force_async,
            dry_run=dry_run,
            force_spawn=force_spawn,
            explicit_caller_sid=callback_session_id,
        ):
            assert caller_sid is not None
            effective_caller_ctx = (
                caller_context_id
                if caller_context_id != "cli:owner"
                else f"session:{caller_sid}"
            )
            launcher = lambda rec, q: _dispatch_employee_async_turn(  # noqa: E731
                rec,
                q,
                mode="invoke",
                caller_session_id=caller_sid,
                caller_context_id=effective_caller_ctx,
                timeout_s=timeout_s,
            )
        elif wait_for_answer or (not in_pytest and not force_spawn):
            launcher = lambda rec, q: _execute_employee_sync_turn(  # noqa: E731
                rec, q, caller_context_id=caller_context_id, timeout_s=timeout_s
            )
        elif force_spawn:
            launcher = _launch_employee_session
    try:
        receipt = svc.invoke(
            member_post_id,
            query_or_task,
            caller_context_id=caller_context_id,
            requested_asset_id=requested_asset_id,
            session_launcher=launcher,
        )
    except (ValueError, KeyError, ContractViolationError) as exc:
        raise click.ClickException(str(exc)) from None
    except Exception as exc:  # noqa: BLE001 - 启动代理会话失败时翻转成命令行错误
        raise click.ClickException(str(exc)) from None

    if receipt.get("error"):
        raise click.ClickException(str(receipt["error"]))

    sid_display = receipt.get("session_id") or receipt.get("handle")
    _maybe_record_schedule_session(sid_display)

    if as_json:
        click.echo(json.dumps(receipt, ensure_ascii=False, indent=2))
        return
    if receipt.get("status") == "dispatched":
        click.echo(receipt["text"])
        return
    sid_display = receipt.get("session_id") or receipt.get("handle")
    click.echo(
        f"[{receipt['status']}] {receipt['role_id']} (session={sid_display}): {receipt['answer_summary']}"
    )
    if receipt.get("is_completed") is False and receipt.get("notice"):
        click.echo(str(receipt["notice"]))


@employee_group.command(name="ask", cls=AgentFriendlyCommand)
@click.argument("member_post_id")
@click.argument("question")
@click.option(
    "--asset",
    "requested_asset_id",
    default=None,
    help="Target asset within the employee's territory (e.g. domain:architecture)",
)
@click.option(
    "--caller",
    "caller_context_id",
    default="employee:peer",
    show_default=True,
    help="Caller employee or session identifier",
)
@click.option(
    "--wait",
    "wait_for_answer",
    is_flag=True,
    help="Synchronously wait for the target employee's real conclusion text",
)
@click.option(
    "--async",
    "force_async",
    is_flag=True,
    help="Non-blocking async dispatch with automatic callback into caller session stream",
)
@click.option(
    "--callback-session",
    "callback_session_id",
    default=None,
    help="Explicit caller session ID to receive the async completion callback",
)
@click.option(
    "--timeout",
    "timeout_s",
    type=float,
    default=0.0,
    help="Timeout in seconds (0 = no wall-clock limit)",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def employee_ask(
    member_post_id: str,
    question: str,
    requested_asset_id: str | None,
    caller_context_id: str,
    wait_for_answer: bool,
    force_async: bool,
    callback_session_id: str | None,
    timeout_s: float,
    as_json: bool,
) -> None:
    """向同侪领域员工发起协查提问（在会话内默认非阻塞派发并自动回投结果至当前会话流，加 `--wait` 转为同步等待）。"""
    from frago.session.async_dispatch import (
        resolve_caller_session_id,
        should_dispatch_employee_async,
    )

    svc = EmployeeOntologyService()
    caller_sid = resolve_caller_session_id(callback_session_id)
    if should_dispatch_employee_async(
        caller_sid,
        wait_for_answer=wait_for_answer,
        force_async=force_async,
        dry_run=False,
        force_spawn=False,
        explicit_caller_sid=callback_session_id,
    ):
        assert caller_sid is not None
        effective_caller_ctx = (
            caller_context_id
            if caller_context_id != "employee:peer"
            else f"session:{caller_sid}"
        )
        launcher = lambda rec, q: _dispatch_employee_async_turn(  # noqa: E731
            rec,
            q,
            mode="ask",
            caller_session_id=caller_sid,
            caller_context_id=effective_caller_ctx,
            timeout_s=timeout_s,
        )
    else:
        launcher = lambda rec, q: _execute_employee_sync_turn(  # noqa: E731
            rec, q, caller_context_id=caller_context_id, timeout_s=timeout_s
        )
    try:
        receipt = svc.invoke(
            member_post_id,
            question,
            caller_context_id=caller_context_id,
            requested_asset_id=requested_asset_id,
            session_launcher=launcher,
        )
    except (ValueError, KeyError, ContractViolationError) as exc:
        raise click.ClickException(str(exc)) from None
    except Exception as exc:  # noqa: BLE001
        raise click.ClickException(str(exc)) from None

    if receipt.get("error"):
        raise click.ClickException(str(receipt["error"]))

    sid_display = receipt.get("session_id") or receipt.get("handle")
    _maybe_record_schedule_session(sid_display)

    if as_json:
        click.echo(json.dumps(receipt, ensure_ascii=False, indent=2))
        return
    if receipt.get("status") == "dispatched":
        click.echo(receipt["text"])
        return
    sid_display = receipt.get("session_id") or receipt.get("handle")
    click.echo(f"[{receipt['status']}] {member_post_id} (session={sid_display})")
    click.echo("-" * 72)
    click.echo(receipt.get("text") or receipt["answer_summary"])


@employee_group.command(name="govern", cls=AgentFriendlyCommand)
@click.argument("member_post_id")
@click.option(
    "--kind",
    "asset_kind",
    type=_ASSET_KIND_CHOICE,
    required=True,
    help="Kind of asset being governed",
)
@click.option(
    "--target",
    "target_asset_id",
    required=True,
    help="Identifier of the target asset",
)
@click.option(
    "--op",
    "governance_op",
    type=_GOVERN_OP_CHOICE,
    required=True,
    help="Governance operation to perform",
)
@click.option(
    "--receipt",
    "human_decision_receipt_text",
    default=None,
    help="HumanDecisionReceipt text (【answer】...) required for out-of-territory or irreversible ops",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def employee_govern(
    member_post_id: str,
    asset_kind: str,
    target_asset_id: str,
    governance_op: str,
    human_decision_receipt_text: str | None,
    as_json: bool,
) -> None:
    """Govern a territory asset guarded by the `govern_employee_domain_assets` kinetic contract."""
    svc = EmployeeOntologyService()
    try:
        receipt = svc.govern(
            member_post_id,
            asset_kind=asset_kind,
            target_asset_id=target_asset_id,
            governance_op=governance_op,
            human_decision_receipt_text=human_decision_receipt_text,
        )
    except (ValueError, KeyError, ContractViolationError) as exc:
        raise click.ClickException(str(exc)) from None

    if as_json:
        click.echo(json.dumps(receipt, ensure_ascii=False, indent=2))
        return
    click.echo(
        f"[{receipt['status']}] {receipt['member_post_id']} -> {receipt['governance_op']} on {receipt['target_asset_id']} ({receipt['process_id']})"
    )


@employee_group.command(name="context", cls=AgentFriendlyCommand)
@click.argument("member_post_id")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def employee_context(member_post_id: str, as_json: bool) -> None:
    """Print the business context block this post injects into a new conversation's first message."""
    svc = EmployeeOntologyService()
    try:
        block = svc.build_business_context_block(member_post_id)
    except (KeyError, ValueError) as exc:
        raise click.ClickException(str(exc)) from None
    if as_json:
        click.echo(
            json.dumps(
                {"member_post_id": member_post_id, "business_context_block": block},
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    click.echo(block)


@employee_group.command(name="data", cls=AgentFriendlyCommand)
@click.argument("member_post_id")
@click.option(
    "--add",
    "add_folder",
    default=None,
    help="Create/register one archive folder under the post's first DataSlot",
)
@click.option(
    "--slot",
    "slot_path",
    default=None,
    help="DataSlot to add into (defaults to the post's first slot)",
)
@click.option("--summary", default="", help="One-line summary written into the folder's notebook.md")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def employee_data(
    member_post_id: str,
    add_folder: str | None,
    slot_path: str | None,
    summary: str,
    as_json: bool,
) -> None:
    """Inspect, or add into, the ~/.frago/data directories this post manages."""
    svc = EmployeeOntologyService()
    try:
        if add_folder:
            payload: dict[str, Any] = svc.register_data_entry(
                member_post_id,
                add_folder,
                summary=summary,
                slot_path=slot_path,
            )
        else:
            payload = svc.inspect_managed_data(member_post_id)
    except (KeyError, ValueError, ContractViolationError) as exc:
        raise click.ClickException(str(exc)) from None

    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if add_folder:
        click.echo(f"Registered {payload['folder_name']} -> {payload['entry_path']}")
        return
    slots = payload["data_slots"]
    if not slots:
        click.echo(f"No DataSlot bound to '{member_post_id}'.")
        return
    for slot in slots:
        if not slot["exists"]:
            click.echo(f"{slot['slot_path']}  (missing)")
            continue
        click.echo(f"{slot['slot_path']}  ({slot['total_count']} entries)")
        for entry in slot["entries"]:
            summary_text = entry["summary"] or "-"
            click.echo(
                f"  {entry['name']}  — {summary_text} ({entry['file_count']} files)"
            )


@employee_group.command(name="rm", cls=AgentFriendlyCommand)
@click.argument("member_post_id")
def employee_rm(member_post_id: str) -> None:
    """Remove an employee post definition, its companion ledger, and its ledger sync schedule."""
    try:
        existing = get_post(member_post_id)
        schedule_ids = list(existing.schedule_ids) if existing else []
        removed = delete_post(member_post_id)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from None
    if not removed:
        raise click.ClickException(f"Employee post '{member_post_id}' not found.")

    if (
        not os.environ.get("PYTEST_CURRENT_TEST")
        or os.environ.get("FRAGO_EMPLOYEE_AUTO_SCHEDULE") == "1"
    ):
        try:
            remove_schedule, list_schedules = _scheduler_remove_hooks()
            EmployeeOntologyService().remove_ledger_schedule(
                member_post_id,
                schedule_ids=schedule_ids,
                remove_schedule=remove_schedule,
                list_schedules=list_schedules,
            )
        except Exception:  # noqa: BLE001 - 排程清理异常不阻断岗位删除
            pass

    click.echo(f"Removed employee post '{member_post_id}'.")


def _scheduler_hooks() -> tuple[Any, Any]:
    """调度器的两个口：列现有任务、加一条新任务。

    ``frago.employee`` 是领域层，不许 import 服务端（有用例拿 AST 查着这一条）。所以
    「写进 schedules.json」这件事由 CLI 这一层把调度器接进去，而不是让巡检模块自己去
    读写那份文件——那份文件有它自己的字段约定与每一轮的重读逻辑，两边各写一份迟早对不上账。
    """
    from frago.server.services.scheduler_service import SchedulerService

    service = SchedulerService.get_instance()
    return service.add_schedule, service.list_schedules


def _scheduler_remove_hooks() -> tuple[Any, Any]:
    """调度器的删与列两个口：删员工时顺手把它的每日账本巡检排程也清掉。"""
    from frago.server.services.scheduler_service import SchedulerService

    service = SchedulerService.get_instance()
    return service.remove_schedule, service.list_schedules


@employee_group.command(name="sync-ledger", cls=AgentFriendlyCommand)
@click.argument("member_post_id")
@click.option(
    "--full",
    "full_rescan",
    is_flag=True,
    help="丢掉游标重扫一遍（改过岗位职责、想重新认领时用）",
)
@click.option(
    "--no-schedule",
    "skip_schedule",
    is_flag=True,
    help="只记账，不顺手注册每日巡检排程",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def employee_sync_ledger(
    member_post_id: str,
    full_rescan: bool,
    skip_schedule: bool,
    as_json: bool,
) -> None:
    """对员工执行一次主动资源巡检：在 ~/.frago 下认领相关资源并增量入账。

    巡检扫四处：``data/``（数据目录）、``recipes/``（配方）、``books/``（知识域）、
    ``sessions/``（会话）。已记过且指纹未变的资源直接跳过，所以第二次跑通常是「新增 0」。
    """
    svc = EmployeeOntologyService()
    try:
        result = svc.sync_ledger(member_post_id, full_rescan=full_rescan)
    except (KeyError, ValueError) as exc:
        raise click.ClickException(str(exc)) from None

    if not skip_schedule:
        try:
            add_schedule, list_schedules = _scheduler_hooks()
            result["schedule"] = svc.ensure_ledger_schedule(
                member_post_id,
                add_schedule=add_schedule,
                list_schedules=list_schedules,
            )
        except Exception as exc:  # noqa: BLE001 - 排程接不上不该让记账白跑
            result["schedule"] = {"created": False, "reason": f"排程未接入：{exc}"}

    if as_json:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return

    counts = result["counts"]
    click.echo(f"账本：{result['ledger_path']}")
    click.echo(
        f"本轮新增：数据目录 {result['new_data_entries']}、配方 {result['new_recipes']}、"
        f"知识域 {result['new_domains']}、会话 {result['new_sessions']}"
    )
    click.echo(
        f"词条：词汇 +{counts.get('glossary_added', 0)}/更新 {counts.get('glossary_updated', 0)}；"
        f"意图 +{counts.get('intent_added', 0)}/更新 {counts.get('intent_updated', 0)}；"
        f"事项 +{counts.get('topics_added', 0)}/更新 {counts.get('topics_updated', 0)}"
    )
    totals = result["totals"]
    click.echo(
        f"账本现有：词汇 {totals['glossary']}、意图 {totals['intent_playbooks']}、"
        f"活跃事项 {totals['active_topics']}；认领槽位 {totals['claimed_slots']}、"
        f"配方 {totals['claimed_recipes']}、知识域 {totals['claimed_domains']}、"
        f"会话 {totals['matched_sessions']}"
    )
    click.echo(f"游标：会话同步至 {result['cursor']['sessions_through'] or '（未记录）'}")
    schedule = result.get("schedule") or {}
    if schedule.get("schedule_id"):
        verb = "已注册" if schedule.get("created") else "已存在"
        click.echo(f"每日巡检排程{verb}：{schedule['schedule_id']}（cron {schedule.get('cron')}）")
    elif schedule.get("reason"):
        click.echo(f"每日巡检排程未注册：{schedule['reason']}")


@employee_group.command(name="ledger", cls=AgentFriendlyCommand)
@click.argument("member_post_id")
@click.option(
    "--full",
    "full_body",
    is_flag=True,
    help="连条目正文一起打印（默认只给摘要与游标）",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def employee_ledger(member_post_id: str, full_body: bool, as_json: bool) -> None:
    """查看员工的账本内容与游标状态。"""
    try:
        record = get_post(member_post_id)
        ledger = load_ledger(member_post_id)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from None
    if record is None:
        raise click.ClickException(f"Employee post '{member_post_id}' does not exist.")
    if ledger is None:
        raise click.ClickException(
            f"员工 '{member_post_id}' 还没有账本；先跑 `frago employee sync-ledger {member_post_id}`。"
        )

    if as_json:
        payload = ledger.to_dict() if full_body else ledger_summary(ledger)
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    summary = ledger_summary(ledger)
    click.echo(f"员工：{ledger.member_post_id}（账本更新于 {ledger.updated_at}）")
    click.echo(f"职责锚点：{ledger.work_scope_anchor[:80] or '（未记录）'}")
    cursor = summary["cursor"]
    click.echo(
        f"游标：会话同步至 {cursor['sessions_through'] or '（未记录）'}；"
        f"已处理会话 {cursor['processed_session_count']}、数据目录 "
        f"{cursor['processed_data_entry_count']}、配方 {cursor['recipe_digest_count']}、"
        f"知识域 {cursor['domain_digest_count']}"
    )
    claimed = summary["claimed_resources"]
    click.echo(f"认领槽位：{', '.join(claimed['data_slots']) or '-'}")
    click.echo(
        f"认领配方 {claimed['recipe_count']}、知识域 {claimed['knowledge_domain_count']}、"
        f"相关会话 {claimed['matched_session_count']}"
    )
    if full_body:
        for label, entries in (
            ("词汇与隐含语义", ledger.glossary),
            ("意图与默认动作", ledger.intent_playbooks),
            ("活跃事项", ledger.active_topics),
        ):
            click.echo("")
            click.echo(f"【{label}】")
            for entry in entries:
                click.echo(f"  {json.dumps(entry, ensure_ascii=False)}")
