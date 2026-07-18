"""Agent driver contract — 单个 cli-agent 的适配契约。

所有 agent 特异性集中于此（启动命令、就绪信号、提交键、完成信号、答案抽取、
异常处理），主路径不可见，NEVER 出现 ``if agent == "claude"``。

Phase 0 spike 阶段，driver 以裸字符串 agent key（"claude" / "opencode"）注册，
不引入共享的 ``session.models.AgentType`` 枚举（补 OPENCODE/CODEX 属 Phase 2，
会触碰会话子系统，违反本轮零侵入约束）。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from frago.agent_driver.tmux_session import TmuxAgentSession


@dataclass(frozen=True)
class LaunchCtx:
    """生成启动命令时可见的上下文。"""

    cwd: str
    session_id: str
    # session_id 是否已是 agent 原生的真实会话 id（无需再派生）。
    # 默认 False：调用方给的是 frago 自己的标识（如 thread_id / conv-key），driver
    # 需把它确定性映射成合法的 agent 会话 id（claude 走 uuid5）。
    # True：调用方（如 WebUI 续接一个已存在的 claude 会话）给的就是真实 id，driver
    # 原样使用、跳过派生，否则会另起新会话、写进别的 jsonl，续不上原会话。
    native_session_id: bool = False


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
class CompletionVerdict:
    """权威完成探针的一次判定结果。

    ``done`` 为最新一轮是否答完；``text`` 是该轮最终文本（已知时），未知时为 None；
    ``marker`` 是这一轮的去重锚点（如终结记录 uuid），driver 据此判断「答完的是
    *本轮* 而非常驻会话里残留的上一轮」。
    """

    done: bool
    text: str | None = None
    marker: str | None = None


@dataclass(frozen=True)
class ExceptionHandler:
    """启动/运行期异常的一次性处理（如更新模态 → Esc）。

    ``trigger`` 命中 pane 文本时，对 session 执行 ``action``。
    """

    name: str
    trigger: PaneMatcher
    action: Callable[[TmuxAgentSession], None]


@dataclass(frozen=True)
class AgentDriver:
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
    # 可选：权威完成探针。给 claude 这类把结构化 transcript 写进 session JSONL 的
    # agent 用——从 JSONL 的 stop_reason 判「本轮是否真答完」+ 取最终文本，绕开读屏
    # 在多工具轮空窗帧的误判。入参是 session（探针自行定位/读取其 transcript），
    # 返回 CompletionVerdict；探针不可用（如 jsonl 尚未生成）时返回 None，driver
    # 当帧退回 pane done_signal。不设置时（opencode/codex）行为完全不变。
    completion_probe: Callable[[TmuxAgentSession], CompletionVerdict | None] | None = None
    # 可选：清空输入框残留文本的自愈动作，返回"确已清空"与否。给 claude 这类
    # 懒重绘 TUI 用——清行键（C-u）立即清空缓冲区，但 pane 不重绘、仍显示旧文本，
    # "发键后读屏等空输入框"的通用验证注定失败，必须由 driver 自己用结构手段
    # （探针字符强制重绘）确认缓冲区状态。不设置时上层退回通用行为（Escape +
    # 轮询 ready_signal）。
    clear_input: Callable[[TmuxAgentSession], bool] | None = None
    # 可选：定位该会话的 transcript 文件。给 claude 这类把结构化 transcript 写进
    # session JSONL 的 agent 用——``TranscriptStreamer`` 据此 tail 出逐块的文本/
    # 工具事件喂给 attached 流式（spec 20260607 Phase 6）。路径规则是 agent 特异性，
    # 故归 driver；streamer 只管 tail，NEVER 自己认目录布局。返回 None 表示当前
    # 定位不到（文件尚未生成）。不设置时（opencode/codex）该 agent 无 transcript
    # 流式，行为不变。
    transcript_path: Callable[[TmuxAgentSession], Path | None] | None = None


_REGISTRY: dict[str, AgentDriver] = {}


def register_driver(driver: AgentDriver) -> None:
    """注册一个 driver；重复注册同 agent_type 覆盖旧值。"""
    _REGISTRY[driver.agent_type] = driver


def load_driver(agent_type: str) -> AgentDriver:
    """按 agent key 加载 driver；未注册抛 KeyError。"""
    # 延迟导入触发各 driver 模块自注册，避免循环依赖。
    import frago.agent_driver.drivers  # noqa: F401

    try:
        return _REGISTRY[agent_type]
    except KeyError as exc:
        known = ", ".join(sorted(_REGISTRY)) or "<none>"
        raise KeyError(
            f"no driver registered for agent_type={agent_type!r} (known: {known})"
        ) from exc
