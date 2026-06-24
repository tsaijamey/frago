"""claude (Claude Code) TUI recipe。

claude 的特异性：单 Enter 提交；就绪以输入框提示符为信号。完成判定要兼顾当前
claude（v2.1.x，提示符是 ``❯``）的关键行为——思考期间空输入框 ``❯ `` 持续显示，
spinner 在其上方独立成行。若只认"提示符出现"会在提交后立刻误判完成。故完成条件
收紧为：提示符在 AND pane 不含忙碌标记。
extract 擦掉 TUI 边框、侧栏、页脚等视觉 chrome，只留答案文本。
"""

from __future__ import annotations

import re
import uuid

from frago.agent_driver.recipe import (
    AgentRecipe,
    CompletionVerdict,
    LaunchCtx,
    PaneMatcher,
    register_recipe,
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
    # 同时用确定性 ``--session-id`` 锁定 transcript jsonl 路径，供完成探针定位；
    # 该 id 由 frago session_id 经 uuid5 派生，重开同一 session 复用同一 transcript。
    sid = _claude_session_uuid(ctx.session_id)
    return f"claude --dangerously-skip-permissions --session-id {sid}"


def _completion_probe(session: TmuxAgentSession) -> CompletionVerdict | None:
    """权威完成探针：读 claude 的 session JSONL 判本轮是否答完 + 取最终文本。

    定位不到 transcript（jsonl 尚未生成 / 路径未知）时返回 None，由 driver 当帧
    退回 pane 防抖——保证无 transcript 场景与原读屏行为一致。延迟导入解析核心，
    避免把 server 解析依赖（watchdog 等）拉进 agent_driver 的导入面。
    """
    from frago.server.services.transcript_completion import evaluate_file, locate_transcript

    sid = _claude_session_uuid(session.session_id)
    path = locate_transcript(sid, cwd=session.cwd)
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


register_recipe(
    AgentRecipe(
        agent_type="claude",
        launch_command=_launch,
        ready_signal=_READY_BOX,
        submit=_submit,
        done_signal=_DONE,
        extract=_extract,
        read_answer=_read_answer,
        completion_probe=_completion_probe,
        exception_handlers=[],
    )
)
