"""tmux driver 输出 → 既有会话子系统契约的归一化写出。

不另立 schema：每轮的 user prompt 与 agent 答案经对应 ``AgentAdapter`` 转成
``ParsedRecord``，再用 ``record_to_step`` 落成 ``SessionStep`` 写进 ``storage``
的 agent_type 化目录（``~/.frago/sessions/{agent_type}/{session_id}/``）。
claude 走既有 ``ClaudeCodeAdapter``，opencode/codex 走 ``TmuxDriverAdapter``。
``frago session list`` 与 Web UI 因此零改动即可显示 tmux 会话。
"""

from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from frago.agent_driver.tmux_session import TurnResult
from frago.session.models import (
    AgentType,
    MonitoredSession,
    SessionSource,
    SessionStatus,
)

if TYPE_CHECKING:
    from frago.agent_driver.driver import AgentDriver


def _coerce_agent_type(agent_type: AgentType | str) -> AgentType:
    return agent_type if isinstance(agent_type, AgentType) else AgentType(agent_type)


def _coerce_source(source: SessionSource | str) -> SessionSource:
    if isinstance(source, SessionSource):
        return source
    raw = str(source or "").strip().lower()
    if not raw:
        return SessionSource.TERMINAL
    if raw == SessionSource.UNKNOWN.value:
        return SessionSource.UNKNOWN
    from frago.ontology.runtime import normalize_session_origin

    normalized = normalize_session_origin(raw)
    try:
        return SessionSource(normalized)
    except ValueError:
        return SessionSource.TERMINAL


def _resolve_session_terminal_state(
    result: TurnResult, ended_at: datetime
) -> tuple[SessionStatus, datetime | None]:
    """把 TurnResult.status 映射为 metadata.json 的 SessionStatus 与 ended_at。"""
    norm = str(getattr(result, "status", "ok") or "ok").strip().lower()
    if norm == "ok":
        return SessionStatus.COMPLETED, ended_at
    if norm == "needs_input":
        return SessionStatus.AWAITING_INPUT, None
    return SessionStatus.ERROR, ended_at


def _resolve_turn_timestamps(
    result: TurnResult, now: datetime
) -> tuple[datetime, datetime]:
    """保真还原一轮执行的真实起止时间，禁止以落盘瞬间覆写导致 started_at == ended_at。"""
    duration_ms = max(0, int(getattr(result, "duration_ms", 0) or 0))
    ended_at = getattr(result, "ended_at", None) or now
    started_at = getattr(result, "started_at", None)
    if started_at is None:
        started_at = (
            ended_at - timedelta(milliseconds=duration_ms)
            if duration_ms > 0
            else ended_at
        )
    elif duration_ms > 0 and ended_at <= started_at:
        ended_at = started_at + timedelta(milliseconds=duration_ms)
    return started_at, ended_at


def write_turn(
    session_id: str,
    agent_type: AgentType | str,
    project_path: str,
    user_prompt: str,
    result: TurnResult,
    *,
    source: SessionSource | str = SessionSource.TERMINAL,
) -> bool:
    """把一轮 user→agent 归一化落盘。返回是否成功写入（无 adapter 时 False）。"""
    from frago.session.monitor import get_adapter
    from frago.session.parser import record_to_step
    from frago.session.storage import append_step, read_metadata, write_metadata

    at = _coerce_agent_type(agent_type)
    adapter = get_adapter(at)
    if adapter is None:
        return False

    now = datetime.now()
    started_at, ended_at = _resolve_turn_timestamps(result, now)
    coerced_source = _coerce_source(source)

    session = read_metadata(session_id, at)
    if session is None:
        session = MonitoredSession(
            session_id=session_id,
            agent_type=at,
            project_path=project_path,
            name=(user_prompt.strip()[:80] or None),
            source_file=f"tmux://{at.value}/{session_id}",
            started_at=started_at,
            last_activity=ended_at,
            status=SessionStatus.RUNNING,
            source=coerced_source,
        )
    base_step = session.step_count

    user_rec = adapter.parse_turn(
        role="user",
        content=user_prompt,
        session_id=session_id,
        uuid=str(_uuid.uuid4()),
        timestamp=started_at,
    )
    norm_status = str(getattr(result, "status", "ok") or "ok").strip().lower()
    if norm_status == "timeout":
        duration_ms = max(0, int(getattr(result, "duration_ms", 0) or 0))
        response_rec = adapter.parse_turn(
            role="system",
            content=(
                f"[timeout] turn timed out after {duration_ms}ms "
                "without assistant response"
            ),
            session_id=session_id,
            uuid=str(_uuid.uuid4()),
            timestamp=ended_at,
            parent_uuid=user_rec.uuid,
        )
    elif norm_status == "error" and not (result.text or "").strip():
        response_rec = adapter.parse_turn(
            role="system",
            content="[error] turn terminated with error without assistant response",
            session_id=session_id,
            uuid=str(_uuid.uuid4()),
            timestamp=ended_at,
            parent_uuid=user_rec.uuid,
        )
    else:
        response_rec = adapter.parse_turn(
            role="assistant",
            content=result.text,
            session_id=session_id,
            uuid=str(_uuid.uuid4()),
            timestamp=ended_at,
            parent_uuid=user_rec.uuid,
        )

    written = 0
    for rec in (user_rec, response_rec):
        step, _tool_records = record_to_step(rec, base_step + written + 1)
        if step is not None:
            append_step(step, at)
            written += 1

    session.step_count = base_step + written
    session.last_activity = ended_at
    session.status, session.ended_at = _resolve_session_terminal_state(result, ended_at)
    write_metadata(session)
    return True


def persist_turn_result(
    *,
    session_id: str,
    agent_type: AgentType | str,
    project_path: str,
    user_prompt: str,
    result: TurnResult,
    native_session_id: bool = False,
    source: SessionSource | str = SessionSource.TERMINAL,
    driver: AgentDriver | None = None,
) -> bool:
    """统一持久化出口：原生转录驱动严禁双轨落盘，非原生驱动强制复用唯一规范编号。

    - 具备原生持久化转录存储的驱动（如 Claude JSONL、Codex rollout、OpenCode SQLite、
      AGY 原生转录、内置 CoreAgent），由各自 syncer 统一同步进会话清单；此处直接返回
      ``False``，禁止由外层生成合成 ``tmux://`` 目录导致单次运行分裂双记录。
    - 无原生转录存储的驱动，先解析唯一规范会话编号（canonical session id）再调用
      :func:`write_turn` 单轨落盘，与 ``session-ontology-store.json`` 保持严格 1:1 一致。
    """
    from frago.agent_driver.driver import (
        has_native_transcript,
        resolve_canonical_session_id,
    )

    at_str = agent_type.value if isinstance(agent_type, AgentType) else str(agent_type)
    is_native = (
        driver.has_native_transcript
        if driver is not None
        else has_native_transcript(at_str)
    )
    if is_native:
        return False

    canonical_sid = (
        getattr(result, "canonical_session_id", None)
        or resolve_canonical_session_id(
            at_str,
            session_id,
            native_session_id=native_session_id,
        )
    )
    return write_turn(
        canonical_sid,
        agent_type,
        project_path,
        user_prompt,
        result,
        source=source,
    )
