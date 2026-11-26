"""``frago app propose`` CLI 非阻塞提案命令（统一决策收件箱上浮原语）。

与交互式阻塞发卡命令 ``frago app ask`` 严格正交：
- 在定时任务（``FRAGO_SESSION_ORIGIN=schedule``）、无人值守（``FRAGO_UNATTENDED=1``）与
  子任务（``FRAGO_AGENT_ROLE=worker``）模式下**默认放行**；
- 将高危/不可逆/超边界待决事项通过本体服务 :class:`DecisionInboxService` 写入受管存储
  （``~/.frago/decision-inbox/`` 或 ``FRAGO_DECISION_INBOX_DIR``），支持同 ``dedup_key``
  原地去重计数与 72h 默认 TTL 保守收口。
"""

from __future__ import annotations

import difflib
import json
import os
from typing import Any

import click
from click import Context

from frago.cli.agent_friendly import AgentFriendlyCommand, BusinessError, render_fix_lines
from frago.cli.ask_commands import KEY_PATTERN, KEY_RULE_HINT, _describe_key
from frago.decision_inbox import (
    DEFAULT_TTL_HOURS,
    DecisionInboxError,
    get_decision_inbox_service,
)

PROPOSE_TYPES = ("single-choice", "multi-choice", "binary", "text-answer")
RISK_LEVELS = ("low", "medium", "high")

PROPOSE_SUMMARY: dict[str, str] = {
    "single-choice": "上浮单选提案至统一决策收件箱（非阻塞）",
    "multi-choice": "上浮多选提案至统一决策收件箱（非阻塞）",
    "binary": "上浮二选一批准/驳回提案至统一决策收件箱（非阻塞）",
    "text-answer": "上浮需主理人批注文字的提案至统一决策收件箱（非阻塞）",
}

PROPOSE_EXAMPLES: dict[str, list[str]] = {
    "single-choice": [
        'frago app propose single-choice -q "发现 3 条过期缓存目录，是否永久清理？" '
        '--dedup-key "cache:cleanup" --risk high --irreversible '
        '-o "A|全部清理|释放 1.2GB 空间" -o "B|暂保留|跳过本次清理" --recommended B '
        '--impact-scope "~/.cache/frago-tmp" --evidence "连续 14 天未访问"',
    ],
    "multi-choice": [
        'frago app propose multi-choice -q "以下哪些外部同步目标需要本轮执行推送？" '
        '--dedup-key "sync:targets" --risk medium '
        '-o "A|Notion|同步本周周报" -o "B|邮件|发送汇总抄送" --recommended A',
    ],
    "binary": [
        'frago app propose binary -q "确认对外发送本周项目周报邮件？" '
        '--dedup-key "weekly:mail" --risk high --irreversible '
        '--recommended reject --impact-scope "收件人 12 位外部客户"',
    ],
    "text-answer": [
        'frago app propose text-answer -q "请确认新客户档案的归档分类标签" '
        '--dedup-key "crm:tag:new" --risk low --draft "重点潜客"',
    ],
}


def _propose_fixes(propose_type: str) -> list[tuple[str, str]]:
    fixes = [("正确调用示例", ex) for ex in PROPOSE_EXAMPLES[propose_type]]
    fixes.append(
        ("查看完整参数说明", f"frago app propose {propose_type} --help")
    )
    return fixes


def _overview_fixes() -> list[tuple[str, str]]:
    return [
        ("单选提案示例", PROPOSE_EXAMPLES["single-choice"][0]),
        ("二选一批准示例", PROPOSE_EXAMPLES["binary"][0]),
        ("多选提案示例", PROPOSE_EXAMPLES["multi-choice"][0]),
        ("文本批注示例", PROPOSE_EXAMPLES["text-answer"][0]),
    ]


def _raise_for_type(propose_type: str, message: str) -> None:
    raise BusinessError(message, *_propose_fixes(propose_type))


def _check_key_shape(propose_type: str, raw_key: str, index: int) -> None:
    if KEY_PATTERN.match(raw_key):
        return
    shown = _describe_key(raw_key)
    if not raw_key:
        reason = "KEY 不能为空"
    elif len(raw_key) > 8:
        reason = f"KEY '{shown}' 有 {len(raw_key)} 个字符，超过 8 个字符的上限"
    elif any(ch.isspace() for ch in raw_key):
        reason = f"KEY '{shown}' 含有空白字符"
    elif any(ch in raw_key for ch in "|·"):
        reason = f"KEY '{shown}' 含有分隔符（| 或 ·）"
    else:
        reason = f"KEY '{shown}' 含有不允许的字符（只允许字母、数字、-、_）"
    _raise_for_type(propose_type, f"第 {index} 个 --option 的 {reason}。{KEY_RULE_HINT}")


def _parse_option(propose_type: str, raw_opt: str, index: int) -> dict[str, Any]:
    text = (raw_opt or "").strip()
    if not text:
        _raise_for_type(
            propose_type,
            f'第 {index} 个 --option 为空。格式必须为 "KEY|LABEL|EFFECT"（例如 "A|批准|执行该操作"）。',
        )

    if text.startswith("{"):
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as exc:
            _raise_for_type(
                propose_type,
                f"第 {index} 个 --option 的 JSON 解析失败（{exc.msg}）。推荐使用 \"KEY|LABEL|EFFECT\" 格式。",
            )
        if not isinstance(obj, dict):
            _raise_for_type(
                propose_type,
                f'第 {index} 个 --option 必须是包含 key、label、effect 的对象，或使用 "KEY|LABEL|EFFECT" 格式。',
            )
        key = str(obj.get("key") or "").strip()
        label = str(obj.get("label") or "").strip()
        effect = str(obj.get("effect") or "").strip()
        if not key or not label or not effect:
            _raise_for_type(
                propose_type,
                f"第 {index} 个 --option 必须同时包含非空的 key、label、effect。",
            )
        parsed_opt: dict[str, Any] = {
            "key": key,
            "label": label,
            "effect": effect,
            "recommended": obj.get("recommended") is True,
        }
        if "reversible" in obj and isinstance(obj.get("reversible"), bool):
            parsed_opt["reversible"] = obj["reversible"]
        return parsed_opt

    parts = [p.strip() for p in text.split("|", 3)]
    if len(parts) < 3 or not parts[0] or not parts[1] or not parts[2]:
        _raise_for_type(
            propose_type,
            f'第 {index} 个 --option 格式错误（收到 {raw_opt!r}），必须为 "KEY|LABEL|EFFECT"。',
        )
    recommended = False
    if len(parts) == 4 and parts[3]:
        for raw_flag in parts[3].split(","):
            flag = raw_flag.strip().lower()
            if not flag:
                continue
            if flag in ("recommended", "rec", "recommended=true"):
                recommended = True
            elif flag in ("irreversible", "reversible", "reversible=false", "reversible=true"):
                # 提案级不可逆请使用顶层 --irreversible 标记；此处兼容跳过
                continue
            else:
                _raise_for_type(
                    propose_type,
                    f"第 {index} 个 --option 含有未知附加标记 {raw_flag.strip()!r}。",
                )
    return {
        "key": parts[0],
        "label": parts[1],
        "effect": parts[2],
        "recommended": recommended,
    }


class ProposeComponentCommand(AgentFriendlyCommand):
    """子命令参数错误时仅返回对应提案类型的正确调用示例。"""

    def format_usage(self, ctx: Context, formatter: click.HelpFormatter) -> None:
        super().format_usage(ctx, formatter)

    def main(self, *args: Any, **kwargs: Any) -> Any:
        try:
            return super().main(*args, **kwargs)
        except click.UsageError as exc:
            fixes = _propose_fixes(self.name) if self.name in PROPOSE_TYPES else _overview_fixes()
            click.echo(f"Error: {exc.format_message()}", err=True)
            for line in render_fix_lines(fixes):
                click.echo(line, err=True)
            sys_exit_code = exc.exit_code or 2
            raise SystemExit(sys_exit_code) from exc


class ProposeGroup(click.Group):
    """非阻塞提案命令组：支持 4 种提案形态，无人值守模式全程放行。"""

    def resolve_command(
        self, ctx: Context, args: list[str]
    ) -> tuple[str | None, click.Command | None, list[str]]:
        cmd_name = args[0] if args else None
        if cmd_name:
            cmd = self.get_command(ctx, cmd_name)
            if cmd is None and not ctx.resilient_parsing:
                matches = difflib.get_close_matches(cmd_name, PROPOSE_TYPES, n=2, cutoff=0.4)
                hint = f"（你是不是想调：{', '.join(matches)}？）" if matches else ""
                raise BusinessError(
                    f"未知的提案类型 '{cmd_name}'{hint}。"
                    f"可用提案类型：{', '.join(PROPOSE_TYPES)}。",
                    *_overview_fixes(),
                )
        return super().resolve_command(ctx, args)


def submit_proposal(
    *,
    propose_type: str,
    question: str | None,
    why: str | None,
    options_raw: tuple[str, ...],
    recommended: str | None,
    risk: str,
    irreversible: bool,
    ttl_hours: float,
    dedup_key: str | None,
    impact_scope: str | None,
    evidence: str | None,
    skip_reason: str | None,
    draft: str | None,
    suggestions: tuple[str, ...],
    session_id: str | None,
    schedule_id: str | None,
    schedule_name: str | None,
    employee_id: str | None,
    source: str | None,
) -> dict[str, Any]:
    """校验参数并调用 :class:`DecisionInboxService` 提交（或去重合并）提案。"""
    if propose_type not in PROPOSE_TYPES:
        raise BusinessError(
            f"未知的提案类型 '{propose_type}'。可用类型：{', '.join(PROPOSE_TYPES)}。",
            *_overview_fixes(),
        )

    q = (question or "").strip()
    if not q:
        _raise_for_type(
            propose_type,
            f"{propose_type} 提案缺少必填参数 --question（必须提供清晰的一句话待决问题）。",
        )

    clean_risk = (risk or "low").strip().lower()
    if clean_risk not in RISK_LEVELS:
        _raise_for_type(
            propose_type,
            f"--risk 只允许 low / medium / high，收到 {risk!r}。",
        )

    if ttl_hours <= 0:
        _raise_for_type(propose_type, f"--ttl-hours 必须大于 0（当前为 {ttl_hours}）。")

    if propose_type == "text-answer":
        if options_raw:
            _raise_for_type(
                propose_type,
                "text-answer 提案不支持 --option（如需选项请改用 single-choice / multi-choice / binary）。",
            )
    elif propose_type in ("single-choice", "multi-choice") and not options_raw:
        _raise_for_type(
            propose_type,
            f'{propose_type} 提案必须至少提供一个 --option（格式："KEY|LABEL|EFFECT"）。',
        )

    parsed_options: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for idx, raw_opt in enumerate(options_raw, start=1):
        opt = _parse_option(propose_type, raw_opt, idx)
        _check_key_shape(propose_type, opt["key"], idx)
        if opt["key"] in seen_keys:
            _raise_for_type(
                propose_type,
                f"选项 key '{opt['key']}' 重复出现；每个 --option 的 key 必须唯一。",
            )
        seen_keys.add(opt["key"])
        parsed_options.append(opt)

    clean_rec = recommended.strip() if isinstance(recommended, str) and recommended.strip() else None
    if clean_rec is not None:
        if parsed_options and clean_rec not in seen_keys:
            _raise_for_type(
                propose_type,
                f"--recommended 指定的 key '{clean_rec}' 不在选项列表中（可用：{', '.join(seen_keys)}）。",
            )
        if propose_type == "binary" and not parsed_options and clean_rec not in ("approve", "reject"):
            _raise_for_type(
                propose_type,
                f"binary 提案未传 --option 时，--recommended 仅允许 approve 或 reject（收到 {clean_rec!r}）。",
            )

    resolved_session_id = (session_id or os.environ.get("FRAGO_SESSION_ID") or "").strip() or None
    resolved_schedule_id = (schedule_id or os.environ.get("FRAGO_SCHEDULE_ID") or "").strip() or None
    resolved_schedule_name = (
        schedule_name or os.environ.get("FRAGO_SCHEDULE_NAME") or ""
    ).strip() or None
    resolved_employee_id = (
        employee_id or os.environ.get("FRAGO_EMPLOYEE_ID") or ""
    ).strip() or None

    resolved_source = (source or "").strip().lower()
    if resolved_source not in ("schedule", "session"):
        if (
            resolved_schedule_id
            or os.environ.get("FRAGO_SESSION_ORIGIN", "").strip() == "schedule"
            or os.environ.get("FRAGO_UNATTENDED", "").strip() == "1"
            or os.environ.get("FRAGO_AGENT_ROLE", "").strip() == "worker"
        ):
            resolved_source = "schedule"
        elif resolved_session_id:
            resolved_source = "session"
        else:
            resolved_source = "schedule"

    clean_suggestions = [s.strip() for s in suggestions if s and s.strip()]
    joined_suggestion = " / ".join(clean_suggestions) if clean_suggestions else None

    try:
        svc = get_decision_inbox_service()
        item = svc.propose(
            question=q,
            action_type=propose_type,
            options=parsed_options or None,
            recommended=clean_rec,
            why=(why or "").strip(),
            skip_reason=(skip_reason or "").strip(),
            impact_scope=(impact_scope or "").strip(),
            evidence=(evidence or "").strip(),
            risk=clean_risk,
            irreversible=bool(irreversible),
            ttl_hours=float(ttl_hours),
            dedup_key=(dedup_key or "").strip() or None,
            source=resolved_source,
            session_id=resolved_session_id,
            schedule_id=resolved_schedule_id,
            schedule_name=resolved_schedule_name,
            employee_id=resolved_employee_id,
            draft=draft.rstrip("\n") if isinstance(draft, str) else None,
            suggestion=joined_suggestion,
        )
    except DecisionInboxError as exc:
        _raise_for_type(propose_type, str(exc))

    return {
        "frago_proposal": True,
        "proposal_id": item["proposal_id"],
        "dedup_key": item["dedup_key"],
        "deduped": bool(item.get("deduped", False)),
        "occurrence_count": int(item.get("occurrence_count", 1)),
        "status": item["status"],
        "action_type": item["action_type"],
        "source": item["source"],
        "risk": item["risk"],
        "irreversible": bool(item["irreversible"]),
        "recommended": item.get("recommended"),
        "ttl_hours": item["ttl_hours"],
        "expires_at": item["expires_at"],
        "next_action": (
            "提案已非阻塞写入统一决策收件箱（#sessions/inbox）。"
            "请安全跳过该待决动作，并在本轮回复中简要说明已上浮待主理人确认后正常结束，无需等待。"
        ),
    }


def _common_propose_options(func: Any) -> Any:
    decorators = [
        click.option("-q", "--question", default=None, help="必填：清晰的一句话待决问题。"),
        click.option("-w", "--why", default=None, help="选填：背景说明或推荐理由。"),
        click.option(
            "-o",
            "--option",
            "options_raw",
            multiple=True,
            help='选项（可多次传入），格式 "KEY|LABEL|EFFECT"；KEY 须为 1–8 位字母数字/-/_。',
        ),
        click.option("--recommended", default=None, help="选填：保守默认推荐项 key（如 B 或 reject）。"),
        click.option(
            "--risk",
            type=click.Choice(["low", "medium", "high"], case_sensitive=False),
            default="low",
            show_default=True,
            help="风险等级（low / medium / high）。",
        ),
        click.option(
            "--irreversible",
            is_flag=True,
            default=False,
            help="标记此提案属于不可逆高危动作（超期时绝不自动执行）。",
        ),
        click.option(
            "--ttl-hours",
            type=float,
            default=DEFAULT_TTL_HOURS,
            show_default=True,
            help="超期保守收口时长（小时）。",
        ),
        click.option(
            "--dedup-key",
            default=None,
            help="确定性去重键；同 key 在活跃期间重复 propose 将原地刷新并累计出现次数。",
        ),
        click.option("--impact-scope", default=None, help="影响范围（目录、记录条数、受影响对象等）。"),
        click.option("--evidence", default=None, help="依据或跳过证据摘要。"),
        click.option("--skip-reason", default=None, help="本次无人值守跳过该动作的原因。"),
        click.option("--draft", default=None, help="选填（仅 text-answer）：预填草稿。"),
        click.option(
            "-s",
            "--suggestion",
            "suggestions",
            multiple=True,
            help="选填（仅 text-answer）：建议批注文本。",
        ),
        click.option("--session-id", default=None, help="关联会话 ID（默认读取 FRAGO_SESSION_ID）。"),
        click.option("--schedule-id", default=None, help="关联定时任务 ID（默认读取 FRAGO_SCHEDULE_ID）。"),
        click.option("--schedule-name", default=None, help="关联定时任务名称（默认读取 FRAGO_SCHEDULE_NAME）。"),
        click.option("--employee-id", default=None, help="关联员工 ID（默认读取 FRAGO_EMPLOYEE_ID）。"),
        click.option(
            "--source",
            type=click.Choice(["schedule", "session"], case_sensitive=False),
            default=None,
            help="提案来源（默认按环境变量自动识别为 schedule 或 session）。",
        ),
    ]
    for dec in reversed(decorators):
        func = dec(func)
    return func


def _make_subcommand(propose_type: str, short_help: str) -> click.Command:
    @click.command(
        name=propose_type,
        cls=ProposeComponentCommand,
        short_help=short_help,
        help=f"{short_help}\n\n正确调用示例:\n"
        + "\n".join(f"  {ex}" for ex in PROPOSE_EXAMPLES[propose_type]),
    )
    @_common_propose_options
    def _cmd(
        question: str | None,
        why: str | None,
        options_raw: tuple[str, ...],
        recommended: str | None,
        risk: str,
        irreversible: bool,
        ttl_hours: float,
        dedup_key: str | None,
        impact_scope: str | None,
        evidence: str | None,
        skip_reason: str | None,
        draft: str | None,
        suggestions: tuple[str, ...],
        session_id: str | None,
        schedule_id: str | None,
        schedule_name: str | None,
        employee_id: str | None,
        source: str | None,
    ) -> None:
        payload = submit_proposal(
            propose_type=propose_type,
            question=question,
            why=why,
            options_raw=options_raw,
            recommended=recommended,
            risk=risk,
            irreversible=irreversible,
            ttl_hours=ttl_hours,
            dedup_key=dedup_key,
            impact_scope=impact_scope,
            evidence=evidence,
            skip_reason=skip_reason,
            draft=draft,
            suggestions=suggestions,
            session_id=session_id,
            schedule_id=schedule_id,
            schedule_name=schedule_name,
            employee_id=employee_id,
            source=source,
        )
        click.echo(json.dumps(payload, ensure_ascii=False))

    return _cmd


@click.group(
    name="propose",
    cls=ProposeGroup,
    invoke_without_command=True,
    short_help="Propose a non-blocking decision item into the unified Decision Inbox",
)
@click.pass_context
def propose_group(ctx: Context) -> None:
    """将待拍板提案非阻塞上浮到统一决策收件箱（无人值守 / 定时任务 / 子任务放行）。"""
    if ctx.invoked_subcommand is None:
        click.echo(
            "Error: 请指定提案类型（single-choice / multi-choice / binary / text-answer）。",
            err=True,
        )
        for line in render_fix_lines(_overview_fixes()):
            click.echo(line, err=True)
        ctx.exit(1)


for _ptype in PROPOSE_TYPES:
    propose_group.add_command(_make_subcommand(_ptype, PROPOSE_SUMMARY[_ptype]))
