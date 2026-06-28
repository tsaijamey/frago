"""claude (Claude Code) TUI driver。

claude 的特异性：单 Enter 提交；就绪以输入框提示符为信号。完成判定要兼顾当前
claude（v2.1.x，提示符是 ``❯``）的关键行为——思考期间空输入框 ``❯ `` 持续显示，
spinner 在其上方独立成行。若只认"提示符出现"会在提交后立刻误判完成。故完成条件
收紧为：提示符在 AND pane 不含忙碌标记。
extract 擦掉 TUI 边框、侧栏、页脚等视觉 chrome，只留答案文本。
"""

from __future__ import annotations

import re
import time
import uuid
from pathlib import Path

from frago.agent_driver.driver import (
    AgentDriver,
    CompletionVerdict,
    LaunchCtx,
    PaneMatcher,
    register_driver,
)
from frago.agent_driver.tmux_session import TmuxAgentSession

# 把 frago 自己的 session_id 确定性映射成一个合法 claude session uuid。launch 用它
# 传 ``--session-id``，探针用它定位 jsonl——两端同一派生，路径在起会话那刻就锁定。
_CLAUDE_SID_NS = uuid.UUID("6f4d2c1a-0b3e-4a5d-8c7b-9e0f1a2b3c4d")


def _claude_session_uuid(frago_session_id: str) -> str:
    return str(uuid.uuid5(_CLAUDE_SID_NS, frago_session_id))

# claude TUI 底部输入框提示符行。当前 claude 用 ``❯``，旧版本用 ``>``，两者都认。
# 一轮答完回到此态。注意：scrollback 里 shell 回显的启动命令行（``❯ claude …``）也
# 命中本式，故仅用于"完成"判定（叠加非忙碌条件兜底），NEVER 单独用于就绪判定。
_PROMPT_BOX = PaneMatcher(name="claude-prompt", pattern=r"(?m)^\s*│?\s*[>❯]\s")

# 就绪信号：claude 输入框**空载**（``❯ `` 后整行无内容）。区别于 shell 回显的
# ``❯ claude --dangerously-skip-permissions``（``❯`` 后有命令文本），避免在 TUI
# 尚未可交互时就误判就绪、过早投喂导致 Enter 被吞、prompt 永不提交。
_READY_BOX = PaneMatcher(name="claude-ready", pattern=r"(?m)^\s*│?\s*[>❯]\s*$")

# 忙碌标记：思考期间 pane 会出现下列之一，三者任一命中即视为"仍在忙"。
#   1. ``esc to interrupt`` —— 可中断提示行。
#   2. 括号内计时 ``(12s`` / ``(running stop hook · 4s`` —— 注意完成后的摘要行
#      形如 ``✻ Cogitated for 5s`` 不带括号，故只认带 ``(`` 的计时，避免误判。
#   3. token 计数 ``↑ 0.3k tokens`` / ``↓ 7 tokens``。
#   4. 以 spinner 字形起头且带省略号 ``…`` 的转轮行（如 ``✽ Propagating…``）；
#      要求 ``…`` 在同一行，规避完成摘要行（无 ``…``）与答案文本的误命中。
_BUSY = re.compile(
    r"esc to interrupt"
    r"|\(\s*\d+(?:\.\d+)?s\b"
    r"|[↑↓]\s*[\d.,]+\s*k?\s*tokens"
    r"|^\s*[✻✽✶✢✳✺✷✸✹✦·*∗•◦⠋⠙⠹⠸⠼⠴⠦⠧][^\n]*…",
    re.MULTILINE,
)

# 视觉装饰行：边框字符、侧栏提示、底部快捷键页脚、完成摘要 spinner 行。
_CHROME_LINE = re.compile(
    r"^\s*(?:[╭╮╯╰│─┌┐└┘├┤┬┴┼]|✻|✽|✶|✢|✳|✺|⏵|\?|—\s*for shortcuts|esc to interrupt)",
)

# 阻断门 needs_input：撞上即判本轮为 needs_input，把"需要你选/确认"投递回 chat，
# 不静默挂到超时。PA 会话两条 claude 启动路径都带 ``--dangerously-skip-permissions``，
# 权限确认菜单本就被跳过，不是靶子。真正还会卡住本轮、要人介入的只剩两类：
#   ① 认证墙 / API 鉴权失败——未登录、token 过期、key 失效、余额不足（参照 codex
#      ``_AUTH_WALL``）。命中即需人去登录/换 key。
#   ② agent 自己抛的编号选择 / 澄清菜单——claude 把可选项渲染成带 ``❯`` 光标的编号
#      行（``❯ 1.`` / ``❯ 2.``）。MUST 不误命中正常空输入框 ``_READY_BOX``（``❯ ``
#      行尾为空）与本轮答案正文：故要求 ``❯`` 后紧跟「数字 + ``.`` 或 ``)``」。
# claude 有 transcript 完成探针，``_ok`` 采信 JSONL 权威信号；菜单/认证墙下本轮
# transcript 不会推进，``_ok`` 为假，needs_input 才得以命中，不会被 pane done 抢先。
_AUTH_WALL_PAT = (
    r"invalid api key|api key.*(?:invalid|expired)|please run\s*/login"
    r"|not\s+logged\s+in|unauthorized|authentication\s+failed"
    r"|credit balance is too low|/login\b|sign\s+in"
)
_SELECT_MENU_PAT = r"^\s*│?\s*❯\s+\d+[.)]\s"
_NEEDS_INPUT = PaneMatcher(
    name="claude-needs-input",
    pattern=rf"(?i:{_AUTH_WALL_PAT})|{_SELECT_MENU_PAT}",
)

# 真空闲判定（spec 20260627 Phase 6）用到的两个独立结构信号——与 ``_BUSY`` 互补：
#   ① spinner/工作转轮：claude 干活时在输入框上方独立成行渲染 spinner 字形 +
#      进行时态动词（``✻ Cogitating…`` / ``✶ Brewing…`` / ``✳ Baking…``）。它的
#      「存在=在忙」。``_BUSY`` 已认带 ``…`` 的转轮行，这里单列一个语义化 matcher
#      供 ``is_truly_idle`` 直接复用，命名表达「spinner 在 = 仍在思考」。
_WORKING = PaneMatcher(
    name="claude-working",
    pattern=r"(?m)^\s*[✻✽✶✢✳✺✷✸✹✦·*∗•◦⠋⠙⠹⠸⠼⠴⠦⠧][^\n]*…",
)
#   ② 后台 shell 仍在跑：claude 把活派给后台 shell（bash run_in_background）时，
#      pane 会出现 ``shell still running`` / ``shells still running`` 提示。它在 =
#      后台 worker 没干完，绝不能当空闲回收 / 插话喂下一条。
_SHELL_RUNNING = re.compile(r"shells?\s+still\s+running", re.IGNORECASE)

# 提交后确认进入忙碌态的最大轮询次数。跨过"提交到开始思考"的极短空窗，避免
# done 检测在空窗里误触（彼时提示符已在、忙碌标记尚未出现）。生产按 session
# 的 poll_interval 真实间隔轮询；单测注入 no-op sleep，N 次瞬间走完。
_BUSY_CONFIRM_POLLS = 24


class _ClaudeDone:
    """claude 完成判定：提示符框在 AND pane 不含忙碌标记。

    driver 主路径只用到 ``.matches(text)``，与 PaneMatcher 鸭子兼容。
    """

    name = "claude-done"

    def matches(self, text: str) -> bool:
        return _PROMPT_BOX.matches(text) and _BUSY.search(text) is None


_DONE = _ClaudeDone()


def _launch(ctx: LaunchCtx) -> str:
    # tmux 后端下 claude 在非交互注入场景需要免去逐次权限确认，否则首条 prompt
    # 会卡在权限弹窗、就绪信号永不出现。LaunchCtx 目前没有可表达跳权限的字段，
    # 直接拼入该 flag。
    if ctx.native_session_id:
        # 续接一个**已存在**的真实 claude 会话（如 WebUI 点开页面上的某会话）：
        # 必须用 ``--resume`` 原样带真实 id——claude 会续上原对话、把回复写回同一个
        # ``<sid>.jsonl``（页面正读的那个）。NEVER 用 ``--session-id``：那是"用此 id
        # 新建会话"，撞上已存在的会话直接 ``Error: Session ID ... is already in use``
        # 并退出，链路断在启动那一刻。
        return f"claude --dangerously-skip-permissions --resume {ctx.session_id}"
    # 非 native：frago 自己的标识经 uuid5 确定性映射成合法 claude 会话 id。
    # 关键分流（spec 20260627 Phase 5）：``--session-id`` 是"用此 id **新建**会话"，
    # 撞上已存在的 ``<sid>.jsonl`` 直接 ``Error: Session ID ... is already in use``
    # 退出（判的是 transcript 文件存在、非活锁）；同 id 换 ``--resume`` 则正常起且
    # 把整段历史载回上下文。重启 / 空闲回收 / token 轮换后同一 conv_key 重新拉起即属
    # 此情形——故按该 sid 的 transcript 是否已存在二分：存在 → ``--resume`` 续接，
    # 不存在 → ``--session-id`` 首次创建。延迟导入定位核心（同 _completion_probe），
    # 避免把 server 解析依赖拉进 agent_driver 导入面。
    from frago.server.services.transcript_completion import locate_transcript

    sid = _claude_session_uuid(ctx.session_id)
    if locate_transcript(sid, cwd=ctx.cwd) is not None:
        return f"claude --dangerously-skip-permissions --resume {sid}"
    return f"claude --dangerously-skip-permissions --session-id {sid}"


def transcript_path_for(session: TmuxAgentSession) -> Path | None:
    """定位该会话的 claude transcript jsonl（探针 / 真空闲判定 / 持续转发器共用）。

    与 ``_launch`` 同一套规则：native 会话原样用真实 id 定位，否则按 uuid5 派生。
    延迟导入解析核心，避免把 server 解析依赖拉进 agent_driver 的导入面。
    """
    from frago.server.services.transcript_completion import locate_transcript

    sid = (
        session.session_id
        if session.native_session_id
        else _claude_session_uuid(session.session_id)
    )
    return locate_transcript(sid, cwd=session.cwd)


def is_truly_idle(
    session: TmuxAgentSession,
    *,
    silence_s: float = 3.0,
    now: float | None = None,
) -> bool:
    """真空闲判定（spec 20260627 Phase 6）：四个结构信号缺一不可。

    真空闲 = ① ready 空输入框出现 + ② 无 spinner/工作转轮 + ③ pane 无 "shell(s)
    still running" + ④ transcript 文件 mtime 已静默 ``silence_s`` 秒。任一不满足
    都视为「仍在干活」（可能后台 worker / 异步续干在跑）：此时 NEVER 喂下一条、
    NEVER 回收会话，否则会插话打断、甚至杀掉后台 worker 丢结果。

    全用结构信号、NEVER 语义判断。``now`` 可注入便于单测；transcript 定位不到时
    跳过 mtime 这一信号（无锚点不阻塞前三信号已成立的空闲判定）。
    """
    pane = session.capture_pane()
    if not _READY_BOX.matches(pane):
        return False
    if _BUSY.search(pane) is not None or _WORKING.matches(pane):
        return False
    if _SHELL_RUNNING.search(pane) is not None:
        return False
    path = transcript_path_for(session)
    if path is not None:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return True
        clock = time.time() if now is None else now
        if clock - mtime < silence_s:
            return False
    return True


def _completion_probe(session: TmuxAgentSession) -> CompletionVerdict | None:
    """权威完成探针：读 claude 的 session JSONL 判本轮是否答完 + 取最终文本。

    定位不到 transcript（jsonl 尚未生成 / 路径未知）时返回 None，由 driver 当帧
    退回 pane 防抖——保证无 transcript 场景与原读屏行为一致。延迟导入解析核心，
    避免把 server 解析依赖（watchdog 等）拉进 agent_driver 的导入面。
    """
    from frago.server.services.transcript_completion import evaluate_file

    path = transcript_path_for(session)
    if path is None:
        return None
    tc = evaluate_file(path)
    return CompletionVerdict(
        done=tc.done,
        text=tc.final_text if tc.done else None,
        marker=tc.last_uuid,
    )


def _submit(session: TmuxAgentSession, prompt: str) -> None:
    session.send_text(prompt)
    session.send_keys("Enter")
    # 确认已进入忙碌态再交还 driver 轮询完成，否则首帧落在提交后空窗里会误判完成。
    # 命中即返回；始终未命中（瞬时回复 / fake runner）则跨过 N 轮后放行。
    for _ in range(_BUSY_CONFIRM_POLLS):
        if _BUSY.search(session.capture_pane()) is not None:
            return
        session._sleep(session._poll_interval_s)


def _extract(delta: str) -> str:
    lines = [ln for ln in delta.splitlines() if not _CHROME_LINE.match(ln)]
    return "\n".join(ln.strip() for ln in lines).strip()


# 提示符回显行（``❯ <prompt>`` / ``> <prompt>``，❯ 后可能是 nbsp）。
_ECHO = re.compile(r"^\s*[>❯][\s ]+(?P<text>\S.*)$")
# 一轮答案与下一轮之间的边界：分隔线 / 空输入框 / 下一条提示符回显。
_BLOCK_END = re.compile(r"^\s*(?:─{5,}|[>❯])")
# claude 答案块的起始 bullet。
_ANSWER_BULLET = re.compile(r"^\s*⏺\s?")


def _read_answer(pane: str, prompt: str) -> str:
    """从完成时可见 pane 抽取"本轮 prompt"对应的答案。

    claude 把每轮答案以 ``⏺`` bullet 渲染在该轮提示符回显（``❯ <prompt>``）下方、
    底部输入框上方。多轮常驻会话里上轮内容仍可见，故按 prompt 回显定位本轮区块，
    取其后、下一边界前的 bullet 文本——保证 delta 语义（只返回本轮新答案）。
    """
    norm = prompt.replace(" ", " ").strip()
    lines = pane.splitlines()
    # 自底向上找最后一次本轮 prompt 的回显行（多轮时锁定最新一轮）。
    start = -1
    for i in range(len(lines) - 1, -1, -1):
        m = _ECHO.match(lines[i])
        if m and m.group("text").replace(" ", " ").strip() == norm:
            start = i
            break
    block = lines[start + 1 :] if start >= 0 else lines
    out: list[str] = []
    for ln in block:
        if _BLOCK_END.match(ln):
            break
        if _CHROME_LINE.match(ln):
            continue
        stripped = _ANSWER_BULLET.sub("", ln).strip()
        if stripped:
            out.append(stripped)
    return "\n".join(out).strip()


register_driver(
    AgentDriver(
        agent_type="claude",
        launch_command=_launch,
        ready_signal=_READY_BOX,
        submit=_submit,
        done_signal=_DONE,
        extract=_extract,
        read_answer=_read_answer,
        completion_probe=_completion_probe,
        needs_input_signal=_NEEDS_INPUT,
        exception_handlers=[],
    )
)
