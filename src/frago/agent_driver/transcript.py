"""tmux driver 输出 → 既有会话子系统契约的归一化写出。

不另立 schema：每轮的 user prompt 与 agent 答案经对应 ``AgentAdapter`` 转成
``ParsedRecord``，再用 ``record_to_step`` 落成 ``SessionStep`` 写进 ``storage``
的 agent_type 化目录（``~/.frago/sessions/{agent_type}/{session_id}/``）。
claude 走既有 ``ClaudeCodeAdapter``，opencode/codex 走 ``TmuxDriverAdapter``。
``frago session list`` 与 Web UI 因此零改动即可显示 tmux 会话。
"""

from __future__ import annotations

import uuid as _uuid
from datetime import datetime

from frago.agent_driver.tmux_session import TurnResult
from frago.session.models import (
    AgentType,
    MonitoredSession,
    SessionSource,
    SessionStatus,
)


def _coerce_agent_type(agent_type: AgentType | str) -> AgentType:
    return agent_type if isinstance(agent_type, AgentType) else AgentType(agent_type)


def _coerce_source(source: SessionSource | str) -> SessionSource:
    if isinstance(source, SessionSource):
        return source
    return SessionSource.WEB if str(source).lower() == "web" else SessionSource.TERMINAL


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

    session = read_metadata(session_id, at)
    if session is None:
        session = MonitoredSession(
            session_id=session_id,
            agent_type=at,
            project_path=project_path,
            name=(user_prompt.strip()[:80] or None),
            source_file=f"tmux://{at.value}/{session_id}",
            started_at=now,
            last_activity=now,
            status=SessionStatus.RUNNING,
            source=_coerce_source(source),
        )
    base_step = session.step_count

    user_rec = adapter.parse_turn(
        role="user",
        content=user_prompt,
        session_id=session_id,
        uuid=str(_uuid.uuid4()),
        timestamp=now,
    )
    agent_rec = adapter.parse_turn(
        role="assistant",
        content=result.text,
        session_id=session_id,
        uuid=str(_uuid.uuid4()),
        timestamp=now,
        parent_uuid=user_rec.uuid,
    )

    written = 0
    for rec in (user_rec, agent_rec):
        step, _tool_records = record_to_step(rec, base_step + written + 1)
        if step is not None:
            append_step(step, at)
            written += 1

    session.step_count = base_step + written
    session.last_activity = now
    write_metadata(session)
    return True
