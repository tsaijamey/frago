"""会话可调用的前端交互组件生成工具（``frago app ask``）。

把原本由模型在回复末尾手写 ``answer-needed-by-human`` YAML 代码块的做法，收敛为确定性的
CLI 工具调用：

1. **按组件类型分子命令**：``single-choice``、``multi-choice``、``text-answer``、
   ``choice-and-text`` 四种交互组件各为一拍子命令。
2. **参数错当场拦下，只回当前组件的正确用例**：缺必填项、选项格式不对、跨组件混用标记、
   或传了不存在的参数名（如 ``--title``、``--questions``），直接以非零退出码报错，并只附上
   当前所调那一种组件类型的 ``[Fix]`` 正确调用示例，杜绝带病输出流向前端。
3. **输出结构化 UI 组件数据**：校验通过后向 stdout 输出带 ``frago_ui_component`` 标识的
   JSON 数据包，前端工作台据此判断并直接渲染对应交互组件。
"""

from __future__ import annotations

import difflib
import json
from typing import Any

import click
from click import Context

from .agent_friendly import BusinessError, render_fix_lines

UI_COMPONENT_MARKER = "decision-card"

COMPONENT_TYPES = (
    "single-choice",
    "multi-choice",
    "text-answer",
    "choice-and-text",
)

COMPONENT_SUMMARY: dict[str, str] = {
    "single-choice": "单选交互卡：用户从多个选项里点一个即作答（可标推荐项与不可撤回项）",
    "multi-choice": "多选交互卡：用户勾选一个或多个选项后确认作答",
    "text-answer": "文本输入卡：用户打字作答（可附预填草稿 --draft 或可点建议 --suggestion）",
    "choice-and-text": "选加写组合卡：用户可点选选项、打字补充，或两者同时提交（可配 --multi 多选）",
}

COMPONENT_EXAMPLES: dict[str, list[str]] = {
    "single-choice": [
        (
            'frago app ask single-choice '
            '--question "SQL 模板应当绑定哪个物理表名？" '
            '--why "rtm_data 在 SIT 环境已有 98 家客户数据，立即可用" '
            '--option "A|绑定 rtm_data|直接查询 commercial_sit.public.rtm_data" '
            '--option "B|兼容双表名|默认查 rtm_data 并预留切换配置" '
            '--recommended A'
        ),
        (
            'frago app ask single-choice '
            '--question "1.4.111 要发到 PyPI 吗？" '
            '--option "A|发布|打 v1.4.111 tag 并上传 PyPI，发出去收不回" '
            '--option "B|先不发|改动留在 main，不打 tag" '
            '--recommended A --irreversible A'
        ),
    ],
    "multi-choice": [
        (
            'frago app ask multi-choice '
            '--question "本次需要同步更新哪些环境配置？" '
            '--why "本地单测已通过，可按需选择同步范围" '
            '--option "A|写入 SIT Admin DB|更新 SIT 环境技能配置表" '
            '--option "B|抽测 5 类典型客户|跑 98 家真实样本抽样验证" '
            '--recommended A'
        ),
    ],
    "text-answer": [
        (
            'frago app ask text-answer '
            '--question "请提供本次归档导出文件的命名后缀" '
            '--suggestion "2026Q3_rtm_summary" '
            '--suggestion "sit_verified_v1"'
        ),
        (
            'frago app ask text-answer '
            '--question "请确认或修改下面这段将写入变更说明的文案" '
            '--draft "本次重构对齐 SIT rtm_data 表结构，新增可选 bg 过滤参数。"'
        ),
    ],
    "choice-and-text": [
        (
            'frago app ask choice-and-text '
            '--question "本次需要执行到哪一步？（可点选并在下方补充特殊要求）" '
            '--why "推荐一步到位完成 SIT 抽样验证" '
            '--option "A|改代码 + 跑单测 + SIT 抽样验证|重构本地逻辑并写入 SIT Admin DB 抽测" '
            '--option "B|仅完成本地重构与单测|只改本地仓库与测试，不写 SIT 库" '
            '--recommended A'
        ),
    ],
}


def _overview_fixes() -> list[str]:
    """未指定或指定了错误的组件类型时，返回 4 种组件的简要入口示例。"""
    return [
        f'{t}（{COMPONENT_SUMMARY[t]}）:\n      {COMPONENT_EXAMPLES[t][0]}'
        for t in COMPONENT_TYPES
    ]


class AskGroup(click.Group):
    """按组件类型分流的命令组：缺子命令或写错子命令名时直接报非零退出码并给 4 种组件入口。"""

    def resolve_command(
        self, ctx: Context, args: list[str]
    ) -> tuple[str | None, click.Command | None, list[str]]:
        cmd_name = args[0] if args else None
        if cmd_name:
            cmd = self.get_command(ctx, cmd_name)
            if cmd is None and not ctx.resilient_parsing:
                matches = difflib.get_close_matches(cmd_name, COMPONENT_TYPES, n=2, cutoff=0.4)
                hint = f"（你是不是想调：{', '.join(matches)}？）" if matches else ""
                raise BusinessError(
                    f"未知的交互组件类型 '{cmd_name}'{hint}。"
                    f"可用组件类型只有 4 种：{', '.join(COMPONENT_TYPES)}。",
                    *_overview_fixes(),
                )
        return super().resolve_command(ctx, args)


class AskComponentCommand(click.Command):
    """单个交互组件子命令：任何 Click 解析期异常都转成只含当前组件用例的 Friendly Feedback。"""

    def make_context(
        self,
        info_name: str | None,
        args: list[str],
        parent: Context | None = None,
        **extra: Any,
    ) -> Context:
        try:
            return super().make_context(info_name, args, parent, **extra)
        except click.NoSuchOption as e:
            comp = info_name or self.name or "single-choice"
            examples = COMPONENT_EXAMPLES.get(comp, COMPONENT_EXAMPLES["single-choice"])
            raise BusinessError(
                f"{comp} 组件不存在参数 '{e.option_name}'。"
                f"请按确定性参数传参（如 --question、--option \"KEY|LABEL|EFFECT\"），不要自造字段名。",
                *examples,
            ) from e
        except (click.MissingParameter, click.BadParameter, click.UsageError) as e:
            comp = info_name or self.name or "single-choice"
            examples = COMPONENT_EXAMPLES.get(comp, COMPONENT_EXAMPLES["single-choice"])
            raise BusinessError(
                f"{comp} 组件参数错误：{e.format_message()}",
                *examples,
            ) from e


def _raise_for_component(component_type: str, message: str) -> None:
    """抛出只带当前组件类型正确用例的 BusinessError。"""
    examples = COMPONENT_EXAMPLES.get(component_type, COMPONENT_EXAMPLES["single-choice"])
    raise BusinessError(message, *examples)


def _parse_single_option(
    component_type: str, raw_opt: str, index: int
) -> dict[str, Any]:
    """解析单个 ``--option`` 参数，支持 ``KEY|LABEL|EFFECT`` 或 JSON 字符串。"""
    text = (raw_opt or "").strip()
    if not text:
        _raise_for_component(
            component_type,
            f"第 {index} 个 --option 为空。格式必须为 \"KEY|LABEL|EFFECT\"（例如 \"A|发布|打 tag 并上传\"）。",
        )

    if text.startswith("{"):
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as e:
            _raise_for_component(
                component_type,
                f"第 {index} 个 --option 的 JSON 解析失败（{e.msg}）。推荐直接使用 \"KEY|LABEL|EFFECT\" 格式。",
            )
        if not isinstance(obj, dict):
            _raise_for_component(
                component_type,
                f"第 {index} 个 --option 必须是包含 key、label、effect 的对象，或使用 \"KEY|LABEL|EFFECT\" 格式。",
            )
        if "effect" not in obj and "description" in obj:
            _raise_for_component(
                component_type,
                f"第 {index} 个 --option 缺少必填字段 'effect'（检测到传了 'description'，交互卡要求写明点了会发生什么的 'effect'）。"
                f"请改用 --option \"KEY|LABEL|EFFECT\"。",
            )
        key = str(obj.get("key") or "").strip()
        label = str(obj.get("label") or "").strip()
        effect = str(obj.get("effect") or "").strip()
        if not key or not label or not effect:
            _raise_for_component(
                component_type,
                f"第 {index} 个 --option 必须同时包含非空的 key、label、effect（当前收到 key={key!r}, label={label!r}, effect={effect!r}）。",
            )
        return {
            "key": key,
            "label": label,
            "effect": effect,
            "reversible": obj.get("reversible") is not False,
            "recommended": obj.get("recommended") is True,
        }

    parts = [p.strip() for p in text.split("|", 3)]
    if len(parts) < 3 or not parts[0] or not parts[1] or not parts[2]:
        _raise_for_component(
            component_type,
            f"第 {index} 个 --option 格式错误（收到 {raw_opt!r}）。"
            f"必须用竖线分成非空的三段：\"KEY|LABEL|EFFECT\"（键|短名|点了会发生什么）。",
        )
    reversible = True
    recommended = False
    if len(parts) == 4 and parts[3]:
        for raw_flag in parts[3].split(","):
            flag = raw_flag.strip().lower()
            if not flag:
                continue
            if flag in ("recommended", "rec", "recommended=true"):
                recommended = True
            elif flag in ("irreversible", "reversible=false"):
                reversible = False
            elif flag in ("reversible", "reversible=true"):
                reversible = True
            else:
                _raise_for_component(
                    component_type,
                    f"第 {index} 个 --option 含有未知附加标记 {raw_flag.strip()!r}（仅支持 recommended / irreversible，或改用顶层参数 --recommended KEY / --irreversible KEY）。",
                )
    return {
        "key": parts[0],
        "label": parts[1],
        "effect": parts[2],
        "reversible": reversible,
        "recommended": recommended,
    }


def validate_and_build_component(
    *,
    component_type: str,
    question: str | None,
    why: str | None,
    options_raw: tuple[str, ...],
    recommended: tuple[str, ...],
    irreversible: tuple[str, ...],
    draft: str | None,
    suggestions: tuple[str, ...],
    multi: bool,
    from_teammate: bool,
    request: str | None,
    changes: str | None,
) -> dict[str, Any]:
    """按组件类型校验所有输入参数，生成前端 UI 交互组件所需的结构化数据。"""
    if component_type not in COMPONENT_TYPES:
        raise BusinessError(
            f"未知的交互组件类型 '{component_type}'。可用组件类型只有 4 种：{', '.join(COMPONENT_TYPES)}。",
            *_overview_fixes(),
        )

    q = (question or "").strip()
    if not q:
        _raise_for_component(
            component_type,
            f"{component_type} 组件缺少必填参数 --question（必须提供一句话问题，让人不看上文也能懂）。",
        )

    # ── 跨组件专属标记校验 ──────────────────────────────────────────────
    if component_type == "text-answer":
        if options_raw:
            _raise_for_component(
                component_type,
                "text-answer 组件不支持 --option（若要提供可点击的建议词，请改用 --suggestion；若要选项加输入框，请改用 choice-and-text）。",
            )
        if recommended:
            _raise_for_component(
                component_type,
                "text-answer 组件没有选项，不支持 --recommended。",
            )
        if irreversible:
            _raise_for_component(
                component_type,
                "text-answer 组件没有选项，不支持 --irreversible。",
            )
    else:
        if not options_raw:
            _raise_for_component(
                component_type,
                f"{component_type} 组件必须提供 --option（格式为 \"KEY|LABEL|EFFECT\"，至少 1 项）。",
            )

    if draft is not None and component_type not in ("text-answer", "choice-and-text"):
        _raise_for_component(
            component_type,
            f"--draft 仅支持 text-answer 与 choice-and-text 组件，{component_type} 不支持。",
        )

    if suggestions and component_type != "text-answer":
        _raise_for_component(
            component_type,
            f"--suggestion 仅支持 text-answer 组件，{component_type} 不支持（请改用 --option 定义选项）。",
        )

    if multi and component_type != "choice-and-text":
        hint = "若需要多选交互卡，请直接调用 frago ask multi-choice。" if component_type == "single-choice" else ""
        _raise_for_component(
            component_type,
            f"--multi 仅支持 choice-and-text 组件，{component_type} 不支持。{hint}".strip(),
        )

    if not from_teammate and (request is not None or changes is not None):
        _raise_for_component(
            component_type,
            "--request 与 --changes 仅在结对队友请求场景下有效，必须同时传 --from-teammate。",
        )

    # ── 解析并校验选项 ──────────────────────────────────────────────────
    parsed_options: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for idx, raw_opt in enumerate(options_raw, start=1):
        opt = _parse_single_option(component_type, raw_opt, idx)
        if opt["key"] in seen_keys:
            _raise_for_component(
                component_type,
                f"选项 key '{opt['key']}' 重复出现；每个 --option 的 key 必须唯一（如 A、B、C）。",
            )
        seen_keys.add(opt["key"])
        parsed_options.append(opt)

    # ── 校验推荐项与不可撤回标记 ────────────────────────────────────────
    rec_keys = [k.strip() for k in recommended if k and k.strip()]
    for k in rec_keys:
        if k not in seen_keys:
            _raise_for_component(
                component_type,
                f"--recommended 指定的 key '{k}' 不在选项列表中（当前可用 key：{', '.join(o['key'] for o in parsed_options)}）。",
            )
    for opt in parsed_options:
        if opt["key"] in rec_keys:
            opt["recommended"] = True

    total_recommended = sum(1 for o in parsed_options if o["recommended"])
    if total_recommended > 1:
        _raise_for_component(
            component_type,
            f"一张交互卡至多只能标记 1 个推荐项（--recommended），当前标记了 {total_recommended} 个。",
        )

    irr_keys = [k.strip() for k in irreversible if k and k.strip()]
    for k in irr_keys:
        if k not in seen_keys:
            _raise_for_component(
                component_type,
                f"--irreversible 指定的 key '{k}' 不在选项列表中（当前可用 key：{', '.join(o['key'] for o in parsed_options)}）。",
            )
    for opt in parsed_options:
        if opt["key"] in irr_keys:
            opt["reversible"] = False

    clean_suggestions = [s.strip() for s in suggestions if s and s.strip()]
    clean_why = why.strip() if isinstance(why, str) and why.strip() else None
    clean_draft = draft.rstrip("\n") if isinstance(draft, str) else None
    clean_request = request.strip() if from_teammate and isinstance(request, str) and request.strip() else None
    clean_changes = changes.strip() if from_teammate and isinstance(changes, str) and changes.strip() else None

    data: dict[str, Any] = {
        "type": component_type,
        "question": q,
    }
    if clean_why is not None:
        data["why"] = clean_why
    if component_type != "text-answer":
        data["options"] = parsed_options
    if component_type == "choice-and-text" and multi:
        data["multi"] = True
    if clean_draft is not None:
        data["draft"] = clean_draft
    if component_type == "text-answer" and clean_suggestions:
        data["suggestions"] = clean_suggestions
    if from_teammate:
        data["from"] = "teammate"
        if clean_request is not None:
            data["request"] = clean_request
        if clean_changes is not None:
            data["changes"] = clean_changes

    return {
        "frago_ui_component": UI_COMPONENT_MARKER,
        "component_type": component_type,
        "data": data,
        "next_action": (
            "前端交互组件数据已生成，WebUI 会将该交互卡片自动挂载到本轮最终收尾回复（Stop 消息）的正文最下方渲染；"
            "请在收尾回复中正常陈述结论并引导用户在下方卡片点选，无需再手写 answer-needed-by-human 代码块。"
        ),
    }


def _common_component_options(func: Any) -> Any:
    """为四个组件子命令挂载统一的确定性参数选项，在业务层按组件类型精准报错。"""
    decorators = [
        click.option(
            "-q",
            "--question",
            default=None,
            help="必填：一句话问题，让人不看上文也能懂。",
        ),
        click.option(
            "-w",
            "--why",
            default=None,
            help="选填：推荐理由或背景依据。",
        ),
        click.option(
            "-o",
            "--option",
            "options_raw",
            multiple=True,
            help='选项（可多次传入），格式为 "KEY|LABEL|EFFECT"，例如 "A|发布|打 tag 并上传 PyPI"。',
        ),
        click.option(
            "--recommended",
            multiple=True,
            help="选填：推荐选项的 key（至多指定 1 个，如 --recommended A）。",
        ),
        click.option(
            "--irreversible",
            multiple=True,
            help="选填：不可撤回选项的 key（可多次传入，如 --irreversible A）。",
        ),
        click.option(
            "--draft",
            default=None,
            help="选填（仅 text-answer / choice-and-text）：预填的可编辑草稿文字。",
        ),
        click.option(
            "-s",
            "--suggestion",
            "suggestions",
            multiple=True,
            help="选填（仅 text-answer）：可点击填入输入框的建议答案（可多次传入）。",
        ),
        click.option(
            "--multi",
            is_flag=True,
            default=False,
            help="选填（仅 choice-and-text）：将选项改为可多选勾选框。",
        ),
        click.option(
            "--from-teammate",
            is_flag=True,
            default=False,
            help="选填：标识这是结对队友经中继转来的请求。",
        ),
        click.option(
            "--request",
            default=None,
            help="选填（需配 --from-teammate）：队友原话。",
        ),
        click.option(
            "--changes",
            default=None,
            help="选填（需配 --from-teammate）：会改本机什么。",
        ),
    ]
    for dec in reversed(decorators):
        func = dec(func)
    return func


def _make_subcommand(component_type: str, short_help: str) -> click.Command:
    @click.command(
        name=component_type,
        cls=AskComponentCommand,
        short_help=short_help,
        help=f"{short_help}\n\n正确调用示例:\n"
        + "\n".join(f"  {ex}" for ex in COMPONENT_EXAMPLES[component_type]),
    )
    @_common_component_options
    def _cmd(
        question: str | None,
        why: str | None,
        options_raw: tuple[str, ...],
        recommended: tuple[str, ...],
        irreversible: tuple[str, ...],
        draft: str | None,
        suggestions: tuple[str, ...],
        multi: bool,
        from_teammate: bool,
        request: str | None,
        changes: str | None,
    ) -> None:
        payload = validate_and_build_component(
            component_type=component_type,
            question=question,
            why=why,
            options_raw=options_raw,
            recommended=recommended,
            irreversible=irreversible,
            draft=draft,
            suggestions=suggestions,
            multi=multi,
            from_teammate=from_teammate,
            request=request,
            changes=changes,
        )
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))

    return _cmd


@click.group(
    name="ask",
    cls=AskGroup,
    invoke_without_command=True,
    short_help="Generate validated WebUI decision card component data",
)
@click.pass_context
def ask_group(ctx: Context) -> None:
    """生成经过严格参数校验的前端 UI 交互组件数据（替代手写 answer-needed-by-human 代码块）。

    必须指定 4 种交互组件子命令之一：single-choice、multi-choice、text-answer、choice-and-text。
    若参数缺失或格式有误，命令会直接返回非零退出码并给出对应组件类型的正确调用示例。
    """
    if ctx.invoked_subcommand is None:
        click.echo(
            "Error: 请指定要生成的交互组件类型（single-choice / multi-choice / text-answer / choice-and-text）。",
            err=True,
        )
        for line in render_fix_lines(_overview_fixes()):
            click.echo(line, err=True)
        ctx.exit(1)


for _comp_type in COMPONENT_TYPES:
    ask_group.add_command(_make_subcommand(_comp_type, COMPONENT_SUMMARY[_comp_type]))
