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
    """轮次完工判定裁决结果。"""

    done: bool
    stop_reason: str | None = None
    final_text: str = ""


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
            return TurnCompletionVerdict(done=False, stop_reason=None)
        from frago.session.transcript_completion import evaluate_file

        verdict = evaluate_file(target)
        if verdict is None:
            return TurnCompletionVerdict(done=False, stop_reason=None)
        return TurnCompletionVerdict(
            done=bool(verdict.done),
            stop_reason=verdict.stop_reason,
            final_text=verdict.final_text or "",
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
            return TurnCompletionVerdict(done=False, stop_reason=None)
        from frago.session.transcript_completion import evaluate_file

        verdict = evaluate_file(target)
        if verdict is None:
            return TurnCompletionVerdict(done=False, stop_reason=None)
        return TurnCompletionVerdict(
            done=bool(verdict.done),
            stop_reason=verdict.stop_reason,
            final_text=verdict.final_text or "",
        )

    def probe_harness_idle(
        self, session_id: str, pane_text: str = "", pane_ansi: str = ""
    ) -> HarnessIdleVerdict:
        target_text = pane_text or pane_ansi
        completion = self.probe_turn_completion(session_id)

        is_generating = False
        if target_text and (
            "Thinking..." in target_text
            or "Generating" in target_text
            or bool(re.search(r"(?m)^\s*[✻✽✶✢✳✺✷✸✹✦·*∗•◦⠋⠙⠹⠸⠼⠴⠦⠧][^\n]*…", target_text))
        ):
            is_generating = True

        if is_generating and not completion.done:
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
        done = bool(turn.done) if turn is not None else False
        stop_reason = "end_turn" if done else None
        final_text = getattr(turn, "summary", "") or "" if turn is not None else ""
        return TurnCompletionVerdict(
            done=done,
            stop_reason=stop_reason,
            final_text=final_text,
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
            return TurnCompletionVerdict(done=False, stop_reason=None)

        from frago.session.adapters.codex_records import translate_session

        records = translate_session(session_id)
        if not records:
            return TurnCompletionVerdict(done=False, stop_reason=None)
        last = records[-1]
        if last.kind in ("agent.think", "agent.say"):
            return TurnCompletionVerdict(
                done=True,
                stop_reason="end_turn",
                final_text=str(last.payload.get("text") or ""),
            )
        return TurnCompletionVerdict(done=False, stop_reason=None)

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
            )
        return TurnCompletionVerdict(done=False, stop_reason=None)

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
