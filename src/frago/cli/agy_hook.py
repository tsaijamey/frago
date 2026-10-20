"""agy（Antigravity CLI）的 hook 方言垫片。

## 它为什么存在

frago 的规则引擎（``frago-core --engine``）说的是 Claude Code 那一套：从 stdin 收一条
JSON，凭 ``hook_event_name`` 判事件，把结论打成 ``hookSpecificOutput``。agy 的
``hooks.json`` 收发的却是另一套——入参 camelCase（``conversationId``、``toolCall.name``），
出参按事件分成 ``injectSteps``、``decision``、``{}`` 三种形状。

两套方言之间不重建引擎（那是 Rust，为一种 agent 去改它，代价与风险都不成比例），而是在
中间放这一层薄垫片：把 agy 的话翻成引擎听得懂的，再把引擎的回答翻回 agy 的形状。垫片
**只搬字段，不重写任何规则**——命中与否仍由引擎里那套规则说了算。

## 三处翻译

1. **信封字段**：``conversationId`` → ``session_id``、``transcriptPath`` → ``transcript_path``、
   ``workspacePaths[0]`` → ``cwd``。PreInvocation 上还要多备两样——本轮用户那句话与前面
   几轮的提要，agy 的载荷里都没有，得回读一次转录（见 :func:`translate_input`）。
2. **工具名与参数键**：引擎的规则写在 Claude Code 的词表里（``Bash`` / ``Read`` / ``Grep``…），
   agy 报的却是 ``run_command`` / ``view_file`` / ``grep_search``。名字不翻，规则一条都命中
   不了（2026-10-14 实测：``tool_name=run_command`` 喂进引擎，rm 那条规则纹丝不动；换成
   ``Bash`` 立刻拦下）。参数键同理，agy 的 shell 命令在 ``args.CommandLine``，引擎认的是
   ``tool_input.command``。
3. **出参**：SessionStart 的 ``additionalContext`` → ``{"injectSteps":[{"systemMessage":
   {"systemMessage":…}}]}``；PreInvocation 的同一份上下文 → ``{"injectSteps":
   [{"ephemeralMessage":…}]}``（每轮一次性，理由见 :func:`translate_output`）；PreToolUse
   的 ``permissionDecision``/``permissionDecisionReason`` → ``{"decision":…,"reason":…}``；
   PostToolUse、Stop 与一切不认识的事件 → ``{}``。
   **PreToolUse 是个例外：它必须给一个 decision，哪怕引擎没意见。** agy 的 PreToolUse
   契约里 ``decision`` 是必填，缺了它 agy 按拒绝处理——引擎没意见时垫片回 ``ask``，把决定
   权交回 agy 自己的权限流程（细节见 :func:`translate_output`）。

## 认识的有五路

agy 有 SessionStart / PreToolUse / PostToolUse / PreInvocation / PostInvocation / Stop 六个
事件，引擎支持 SessionStart / UserPromptSubmit / PreToolUse / PostToolUse / Stop。五路一一
对应（见 :data:`EVENT_MAP`），其中 ``PreInvocation`` ↔ ``UserPromptSubmit`` 是**名字不同、
位置相同**的一对：两边都在"用户提交了、模型还没跑"这一刻触发，也都带注入能力。

**这一路 2026-10-14 才接上，接之前它是漏的。** 当时只把名字完全一样的四个接上了，还在
这里写过一句"``PreInvocation`` 引擎不认——这是降级，不是遗漏"。那句话是错的：引擎认这一路，
它就是 ``UserPromptSubmit``，而轻量 ai 的每轮复核**只挂在这一路上**。漏掉它的那几天，agy
会话里那套判读一次都没跑过，而表面上一切正常（开场有注入、动手有拦截），要不是用户看见
工作台上 Hooks 那一档是 0，没人会发现。

引擎真没有对端的是 ``PostInvocation``——它唯一的作用是强制续跑，引擎没有对应语义。

## 失败时的降级

垫片夹在 agy 与引擎之间，它一出错，规则就静默失效。任何一步失败（stdin 读不动、引擎不在、
引擎吐的不是 JSON）都记日志，并按事件给一个**不改变 agy 行为**的答复：PreToolUse 回
``{"decision":"ask"}``（交回 agy 自己的权限流程），其余回 ``{}``。NEVER 因为垫片坏了而硬放行
一次工具调用——``ask`` 是"我不管，按你的规矩来"，``allow`` 才是"放行"，两者天差地别。
"""

from __future__ import annotations

import contextlib
import json
import logging
import subprocess
import sys
from typing import Any

import click

logger = logging.getLogger(__name__)

#: agy 工具名 → 引擎（Claude Code 词表）工具名。
#:
#: 只收引擎规则真正点名过、或四类基本操作对应的那几个。名字不在表里的一律**原样透传**——
#: 透传至少让"按名字精确匹配"的规则还有机会命中，凭空给一个不认识的名字编一个 Claude Code
#: 名字，只会让规则认错工具、拦错东西。
TOOL_NAME_MAP: dict[str, str] = {
    "run_command": "Bash",
    "view_file": "Read",
    "multimodal_view_file": "Read",
    "write_file": "Write",
    "edit_file": "Edit",
    "grep_search": "Grep",
    "code_search": "Grep",
    "list_dir": "LS",
    "search_web": "WebSearch",
    "read_url": "WebFetch",
}

#: 引擎侧工具名 → {agy 参数键: 引擎参数键}。
#:
#: 引擎的规则读 ``tool_input.command`` 这类 Claude Code 的参数名，而 agy 把 shell 命令放在
#: ``CommandLine``（首字母大写）。表里没有的工具，参数**原样透传**；表里有的，**只搬表里
#: 列出的键**——agy 每个工具都额外塞 ``toolAction`` / ``toolSummary`` 两个给人看的键，它们
#: 不是工具参数，留着只会污染引擎看到的输入。
ARG_KEY_MAP: dict[str, dict[str, str]] = {
    "Bash": {"CommandLine": "command"},
    "Read": {"AbsolutePath": "file_path"},
    "Write": {"AbsolutePath": "file_path", "Content": "content"},
    "Edit": {"AbsolutePath": "file_path"},
    "Grep": {"Query": "pattern"},
    "WebFetch": {"Url": "url"},
}

#: agy 事件 → 引擎事件。**名字不同不等于没有对端**——``PreInvocation`` 就是 agy 那一侧的
#: ``UserPromptSubmit``：两边都在"用户提交了、模型还没跑"这一刻触发，也都带注入能力。
#: 只有 ``PostInvocation`` 是引擎真没有的那一路（它唯一的作用是强制续跑，引擎没有对应
#: 语义）。
EVENT_MAP: dict[str, str] = {
    "SessionStart": "SessionStart",
    "PreInvocation": "UserPromptSubmit",
    "PreToolUse": "PreToolUse",
    "PostToolUse": "PostToolUse",
    "Stop": "Stop",
}

#: 引擎 PreToolUse 的 ``permissionDecision`` → agy 的 ``decision``。
#:
#: ``defer``（暂停等外部集成）在 agy 里没有对端，翻成 ``ask``——最坏是多问用户一次，
#: 比放行安全。
DECISION_MAP: dict[str, str] = {
    "allow": "allow",
    "deny": "deny",
    "ask": "ask",
    "defer": "ask",
}

#: 等引擎回答的上限（秒）。引擎里那些确定性规则答在毫秒级，慢的只有要调模型的那一趟
#: ——轻量 ai 的每轮复核，挂在 UserPromptSubmit 上，也就是 agy 的 PreInvocation。
#: 18 秒是给意外留的余量（hooks.json 那边登记的是 20 秒，留 2 秒把答复写完），超过就
#: 回 ``{}``，绝不把 agy 的会话拖在一条 hook 上。
ENGINE_TIMEOUT_SECONDS = 18


def _translate_args(engine_tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """把 agy 的工具参数翻成引擎认的参数名。"""
    mapping = ARG_KEY_MAP.get(engine_tool)
    if not mapping:
        return dict(args)
    return {mapping[k]: v for k, v in args.items() if k in mapping}


def translate_input(payload: dict[str, Any], event: str) -> dict[str, Any]:
    """agy 的入参 → 引擎的入参。

    ``event`` 来自 ``--event``（agy 的 hooks.json 里逐个事件写死），不指望它在 stdin 里
    ——agy 的 payload 里根本没有事件名字段。

    **事件名要过一遍 :data:`EVENT_MAP`。** 引擎凭 ``hook_event_name`` 去挑该跑哪一套规则，
    喂它 agy 的名字（``PreInvocation``）它会一条都不认识，规则与复核双双静默不跑。
    """
    out: dict[str, Any] = {"hook_event_name": EVENT_MAP.get(event, event)}

    conversation_id = payload.get("conversationId")
    if conversation_id:
        out["session_id"] = conversation_id
    transcript_path = payload.get("transcriptPath")
    if transcript_path:
        out["transcript_path"] = transcript_path
    workspace_paths = payload.get("workspacePaths") or []
    if workspace_paths:
        out["cwd"] = workspace_paths[0]

    if event in ("PreToolUse", "PostToolUse"):
        call = payload.get("toolCall") or {}
        raw_name = call.get("name") or ""
        engine_name = TOOL_NAME_MAP.get(raw_name, raw_name)
        out["tool_name"] = engine_name
        out["tool_input"] = _translate_args(engine_name, call.get("args") or {})
        # PostToolUse 才带 error；引擎拿它判"这一步是成功还是失败"。
        if "error" in payload:
            out["tool_response"] = {"error": payload.get("error") or ""}

    if event == "SessionStart":
        out["source"] = payload.get("source") or "startup"

    if event == "PreInvocation":
        # agy 这一路**不带用户那句话**（它的载荷只有 invocationNum / initialNumSteps 加
        # 几个公共字段），而引擎判"用户到底要什么"正需要它。转录里有——提交先于模型调用
        # 落盘。故这里回读一次转录，把那句话与前面几轮的提要一并递过去（见
        # ``agy_records.review_context``）。
        #
        # **只有本轮的第一次模型调用才递。** agy 的 ``PreInvocation`` 每次调模型都触发
        # （实测一轮 5 次），而引擎的 ``UserPromptSubmit`` 在 claude 那边一轮只触发一次。
        # 从前这一路每次都把 prompt 递过去，于是轻量 ai 的每轮复核跟着每一步跑一遍——
        # 用户看到的就是「每个 agent 步骤都在调用轻量 ai」。
        #
        # 后续步骤什么都不递：引擎的 ``situation`` 因此为空，复核那一趟不跑（省一次模型
        # 调用），而确定性规则照旧由 ``rules::dispatch_with`` 跑完返回，它不依赖这份载荷。
        # prompt 类规则同样只在首步命中，与 claude 那边一轮一次的行为对齐。
        #
        # 读不出来就什么都不加：引擎会退化成"只有规则、没有复核"，而**瞎猜一句喂过去
        # 比不喂坏得多**——复核会照着错的那句话给建议，人还看不出它判错了对象。
        from frago.session.adapters.agy_records import review_context

        prompt, recent, is_first_call = review_context(
            transcript_path, conversation_id if isinstance(conversation_id, str) else None
        )
        if is_first_call:
            if prompt:
                out["prompt"] = prompt
            if recent:
                out["recent_turns"] = recent

    return out


def translate_output(event: str, engine_response: dict[str, Any]) -> dict[str, Any]:
    """引擎的出参 → agy 的出参。

    **PreToolUse 必须给一个 decision，哪怕引擎没意见。** agy 的 PreToolUse 契约里
    ``decision`` 是必填；缺了它 agy 按**拒绝**处理（2026-10-14 实测：垫片回 ``{}``，
    一条无害的 ``echo`` 也被挡下，拒绝理由是空的）。所以引擎没有意见时回 ``ask``——
    把决定权交回 agy 自己的权限流程（该弹窗弹窗、``--dangerously-skip-permissions``
    下照旧自动放行）。回 ``allow`` 是不行的：那等于静默关掉 agy 自己的权限系统。
    """
    specific = (engine_response or {}).get("hookSpecificOutput") or {}

    if event == "SessionStart":
        context = specific.get("additionalContext")
        if not context:
            return {}
        return {"injectSteps": [{"systemMessage": {"systemMessage": context}}]}

    if event == "PreInvocation":
        context = specific.get("additionalContext")
        if not context:
            return {}
        # 用 ``ephemeralMessage`` 而不是 ``systemMessage``：轻量 ai 这一趟说的是**这一轮**
        # 该怎么答，说完就该走。agy 的 ``systemMessage`` 会常驻在对话轨迹里跨轮累积，
        # 每轮一份，十几轮下来就是上万字的污染，而人一句都读不到（它不在回复里）。
        # claude 那边的 UserPromptSubmit 注入同样是每轮一次性的，这里与它对齐。
        return {"injectSteps": [{"ephemeralMessage": context}]}

    if event == "PreToolUse":
        decision = specific.get("permissionDecision")
        out: dict[str, Any] = {
            "decision": DECISION_MAP.get(decision, decision) if decision else "ask"
        }
        # 引擎把"为什么"放在 permissionDecisionReason，把规则全文放在 additionalContext；
        # agy 的 PreToolUse 只有一个 reason 栏，两者都并进它。
        reason = "\n\n".join(
            part
            for part in (
                specific.get("permissionDecisionReason"),
                specific.get("additionalContext"),
            )
            if part
        )
        if reason:
            out["reason"] = reason
        return out

    # PostToolUse / Stop：引擎这两路只回 {}，agy 也只认 {}。
    # 引擎将来若在 PostToolUse 上回 additionalContext，agy 没有承接它的栏位——静默丢弃，
    # 记一条日志，好过假装注入了。
    if specific.get("additionalContext"):
        logger.debug("agy-hook: %s 的 additionalContext 无处安放，丢弃", event)
    return {}


def _call_engine(engine_payload: dict[str, Any]) -> dict[str, Any]:
    """把一条事件喂给 ``frago-core --engine``，取回它的回答。失败回 ``{}``。"""
    from frago.init.hook_binary import get_engine_argv, get_hook_binary_path

    try:
        argv = [get_hook_binary_path(), *get_engine_argv()]
    except Exception:  # noqa: BLE001 — 引擎不在就没人可问，回 {} 让 agy 走默认
        logger.warning("agy-hook: 找不到引擎二进制，本轮无规则", exc_info=True)
        return {}

    try:
        result = subprocess.run(
            argv,
            input=json.dumps(engine_payload),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=ENGINE_TIMEOUT_SECONDS,
        )
    except (subprocess.TimeoutExpired, OSError):
        logger.warning("agy-hook: 引擎没答上来，本轮无规则", exc_info=True)
        return {}

    if result.returncode != 0 or not result.stdout.strip():
        logger.warning("agy-hook: 引擎退出码 %s，本轮无规则", result.returncode)
        return {}

    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError:
        logger.warning("agy-hook: 引擎吐的不是 JSON，本轮无规则", exc_info=True)
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _record_launch_relation(payload: dict[str, Any]) -> None:
    """把「这场 agy 会话是从哪场会话里起来的」记进会话关系账。

    **这是 agy 自建会话唯一能被认出来的时刻。** agy 自己新建的会话（``agy -p`` 那种）
    不经过 frago 的任何一条起会话的路，事后也没有地方能查它属于谁：agy 的转录里没有
    父会话字段，它的 conversations 库里 parent_references 表也是空的（2026-10-16 实测）。
    唯一握得住的是**它起来的那一瞬**——它的进程继承着发起方的环境，发起方若是一场会话，
    那个编号就在环境里（claude 自注入 ``CLAUDE_CODE_SESSION_ID``，内核每条命令带
    ``FRAGO_SESSION_ID``，frago 起的会话由 tmux 那一侧注入 ``FRAGO_SESSION_ID``）。

    认不出父亲、或者认出来的就是本场自己，都不记：前者是人在终端里直接敲的 agy，没有
    派人；后者说明这一场是 frago 起的、身份由自己那一侧声明，父子关系由派活那一刻记。
    """
    child = payload.get("conversationId")
    if not isinstance(child, str) or not child.strip():
        return
    child = child.strip()
    from frago.session.session_origin import parent_from_env, record_relation

    parent = parent_from_env()
    if parent is None or parent == child:
        return
    workspace = payload.get("workspacePaths") or []
    record_relation(
        kind="dispatch",
        child_session_id=child,
        parent_session_id=parent,
        agent_type="agy",
        cwd=workspace[0] if workspace else "",
    )


def run(event: str) -> int:
    """读一条 agy 事件、翻过去、问引擎、翻回来、打在 stdout。永远返回 0。"""
    raw = sys.stdin.read()
    payload: dict[str, Any] | None = None
    if raw.strip():
        try:
            parsed = json.loads(raw)
            payload = parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            logger.warning("agy-hook: stdin 不是 JSON，本轮无规则", exc_info=True)

    if payload is not None and event == "SessionStart":
        with contextlib.suppress(Exception):  # 记账失败不该挡住 hook 的答复
            _record_launch_relation(payload)

    # 读不出事件就按"没有意见"答复，且答复仍要**按事件分形状**——PreToolUse 缺 decision
    # 会被 agy 当拒绝（见 translate_output），所以这里也得走它，不能直接吐 {}。
    engine_response = _call_engine(translate_input(payload, event)) if payload else {}
    click.echo(json.dumps(translate_output(event, engine_response), ensure_ascii=False))
    return 0


@click.command("agy-hook")
@click.option(
    "--event",
    required=True,
    help=(
        "agy 事件名（SessionStart / PreInvocation / PreToolUse / PostToolUse / Stop），"
        "写进 hooks.json 的 command 里。"
    ),
)
def agy_hook(event: str) -> None:
    """agy 生命周期 hook 的垫片——由 agy 的 hooks.json 调用，不由人直接敲。

    agy 在事件发生时把一条 camelCase 的 JSON 喂进 stdin，本命令把它翻成引擎认的形状、
    问过 ``frago-core --engine``、再把回答翻回 agy 的形状打在 stdout 上。
    """
    raise SystemExit(run(event))
