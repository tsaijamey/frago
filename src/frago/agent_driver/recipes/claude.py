"""claude (Claude Code) TUI recipe。

claude 的特异性：单 Enter 提交；就绪/完成都以输入框提示符为信号。
extract 擦掉 TUI 边框、侧栏、页脚等视觉 chrome，只留答案文本。
"""

from __future__ import annotations

import re

from frago.agent_driver.recipe import (
    AgentRecipe,
    LaunchCtx,
    PaneMatcher,
    register_recipe,
)
from frago.agent_driver.tmux_session import TmuxAgentSession

# claude TUI 底部输入框提示符（"> " 行 + 边框）。就绪与一轮答完都回到此态。
_PROMPT_BOX = PaneMatcher(name="claude-prompt", pattern=r"(?m)^\s*│?\s*>\s")

# 视觉装饰行：边框字符、侧栏提示、底部快捷键页脚。
_CHROME_LINE = re.compile(
    r"^\s*(?:[╭╮╯╰│─┌┐└┘├┤┬┴┼]|✻|⏵|\?|—\s*for shortcuts|esc to interrupt)",
)


def _launch(_ctx: LaunchCtx) -> str:
    # tmux 后端下 claude 在非交互注入场景需要免去逐次权限确认，否则首条 prompt
    # 会卡在权限弹窗、就绪信号永不出现。LaunchCtx 目前没有可表达跳权限的字段，
    # 直接拼入该 flag。
    return "claude --dangerously-skip-permissions"


def _submit(session: TmuxAgentSession, prompt: str) -> None:
    session.send_text(prompt)
    session.send_keys("Enter")


def _extract(delta: str) -> str:
    lines = [ln for ln in delta.splitlines() if not _CHROME_LINE.match(ln)]
    return "\n".join(ln.strip() for ln in lines).strip()


register_recipe(
    AgentRecipe(
        agent_type="claude",
        launch_command=_launch,
        ready_signal=_PROMPT_BOX,
        submit=_submit,
        done_signal=_PROMPT_BOX,
        extract=_extract,
        exception_handlers=[],
    )
)
