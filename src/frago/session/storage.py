"""
会话数据持久化存储

提供会话数据的本地存储能力，包括：
- 会话目录创建和管理
- metadata.json 读写
- steps.jsonl 追加写入
- summary.json 生成
- 会话列表查询
"""

import json
import logging
import os
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from frago.session.models import (
    AgentType,
    MonitoredSession,
    SessionStatus,
    SessionStep,
    SessionSummary,
    StepType,
    ToolCallRecord,
    ToolCallStatus,
    ToolUsageStats,
)

logger = logging.getLogger(__name__)

# 默认存储目录
DEFAULT_SESSION_DIR = Path.home() / ".frago" / "sessions"


def get_session_base_dir() -> Path:
    """获取会话存储基础目录

    支持通过环境变量 FRAGO_SESSION_DIR 自定义。

    Returns:
        会话存储基础目录路径
    """
    custom_dir = os.environ.get("FRAGO_SESSION_DIR")
    if custom_dir:
        return Path(custom_dir).expanduser()
    return DEFAULT_SESSION_DIR


# ============================================================
# 会话目录管理
# ============================================================


def get_session_dir(
    session_id: str, agent_type: AgentType = AgentType.CLAUDE
) -> Path:
    """获取会话存储目录路径

    Args:
        session_id: 会话 ID
        agent_type: Agent 类型

    Returns:
        会话目录路径
    """
    base_dir = get_session_base_dir()
    return base_dir / agent_type.value / session_id


def create_session_dir(
    session_id: str, agent_type: AgentType = AgentType.CLAUDE
) -> Path:
    """创建会话存储目录

    Args:
        session_id: 会话 ID
        agent_type: Agent 类型

    Returns:
        创建的会话目录路径
    """
    session_dir = get_session_dir(session_id, agent_type)
    session_dir.mkdir(parents=True, exist_ok=True)
    logger.debug(f"创建会话目录: {session_dir}")
    return session_dir


# ============================================================
# metadata.json 读写
# ============================================================


def write_metadata(session: MonitoredSession) -> Path:
    """写入会话元数据

    Args:
        session: 监控会话对象

    Returns:
        metadata.json 文件路径
    """
    session_dir = create_session_dir(session.session_id, session.agent_type)
    metadata_path = session_dir / "metadata.json"

    data = session.model_dump(mode="json")

    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.debug(f"写入元数据: {metadata_path}")
    return metadata_path


def read_metadata(
    session_id: str, agent_type: AgentType = AgentType.CLAUDE
) -> Optional[MonitoredSession]:
    """读取会话元数据

    Args:
        session_id: 会话 ID
        agent_type: Agent 类型

    Returns:
        监控会话对象，不存在时返回 None
    """
    session_dir = get_session_dir(session_id, agent_type)
    metadata_path = session_dir / "metadata.json"

    if not metadata_path.exists():
        return None

    try:
        with open(metadata_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return MonitoredSession.model_validate(data)
    except Exception as e:
        logger.warning(f"读取元数据失败: {e}")
        return None


def update_metadata(
    session_id: str,
    agent_type: AgentType = AgentType.CLAUDE,
    **updates: Any,
) -> Optional[MonitoredSession]:
    """更新会话元数据

    Args:
        session_id: 会话 ID
        agent_type: Agent 类型
        **updates: 要更新的字段

    Returns:
        更新后的监控会话对象
    """
    session = read_metadata(session_id, agent_type)
    if not session:
        return None

    # 更新字段
    for key, value in updates.items():
        if hasattr(session, key):
            setattr(session, key, value)

    write_metadata(session)
    return session


# ============================================================
# steps.jsonl 追加写入
# ============================================================


def append_step(step: SessionStep, agent_type: AgentType = AgentType.CLAUDE) -> Path:
    """追加写入步骤记录

    Args:
        step: 会话步骤对象
        agent_type: Agent 类型

    Returns:
        steps.jsonl 文件路径
    """
    session_dir = create_session_dir(step.session_id, agent_type)
    steps_path = session_dir / "steps.jsonl"

    data = step.model_dump(mode="json")
    line = json.dumps(data, ensure_ascii=False)

    with open(steps_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")

    logger.debug(f"追加步骤 {step.step_id}: {steps_path}")
    return steps_path


def read_steps(
    session_id: str, agent_type: AgentType = AgentType.CLAUDE
) -> List[SessionStep]:
    """读取所有步骤记录

    Args:
        session_id: 会话 ID
        agent_type: Agent 类型

    Returns:
        步骤记录列表
    """
    session_dir = get_session_dir(session_id, agent_type)
    steps_path = session_dir / "steps.jsonl"

    if not steps_path.exists():
        return []

    steps = []
    try:
        with open(steps_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    data = json.loads(line)
                    steps.append(SessionStep.model_validate(data))
    except Exception as e:
        logger.warning(f"读取步骤记录失败: {e}")

    return steps


# ============================================================
# summary.json 生成
# ============================================================


def generate_summary(
    session_id: str,
    agent_type: AgentType = AgentType.CLAUDE,
    tool_calls: Optional[List[ToolCallRecord]] = None,
) -> Optional[SessionSummary]:
    """生成会话摘要

    Args:
        session_id: 会话 ID
        agent_type: Agent 类型
        tool_calls: 工具调用记录列表（可选，用于统计）

    Returns:
        会话摘要对象
    """
    session = read_metadata(session_id, agent_type)
    if not session:
        return None

    steps = read_steps(session_id, agent_type)

    # 统计消息数量
    user_count = sum(1 for s in steps if s.type == StepType.USER_MESSAGE)
    assistant_count = sum(1 for s in steps if s.type == StepType.ASSISTANT_MESSAGE)

    # 统计工具调用
    tool_call_count = 0
    tool_success_count = 0
    tool_error_count = 0
    tool_usage: Counter = Counter()

    if tool_calls:
        for tc in tool_calls:
            tool_call_count += 1
            tool_usage[tc.tool_name] += 1
            if tc.status == ToolCallStatus.SUCCESS:
                tool_success_count += 1
            elif tc.status == ToolCallStatus.ERROR:
                tool_error_count += 1
    else:
        # 从步骤中估算
        tool_call_count = sum(1 for s in steps if s.type == StepType.TOOL_CALL)

    # 计算最常用工具
    most_used = [
        ToolUsageStats(tool_name=name, count=count)
        for name, count in tool_usage.most_common(5)
    ]

    # 计算持续时间（确保非负，因为文件中时间戳可能不是严格顺序）
    if session.started_at and session.ended_at:
        delta = session.ended_at - session.started_at
        total_duration_ms = max(0, int(delta.total_seconds() * 1000))
    elif session.started_at and session.last_activity:
        delta = session.last_activity - session.started_at
        total_duration_ms = max(0, int(delta.total_seconds() * 1000))
    else:
        total_duration_ms = 0

    summary = SessionSummary(
        session_id=session_id,
        total_duration_ms=total_duration_ms,
        user_message_count=user_count,
        assistant_message_count=assistant_count,
        tool_call_count=tool_call_count,
        tool_success_count=tool_success_count,
        tool_error_count=tool_error_count,
        most_used_tools=most_used,
        final_status=session.status,
    )

    return summary


def write_summary(
    session_id: str,
    agent_type: AgentType = AgentType.CLAUDE,
    tool_calls: Optional[List[ToolCallRecord]] = None,
) -> Optional[Path]:
    """生成并写入会话摘要

    Args:
        session_id: 会话 ID
        agent_type: Agent 类型
        tool_calls: 工具调用记录列表

    Returns:
        summary.json 文件路径
    """
    summary = generate_summary(session_id, agent_type, tool_calls)
    if not summary:
        return None

    session_dir = get_session_dir(session_id, agent_type)
    summary_path = session_dir / "summary.json"

    data = summary.model_dump(mode="json")

    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.debug(f"写入摘要: {summary_path}")
    return summary_path


def read_summary(
    session_id: str, agent_type: AgentType = AgentType.CLAUDE
) -> Optional[SessionSummary]:
    """读取会话摘要

    Args:
        session_id: 会话 ID
        agent_type: Agent 类型

    Returns:
        会话摘要对象
    """
    session_dir = get_session_dir(session_id, agent_type)
    summary_path = session_dir / "summary.json"

    if not summary_path.exists():
        return None

    try:
        with open(summary_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return SessionSummary.model_validate(data)
    except Exception as e:
        logger.warning(f"读取摘要失败: {e}")
        return None


# ============================================================
# 会话列表查询
# ============================================================


def read_steps_paginated(
    session_id: str,
    agent_type: AgentType = AgentType.CLAUDE,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """分页读取会话步骤

    Args:
        session_id: 会话 ID
        agent_type: Agent 类型
        limit: 每页数量（默认 50，最大 10000）
        offset: 偏移量

    Returns:
        包含 steps、total、offset、limit、has_more 的字典
    """
    # 参数验证
    limit = max(1, min(10000, limit))
    offset = max(0, offset)

    all_steps = read_steps(session_id, agent_type)
    total = len(all_steps)

    return {
        "steps": all_steps[offset : offset + limit],
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total,
    }


def count_sessions(
    agent_type: Optional[AgentType] = None,
    status: Optional[SessionStatus] = None,
) -> int:
    """统计会话数量

    Args:
        agent_type: 筛选特定 Agent 类型，None 表示所有
        status: 筛选特定状态

    Returns:
        会话数量
    """
    base_dir = get_session_base_dir()

    if not base_dir.exists():
        return 0

    count = 0

    # 确定要搜索的 agent 目录
    if agent_type:
        agent_dirs = [base_dir / agent_type.value]
    else:
        agent_dirs = [d for d in base_dir.iterdir() if d.is_dir()]

    for agent_dir in agent_dirs:
        if not agent_dir.exists():
            continue

        for session_dir in agent_dir.iterdir():
            if not session_dir.is_dir():
                continue

            metadata_path = session_dir / "metadata.json"
            if not metadata_path.exists():
                continue

            # 如果需要状态筛选，读取 metadata
            if status:
                try:
                    with open(metadata_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    session_status = SessionStatus(data.get("status", "running"))
                    if session_status != status:
                        continue
                except Exception:
                    continue

            count += 1

    return count


def list_sessions(
    agent_type: Optional[AgentType] = None,
    limit: int = 20,
    status: Optional[SessionStatus] = None,
) -> List[MonitoredSession]:
    """列出会话

    Args:
        agent_type: 筛选特定 Agent 类型，None 表示所有
        limit: 返回数量限制
        status: 筛选特定状态

    Returns:
        会话列表，按最后活动时间倒序排列
    """
    base_dir = get_session_base_dir()

    if not base_dir.exists():
        return []

    sessions = []

    # 确定要搜索的 agent 目录
    if agent_type:
        agent_dirs = [base_dir / agent_type.value]
    else:
        agent_dirs = [d for d in base_dir.iterdir() if d.is_dir()]

    for agent_dir in agent_dirs:
        if not agent_dir.exists():
            continue

        for session_dir in agent_dir.iterdir():
            if not session_dir.is_dir():
                continue

            metadata_path = session_dir / "metadata.json"
            if not metadata_path.exists():
                continue

            try:
                with open(metadata_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                session = MonitoredSession.model_validate(data)

                # 状态筛选
                if status and session.status != status:
                    continue

                sessions.append(session)
            except Exception as e:
                logger.warning(f"读取会话 {session_dir.name} 失败: {e}")

    # 按最后活动时间倒序排列（统一为 UTC 时区进行比较）
    from datetime import timezone
    def get_sortable_time(s):
        t = s.last_activity
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return t
    sessions.sort(key=get_sortable_time, reverse=True)

    return sessions[:limit]


def get_session_data(
    session_id: str, agent_type: AgentType = AgentType.CLAUDE
) -> Optional[Dict[str, Any]]:
    """获取会话完整数据

    Args:
        session_id: 会话 ID
        agent_type: Agent 类型

    Returns:
        包含 metadata、steps、summary 的字典
    """
    session = read_metadata(session_id, agent_type)
    if not session:
        return None

    return {
        "metadata": session,
        "steps": read_steps(session_id, agent_type),
        "summary": read_summary(session_id, agent_type),
    }


def delete_session(
    session_id: str, agent_type: AgentType = AgentType.CLAUDE
) -> bool:
    """删除会话数据

    Args:
        session_id: 会话 ID
        agent_type: Agent 类型

    Returns:
        是否删除成功
    """
    import shutil

    session_dir = get_session_dir(session_id, agent_type)

    if not session_dir.exists():
        return False

    try:
        shutil.rmtree(session_dir)
        logger.info(f"删除会话: {session_id}")
        return True
    except Exception as e:
        logger.error(f"删除会话失败: {e}")
        return False


def clean_old_sessions(
    max_age_days: int = 30,
    agent_type: Optional[AgentType] = None,
) -> int:
    """清理过期会话

    Args:
        max_age_days: 最大保留天数
        agent_type: 筛选特定 Agent 类型

    Returns:
        清理的会话数量
    """
    from datetime import timedelta

    cutoff = datetime.now() - timedelta(days=max_age_days)
    sessions = list_sessions(agent_type=agent_type, limit=1000)

    cleaned = 0
    for session in sessions:
        if session.last_activity < cutoff:
            if delete_session(session.session_id, session.agent_type):
                cleaned += 1

    logger.info(f"清理了 {cleaned} 个过期会话")
    return cleaned
