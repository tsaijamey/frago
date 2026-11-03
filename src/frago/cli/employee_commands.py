"""frago employee — CLI system-call entrypoint for the Employee ontology.

  frago employee list/show/hire/bind/discover/invoke/govern/context/data/sync-ledger/ledger/rm/schema

Thin CLI wrapper over ``frago.employee`` (`store.py` + `ledger.py` + `service.py`), bound to
`CliCommandActionContract` (`frago.employee.invoke`, `frago.employee.govern`,
`frago.employee.discover`) and guarded by `invoke_domain_employee` and
`govern_employee_domain_assets` kinetic contracts.
"""

from __future__ import annotations

import json
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
        )
    except (ValueError, ContractViolationError) as exc:
        raise click.ClickException(str(exc)) from None

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
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def employee_invoke(
    member_post_id: str,
    query_or_task: str,
    requested_asset_id: str | None,
    caller_context_id: str,
    as_json: bool,
) -> None:
    """Invoke a domain employee guarded by the `invoke_domain_employee` kinetic contract."""
    svc = EmployeeOntologyService()
    try:
        receipt = svc.invoke(
            member_post_id,
            query_or_task,
            caller_context_id=caller_context_id,
            requested_asset_id=requested_asset_id,
        )
    except (ValueError, KeyError, ContractViolationError) as exc:
        raise click.ClickException(str(exc)) from None

    if as_json:
        click.echo(json.dumps(receipt, ensure_ascii=False, indent=2))
        return
    click.echo(
        f"[{receipt['status']}] {receipt['role_id']} (session={receipt['session_id']}): {receipt['answer_summary']}"
    )


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
    """Remove an employee post definition."""
    try:
        removed = delete_post(member_post_id)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from None
    if not removed:
        raise click.ClickException(f"Employee post '{member_post_id}' not found.")
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
