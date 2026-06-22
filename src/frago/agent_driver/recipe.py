"""Agent recipe contract — 单个 cli-agent 的适配契约。

所有 agent 特异性集中于此（启动命令、就绪信号、提交键、完成信号、答案抽取、
异常处理），driver 主路径不可见，NEVER 出现 ``if agent == "claude"``。

Phase 0 spike 阶段，recipe 以裸字符串 agent key（"claude" / "opencode"）注册，
不引入共享的 ``session.models.AgentType`` 枚举（补 OPENCODE/CODEX 属 Phase 2，
会触碰会话子系统，违反本轮零侵入约束）。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from frago.agent_driver.tmux_session import TmuxAgentSession


@dataclass(frozen=True)
class LaunchCtx:
    """生成启动命令时可见的上下文。"""

    cwd: str
    session_id: str


@dataclass(frozen=True)
class PaneMatcher:
    """判定一块 pane 文本是否命中某状态（就绪 / 完成）。

    ``pattern`` 是正则；``regex`` 预编译；调用 ``matches(text)`` 返回 bool。
    用正则而非固定行号/坐标，避免终端换行差异导致失配。
    """

    name: str
    pattern: str

    @property
    def regex(self) -> re.Pattern[str]:
        return re.compile(self.pattern, re.MULTILINE)

    def matches(self, text: str) -> bool:
        return self.regex.search(text) is not None


@dataclass(frozen=True)
class ExceptionHandler:
    """启动/运行期异常的一次性处理（如更新模态 → Esc）。

    ``trigger`` 命中 pane 文本时，对 session 执行 ``action``。
    """

    name: str
    trigger: PaneMatcher
    action: Callable[[TmuxAgentSession], None]


@dataclass(frozen=True)
class AgentRecipe:
    """单个 cli-agent 的适配契约。"""

    agent_type: str
    launch_command: Callable[[LaunchCtx], str]
    ready_signal: PaneMatcher
    submit: Callable[[TmuxAgentSession, str], None]
    done_signal: PaneMatcher
    extract: Callable[[str], str]
    exception_handlers: list[ExceptionHandler] = field(default_factory=list)
    # 可选：直接从完成时的可见 pane 抽取本轮答案（pane, prompt）→ answer。
    # 给 claude 这类"固定底部输入框 + 答案在框上方渲染 + alt-screen 无 scrollback"
    # 的 TUI 用：通用的 pre/post delta 锚点模型对其失效。设置后 driver 跳过
    # delta+extract 路径，直接喂可见 pane。opencode/codex 不设，沿用 delta 路径。
    read_answer: Callable[[str, str], str] | None = None
    # 运行期遇到认证墙/权限门/澄清门时命中；driver 据此把本轮判为 needs_input。
    needs_input_signal: PaneMatcher | None = None


_REGISTRY: dict[str, AgentRecipe] = {}


def register_recipe(recipe: AgentRecipe) -> None:
    """注册一个 recipe；重复注册同 agent_type 覆盖旧值。"""
    _REGISTRY[recipe.agent_type] = recipe


def load_recipe(agent_type: str) -> AgentRecipe:
    """按 agent key 加载 recipe；未注册抛 KeyError。"""
    # 延迟导入触发各 recipe 模块自注册，避免循环依赖。
    import frago.agent_driver.recipes  # noqa: F401

    try:
        return _REGISTRY[agent_type]
    except KeyError as exc:
        known = ", ".join(sorted(_REGISTRY)) or "<none>"
        raise KeyError(
            f"no recipe registered for agent_type={agent_type!r} (known: {known})"
        ) from exc
