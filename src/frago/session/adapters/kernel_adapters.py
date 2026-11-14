"""五内核统一会话适配器契约与注册表。

收口各内核在会话文件定位（locate_transcript）、统一记录解析（read_unified_records）
与轮次完工探针（probe_turn_completion）三大正交切面的能力，杜绝业务调用方出现
末端 if/else 特判。

涵盖内核：
- claude-code / claude
- coreagent
- agy
- codex
- opencode (显式声明非文件流，基于 SQLite 存储)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from frago.session.unified_record import UnifiedRecord

logger = logging.getLogger(__name__)

__all__ = [
    "KERNEL_SESSION_REGISTRY",
    "AgySessionAdapter",
    "ClaudeCodeSessionAdapter",
    "CodexSessionAdapter",
    "CoreAgentSessionAdapter",
    "HarnessIdleVerdict",
    "KernelSessionAdapter",
    "KernelSessionAdapterNotRegistered",
    "OpencodeSessionAdapter",
    "TurnCompletionVerdict",
    "get_kernel_session_adapter",
    "list_kernel_session_adapters",
    "register_kernel_session_adapter",
]


class KernelSessionAdapterNotRegistered(LookupError):
    """请求的内核家族尚未注册对应会话适配器。"""


@dataclass(frozen=True)
class HarnessIdleVerdict:
    """物理承载空闲探针裁决结果。"""

    is_busy: bool
    is_terminal_idle: bool
    awaiting_input: bool = False
    has_running_subshells: bool = False
    detail: str = ""


@dataclass(frozen=True)
class TurnCompletionVerdict:
    """轮次完工判定裁决结果。

    - ``done=True, unknown=False``：转录明确记录最新轮次已收尾；
    - ``done=False, unknown=False``：转录明确记录最新轮次仍在进行中；
    - ``done=False, unknown=True``：转录文件缺失、为空或未包含可定位的用户输入记录，无法仅凭转录裁决。
    """

    done: bool
    stop_reason: str | None = None
    final_text: str = ""
    unknown: bool = False


@runtime_checkable
class KernelSessionAdapter(Protocol):
    """五内核统一会话适配器协议契约。"""

    @property
    def family(self) -> str:
        """适配器所属内核家族标识。"""
        ...

    @property
    def supports_file_stream(self) -> bool:
        """是否支持单文件转录流监听（True 支持文件流，False 如 opencode SQLite 存储）。"""
        ...

    def locate_transcript(self, session_id: str) -> Path | None:
        """定位会话原始转录文件路径。若无单文件转录或不存在则返回 None，NEVER 抛异常。"""
        ...

    def read_unified_records(
        self, session_id: str, path: Path | None = None
    ) -> list[UnifiedRecord]:
        """将原始记录转换为统一记录列表。"""
        ...

    def probe_turn_completion(
        self, session_id: str, path: Path | None = None
    ) -> TurnCompletionVerdict:
        """探针检测最新轮次是否已完成（交还给人）及结束原因。"""
        ...

    def probe_harness_idle(
        self, session_id: str, pane_text: str = "", pane_ansi: str = ""
    ) -> HarnessIdleVerdict:
        """探针检测物理承载窗格/进程是否空闲或忙碌。"""
        ...

    def safe_terminate_command(
        self, session_id: str, is_borrowed: bool = False
    ) -> list[str] | None:
        """返回安全终止该承载的命令/按键序列。borrowed 模式只退出回 shell，owned 模式返回 None 由底层销毁。"""
        ...


class ClaudeCodeSessionAdapter:
    """Claude Code 内核会话适配器。"""

    family: str = "claude-code"
    supports_file_stream: bool = True

    def locate_transcript(self, session_id: str) -> Path | None:
        import contextlib

        from frago.session import transcript_completion

        if hasattr(transcript_completion, "locate_transcript"):
            with contextlib.suppress(Exception):
                p = transcript_completion.locate_transcript(session_id)
                if p is not None:
                    return Path(p)

        from frago.session.adapters import claude_code_records

        return claude_code_records.find_session_file(session_id)

    def read_unified_records(
        self, session_id: str, path: Path | None = None
    ) -> list[UnifiedRecord]:
        target = path or self.locate_transcript(session_id)
        if target is None or not target.exists():
            return []
        from frago.session.adapters.claude_code_records import to_unified

        return to_unified(target)

    def probe_turn_completion(
        self, session_id: str, path: Path | None = None
    ) -> TurnCompletionVerdict:
        target = path or self.locate_transcript(session_id)
        if target is None or not target.exists():
            return TurnCompletionVerdict(done=False, stop_reason=None, unknown=True)
        from frago.session.transcript_completion import evaluate_file

        verdict = evaluate_file(target)
        if verdict is None:
            return TurnCompletionVerdict(done=False, stop_reason=None, unknown=True)
        return TurnCompletionVerdict(
            done=bool(verdict.done),
            stop_reason=verdict.stop_reason,
            final_text=verdict.final_text or "",
            unknown=False,
        )

    def probe_harness_idle(
        self, session_id: str, pane_text: str = "", pane_ansi: str = ""  # noqa: ARG002
    ) -> HarnessIdleVerdict:
        target_text = pane_text or pane_ansi
        if not target_text:
            return HarnessIdleVerdict(
                is_busy=False, is_terminal_idle=True, awaiting_input=True
            )

        # 1. 严格检查是否有后台子外壳仍在运行（shells still running）
        if "shells still running" in target_text or "shell still running" in target_text:
            return HarnessIdleVerdict(
                is_busy=True,
                is_terminal_idle=False,
                awaiting_input=False,
                has_running_subshells=True,
                detail="Background shells still running",
            )

        # 2. 检查前台 busy 信号（生成中、转轮、括号耗时）
        from frago.agent_driver.drivers import claude as claude_driver

        is_busy = False
        try:
            if claude_driver._BUSY.search(target_text):
                is_busy = True
        except Exception:
            pass

        if is_busy:
            return HarnessIdleVerdict(
                is_busy=True,
                is_terminal_idle=False,
                awaiting_input=False,
                detail="Claude is busy generating or running tool",
            )

        return HarnessIdleVerdict(
            is_busy=False,
            is_terminal_idle=True,
            awaiting_input=True,
            detail="Claude is terminal idle",
        )

    def safe_terminate_command(
        self, session_id: str, is_borrowed: bool = False  # noqa: ARG002
    ) -> list[str] | None:
        if is_borrowed:
            return ["/exit", "C-c", "C-d"]
        return None


_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_CORE_TURN_ACTIVE_RE = re.compile(r"^(?:❯\s+\S|\[init\]\s+session=|⚙\s+\S|⏺\s+\S)")
_CORE_TURN_DONE_RE = re.compile(
    r"^(?:✓ Turn complete \(|✗ Turn failed \(|✓ Final \(|✗ Error \(|Failed to spawn frago-core:)"
)
_CORE_SPINNER_RE = re.compile(r"(?m)^\s*[✻✽✶✢✳✺✷✸✹✦·*∗•◦⠋⠙⠹⠸⠼⠴⠦⠧][^\n]*…")
_BARE_SHELL_LINE_RE = re.compile(
    r"^(?:\([^)]+\)\s*)?(?:[\w.-]+@[\w.-]+[:\s~][^\n]*|(?:ba)?sh-[\d.]+|zsh)\s*[$%#]\s*$"
)


def _looks_like_bare_shell_prompt(plain_text: str) -> bool:
    """判断窗格末尾是否已退回裸交互式 shell 提示符（而非运行中的 CoreAgent 宿主）。"""
    if not plain_text:
        return False
    non_empty = [ln.rstrip() for ln in plain_text.splitlines() if ln.strip()]
    if not non_empty:
        return False
    last = non_empty[-1].strip()
    if last in ("$", "%", "#", "❯"):
        return True
    return bool(_BARE_SHELL_LINE_RE.match(last))


def _coreagent_pane_is_generating(plain_text: str) -> bool:
    """判断 CoreAgent 窗格是否正处于未闭合生成或工具执行中（严防历史已完成工具行误报）。"""
    if not plain_text or _looks_like_bare_shell_prompt(plain_text):
        return False

    if "━━━ CoreAgent (" in plain_text:
        in_active_turn = False
        for raw_ln in plain_text.splitlines():
            ln = raw_ln.strip()
            if not ln:
                continue
            if _CORE_TURN_DONE_RE.match(ln):
                in_active_turn = False
            elif _CORE_TURN_ACTIVE_RE.match(ln):
                in_active_turn = True
        return in_active_turn

    lines = [ln for ln in plain_text.splitlines() if ln.strip()]
    tail = "\n".join(lines[-8:]) if lines else ""
    return bool(
        "Thinking..." in tail
        or "Generating" in tail
        or _CORE_SPINNER_RE.search(tail)
    )


class CoreAgentSessionAdapter:
    """CoreAgent 内核会话适配器。"""

    family: str = "coreagent"
    supports_file_stream: bool = True

    def locate_transcript(self, session_id: str) -> Path | None:
        from frago.session import coreagent_store

        return coreagent_store.find_session_file(session_id)

    def read_unified_records(
        self, session_id: str, path: Path | None = None
    ) -> list[UnifiedRecord]:
        target = path or self.locate_transcript(session_id)
        if target is None or not target.exists():
            return []
        from frago.session.adapters.claude_code_records import to_unified

        return to_unified(target)

    def probe_turn_completion(
        self, session_id: str, path: Path | None = None
    ) -> TurnCompletionVerdict:
        target = path or self.locate_transcript(session_id)
        if target is None or not target.exists():
            return TurnCompletionVerdict(done=False, stop_reason=None, unknown=True)
        from frago.session.transcript_completion import evaluate_file

        verdict = evaluate_file(target)
        if verdict is None:
            return TurnCompletionVerdict(done=False, stop_reason=None, unknown=True)
        return TurnCompletionVerdict(
            done=bool(verdict.done),
            stop_reason=verdict.stop_reason,
            final_text=verdict.final_text or "",
            unknown=False,
        )

    def probe_harness_idle(
        self, session_id: str, pane_text: str = "", pane_ansi: str = ""
    ) -> HarnessIdleVerdict:
        target_text = pane_text or pane_ansi
        plain_text = _ANSI_ESCAPE_RE.sub("", target_text) if target_text else ""
        bare_shell = _looks_like_bare_shell_prompt(plain_text)
        is_generating = (not bare_shell) and _coreagent_pane_is_generating(plain_text)

        transcript_path = self.locate_transcript(session_id)
        if transcript_path is not None and transcript_path.exists():
            completion = self.probe_turn_completion(session_id)
            if not completion.done and not bare_shell:
                return HarnessIdleVerdict(
                    is_busy=True,
                    is_terminal_idle=False,
                    awaiting_input=False,
                    detail="CoreAgent turn in progress",
                )
            if is_generating:
                return HarnessIdleVerdict(
                    is_busy=True,
                    is_terminal_idle=False,
                    awaiting_input=False,
                    detail="CoreAgent is processing turn",
                )
            return HarnessIdleVerdict(
                is_busy=False,
                is_terminal_idle=True,
                awaiting_input=True,
                detail="CoreAgent is idle",
            )

        # transcript_path 为 None（如虚拟 ID "__check_busy__" 或首条记录落盘前）：
        # 仅当明确处于生成/运行中窗格态才返回忙，绝不因缺少转录文件而假阳报忙。
        if is_generating:
            return HarnessIdleVerdict(
                is_busy=True,
                is_terminal_idle=False,
                awaiting_input=False,
                detail="CoreAgent is processing turn",
            )

        return HarnessIdleVerdict(
            is_busy=False,
            is_terminal_idle=True,
            awaiting_input=True,
            detail="CoreAgent is idle",
        )

    def safe_terminate_command(
        self, session_id: str, is_borrowed: bool = False  # noqa: ARG002
    ) -> list[str] | None:
        return None


class AgySessionAdapter:
    """Antigravity (agy) 内核会话适配器。"""

    family: str = "agy"
    supports_file_stream: bool = True

    def locate_transcript(self, session_id: str) -> Path | None:
        from frago.session import agy_store

        return agy_store.find_session_file(session_id)

    def read_unified_records(
        self, session_id: str, path: Path | None = None  # noqa: ARG002
    ) -> list[UnifiedRecord]:
        from frago.session.adapters.agy_records import translate_session

        return translate_session(session_id)

    def probe_turn_completion(
        self, session_id: str, path: Path | None = None  # noqa: ARG002
    ) -> TurnCompletionVerdict:
        from frago.session.agy_store import latest_turn

        turn = latest_turn(session_id)
        if turn is None:
            return TurnCompletionVerdict(
                done=False,
                stop_reason=None,
                final_text="",
                unknown=True,
            )
        done = bool(turn.done)
        stop_reason = "end_turn" if done else None
        final_text = (
            getattr(turn, "text", "") or getattr(turn, "summary", "") or ""
        )
        return TurnCompletionVerdict(
            done=done,
            stop_reason=stop_reason,
            final_text=final_text,
            unknown=False,
        )

    def probe_harness_idle(
        self, session_id: str, pane_text: str = "", pane_ansi: str = ""
    ) -> HarnessIdleVerdict:
        target_text = pane_text or pane_ansi
        if not target_text:
            return HarnessIdleVerdict(
                is_busy=False, is_terminal_idle=True, awaiting_input=True
            )

        lines = [ln for ln in target_text.splitlines() if ln.strip()]
        tail = "\n".join(lines[-6:]) if lines else ""
        has_busy_signal = bool(
            re.search(r"(?i:\besc\s+to\s+cancel\b)", tail)
            or re.search(
                r"(?m:^(?!\s*○\s+Thought\b|\s*\|)[^\n]*\bGenerating(?:\.\.\.|…|\s+response\b))",
                tail,
            )
        )

        # 核心防坑：当业务轮次已完成，即使停留在评分卡或待输入态，也裁决为空闲
        completion = self.probe_turn_completion(session_id)
        if completion.done:
            return HarnessIdleVerdict(
                is_busy=False,
                is_terminal_idle=True,
                awaiting_input=True,
                detail="Agy turn completed, pane is idle or awaiting feedback",
            )

        if has_busy_signal:
            return HarnessIdleVerdict(
                is_busy=True,
                is_terminal_idle=False,
                awaiting_input=False,
                detail="Agy is generating response",
            )

        return HarnessIdleVerdict(
            is_busy=False,
            is_terminal_idle=True,
            awaiting_input=True,
            detail="Agy control tail is idle",
        )

    def safe_terminate_command(
        self, session_id: str, is_borrowed: bool = False  # noqa: ARG002
    ) -> list[str] | None:
        if is_borrowed:
            return ["C-c", "C-c", "exit", "C-d"]
        return None


class CodexSessionAdapter:
    """Codex 内核会话适配器。"""

    family: str = "codex"
    supports_file_stream: bool = True

    def locate_transcript(self, session_id: str) -> Path | None:
        from frago.session import codex_store

        return codex_store.find_rollout(session_id)

    def read_unified_records(
        self, session_id: str, path: Path | None = None  # noqa: ARG002
    ) -> list[UnifiedRecord]:
        from frago.session.adapters.codex_records import translate_session

        return translate_session(session_id)

    def probe_turn_completion(
        self, session_id: str, path: Path | None = None
    ) -> TurnCompletionVerdict:
        from frago.session import codex_store

        turn = codex_store.latest_turn(session_id)
        if turn is not None:
            done = bool(turn.done)
            return TurnCompletionVerdict(
                done=done,
                stop_reason="end_turn" if done else None,
                final_text=getattr(turn, "text", "") or "",
            )

        target = path or self.locate_transcript(session_id)
        if target is None or not target.exists():
            return TurnCompletionVerdict(done=False, stop_reason=None, unknown=True)

        from frago.session.adapters.codex_records import translate_session

        records = translate_session(session_id)
        if not records:
            return TurnCompletionVerdict(done=False, stop_reason=None, unknown=True)
        last = records[-1]
        if last.kind in ("agent.think", "agent.say"):
            return TurnCompletionVerdict(
                done=True,
                stop_reason="end_turn",
                final_text=str(last.payload.get("text") or ""),
                unknown=False,
            )
        return TurnCompletionVerdict(done=False, stop_reason=None, unknown=False)

    def probe_harness_idle(
        self, session_id: str, pane_text: str = "", pane_ansi: str = ""
    ) -> HarnessIdleVerdict:
        target_text = pane_text or pane_ansi
        is_busy = False
        if target_text and (
            bool(re.search(r"(?i:\besc\s+to\s+(?:interrupt|cancel)\b)", target_text))
            or bool(re.search(r"(?m)^\s*[✻✽✶✢✳✺✷✸✹✦·*∗•◦⠋⠙⠹⠸⠼⠴⠦⠧][^\n]*…", target_text))
        ):
            is_busy = True

        completion = self.probe_turn_completion(session_id)
        if completion.done:
            is_busy = False

        return HarnessIdleVerdict(
            is_busy=is_busy,
            is_terminal_idle=not is_busy,
            awaiting_input=not is_busy,
            detail="Codex busy" if is_busy else "Codex idle",
        )

    def safe_terminate_command(
        self, session_id: str, is_borrowed: bool = False  # noqa: ARG002
    ) -> list[str] | None:
        if is_borrowed:
            return ["C-c", "C-d"]
        return None


class OpencodeSessionAdapter:
    """Opencode 内核会话适配器（显式声明 SQLite 存储，非单文件流）。"""

    family: str = "opencode"
    supports_file_stream: bool = False

    def locate_transcript(self, session_id: str) -> Path | None:  # noqa: ARG002
        # opencode 记录在 SQLite 库，非单文件 transcript，显式返回 None
        return None

    def read_unified_records(
        self, session_id: str, path: Path | None = None  # noqa: ARG002
    ) -> list[UnifiedRecord]:
        from frago.session.adapters.opencode_records import to_unified

        return to_unified(session_id)

    def probe_turn_completion(
        self, session_id: str, path: Path | None = None  # noqa: ARG002
    ) -> TurnCompletionVerdict:
        from frago.session import opencode_store

        turn = opencode_store.latest_turn(session_id)
        if turn is not None:
            done = bool(turn.done)
            return TurnCompletionVerdict(
                done=done,
                stop_reason="end_turn" if done else None,
                final_text=getattr(turn, "text", "") or "",
                unknown=False,
            )
        return TurnCompletionVerdict(done=False, stop_reason=None, unknown=True)

    def probe_harness_idle(
        self, session_id: str, pane_text: str = "", pane_ansi: str = ""  # noqa: ARG002
    ) -> HarnessIdleVerdict:
        target_text = pane_text or pane_ansi
        is_busy = False
        if target_text and (
            bool(re.search(r"(?i:\besc\s+to\s+(?:interrupt|cancel)\b)", target_text))
            or bool(re.search(r"(?m)^\s*[✻✽✶✢✳✺✷✸✹✦·*∗•◦⠋⠙⠹⠸⠼⠴⠦⠧][^\n]*…", target_text))
        ):
            is_busy = True

        return HarnessIdleVerdict(
            is_busy=is_busy,
            is_terminal_idle=not is_busy,
            awaiting_input=not is_busy,
            detail="Opencode busy" if is_busy else "Opencode idle",
        )

    def safe_terminate_command(
        self, session_id: str, is_borrowed: bool = False  # noqa: ARG002
    ) -> list[str] | None:
        if is_borrowed:
            return ["C-c", "C-d"]
        return None


_KERNEL_SESSION_REGISTRY: dict[str, KernelSessionAdapter] = {}
KERNEL_SESSION_REGISTRY = _KERNEL_SESSION_REGISTRY
_KERNEL_BUILTINS_LOADED = False


def _load_kernel_builtins() -> None:
    global _KERNEL_BUILTINS_LOADED
    if _KERNEL_BUILTINS_LOADED:
        return

    claude_adapter = ClaudeCodeSessionAdapter()
    coreagent_adapter = CoreAgentSessionAdapter()
    agy_adapter = AgySessionAdapter()
    codex_adapter = CodexSessionAdapter()
    opencode_adapter = OpencodeSessionAdapter()

    defaults: dict[str, KernelSessionAdapter] = {
        "claude-code": claude_adapter,
        "claude": claude_adapter,
        "coreagent": coreagent_adapter,
        "agy": agy_adapter,
        "codex": codex_adapter,
        "opencode": opencode_adapter,
    }
    for family, adapter in defaults.items():
        if family not in _KERNEL_SESSION_REGISTRY:
            _KERNEL_SESSION_REGISTRY[family] = adapter
    _KERNEL_BUILTINS_LOADED = True


def register_kernel_session_adapter(
    family: str, adapter: KernelSessionAdapter
) -> None:
    """登记内核会话适配器。支持测试打桩覆盖。"""
    _KERNEL_SESSION_REGISTRY[family] = adapter


def get_kernel_session_adapter(family: str) -> KernelSessionAdapter:
    """获取指定内核家族的会话适配器。未注册时抛出 KernelSessionAdapterNotRegistered。"""
    _load_kernel_builtins()
    adapter = _KERNEL_SESSION_REGISTRY.get(family)
    if adapter is None:
        raise KernelSessionAdapterNotRegistered(f"内核家族 {family!r} 尚未注册会话适配器")
    return adapter


def list_kernel_session_adapters() -> dict[str, KernelSessionAdapter]:
    """返回当前已注册适配器副本。"""
    _load_kernel_builtins()
    return dict(_KERNEL_SESSION_REGISTRY)


_load_kernel_builtins()
