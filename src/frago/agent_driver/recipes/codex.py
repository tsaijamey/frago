"""codex (OpenAI Codex CLI) recipe —— Phase 1 占位。

首版不做 codex 端到端打通（认证墙处理后补）。本占位的核心价值是：未登录时
不静默挂起，而是经 ``needs_input_signal`` 命中 401/认证墙，把本轮判为 needs_input
并提示登录。launch/ready/submit/done/extract 先按 codex TUI 的合理默认填，待认证
打通后在 Phase 4 校准。
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

_READY = PaneMatcher(name="codex-ready", pattern=r"(?i)(?:codex|>\s)")
_DONE = PaneMatcher(name="codex-done", pattern=r"(?m)^\s*(?:codex)?\s*>\s*$")
# 认证墙：未登录 / token 过期 / 401。命中即 needs_input，不静默挂起。
_AUTH_WALL = PaneMatcher(
    name="codex-auth-wall",
    pattern=r"(?i)(401|unauthorized|not\s+logged\s+in|sign\s+in|please\s+login|authentication)",
)

_CHROME_LINE = re.compile(r"^\s*(?:[╭╮╯╰│─┌┐└┘├┤┬┴┼]|>\s*$|codex\s*$)")


def _launch(_ctx: LaunchCtx) -> str:
    return "codex"


def _submit(session: TmuxAgentSession, prompt: str) -> None:
    session.send_text(prompt)
    session.send_keys("Enter")


def _extract(delta: str) -> str:
    lines = [ln for ln in delta.splitlines() if not _CHROME_LINE.match(ln)]
    return "\n".join(ln.strip() for ln in lines).strip()


register_recipe(
    AgentRecipe(
        agent_type="codex",
        launch_command=_launch,
        ready_signal=_READY,
        submit=_submit,
        done_signal=_DONE,
        extract=_extract,
        exception_handlers=[],
        needs_input_signal=_AUTH_WALL,
    )
)
