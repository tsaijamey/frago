"""opencode TUI driver。

实测真实坑（全部进 driver，只在会话首启发生一次）：
- 启动弹 Update 模态 → 先 Esc 关掉。
- send-keys 文本上屏有渲染时序 → 提交前重抓 pane 确认文本进框再发 Enter。
- Enter 要连发两次才提交。
完成信号用 agent 自带的 ``▣ Build · 模型 · Ns`` 页脚，而非纯屏幕静止。
"""

from __future__ import annotations

import re

from frago.agent_driver.driver import (
    AgentDriver,
    ExceptionHandler,
    LaunchCtx,
    PaneMatcher,
    register_driver,
)
from frago.agent_driver.tmux_session import TmuxAgentSession

# 就绪：输入框占位提示。
_READY = PaneMatcher(name="opencode-ready", pattern=r"Ask anything")
# 完成：底部 "▣ Build · <model> · 3.7s" 页脚带耗时。
_DONE = PaneMatcher(name="opencode-done", pattern=r"▣\s*Build\b.*·\s*[\d.]+s")
# 启动期 Update 模态。
_UPDATE_MODAL = PaneMatcher(name="opencode-update", pattern=r"(?i)\bUpdate\b.*available")

_CHROME_LINE = re.compile(
    r"^\s*(?:[╭╮╯╰│─┌┐└┘├┤┬┴┼]|▣\s*Build|>\s*$|Ask anything)",
)


def _launch(_ctx: LaunchCtx) -> str:
    return "opencode"


def _dismiss_update_modal(session: TmuxAgentSession) -> None:
    session.send_keys("Escape")


def _submit(session: TmuxAgentSession, prompt: str) -> None:
    session.send_text(prompt)
    # 重抓确认文本进框（渲染时序），未进框再补发一次文本。
    if prompt.strip() and prompt.strip() not in session.capture_pane():
        session.send_text(prompt)
    # 双 Enter 才提交。
    session.send_keys("Enter")
    session.send_keys("Enter")


def _extract(delta: str) -> str:
    lines = [ln for ln in delta.splitlines() if not _CHROME_LINE.match(ln)]
    return "\n".join(ln.strip() for ln in lines).strip()


register_driver(
    AgentDriver(
        agent_type="opencode",
        launch_command=_launch,
        ready_signal=_READY,
        submit=_submit,
        done_signal=_DONE,
        extract=_extract,
        exception_handlers=[
            ExceptionHandler(
                name="dismiss-update-modal",
                trigger=_UPDATE_MODAL,
                action=_dismiss_update_modal,
            ),
        ],
    )
)
