"""
会话同步模块

从 ~/.claude/projects/ 同步会话数据到 ~/.frago/sessions/claude/
支持幂等操作，不修改源文件。
"""

import json
import logging
import os
import uuid as uuid_module
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from frago.session.models import (
    AgentType,
    MonitoredSession,
    SessionStatus,
    SessionStep,
    StepType,
)
from frago.session.parser import IncrementalParser, record_to_step
from frago.session.storage import (
    append_step,
    get_session_dir,
    read_metadata,
    write_metadata,
    write_summary,
)

logger = logging.getLogger(__name__)

# Claude Code 会话目录
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"

# 无活动超时（用于判断会话是否已结束）
INACTIVITY_TIMEOUT_MINUTES = 1


@dataclass
class SyncResult:
    """同步结果"""

    synced: int = 0  # 新同步的会话数
    updated: int = 0  # 更新的会话数
    skipped: int = 0  # 跳过的会话数（已存在且无变化）
    errors: List[str] = field(default_factory=list)  # 错误信息


def encode_project_path(project_path: str) -> str:
    """将项目路径编码为 Claude Code 目录名

    Args:
        project_path: 项目绝对路径

    Returns:
        编码后的目录名
    """
    return project_path.replace("/", "-")


def is_main_session_file(filename: str) -> bool:
    """判断是否为主会话文件（非 sidechain）

    主会话文件格式: {uuid}.jsonl
    Sidechain 文件格式: agent-{short_id}.jsonl

    Args:
        filename: 文件名

    Returns:
        是否为主会话文件
    """
    if not filename.endswith(".jsonl"):
        return False

    # 排除 sidechain 文件
    if filename.startswith("agent-"):
        return False

    # 尝试解析为 UUID
    name = filename.replace(".jsonl", "")
    try:
        uuid_module.UUID(name)
        return True
    except ValueError:
        return False


def infer_session_status(
    records: List[Dict[str, Any]], last_activity: datetime
) -> SessionStatus:
    """从记录推断会话状态

    Args:
        records: 原始记录列表
        last_activity: 最后活动时间

    Returns:
        推断的会话状态
    """
    if not records:
        return SessionStatus.RUNNING

    # 检查是否有结束标记（如 summary 类型）
    for record in reversed(records[-10:]):  # 只检查最后几条
        record_type = record.get("type")
        if record_type == "summary":
            return SessionStatus.COMPLETED

    # 检查最后活动时间
    now = datetime.now(timezone.utc)
    if last_activity.tzinfo is None:
        last_activity = last_activity.replace(tzinfo=timezone.utc)

    delta = now - last_activity
    if delta > timedelta(minutes=INACTIVITY_TIMEOUT_MINUTES):
        # 超过 5 分钟无活动，视为已完成
        return SessionStatus.COMPLETED

    return SessionStatus.RUNNING


def parse_session_file(jsonl_path: Path) -> Dict[str, Any]:
    """解析会话 JSONL 文件

    Args:
        jsonl_path: JSONL 文件路径

    Returns:
        包含 session_id, records, steps, metadata 的字典
    """
    result = {
        "session_id": None,
        "records": [],
        "first_timestamp": None,
        "last_timestamp": None,
        "step_count": 0,
        "tool_call_count": 0,
        "is_sidechain": False,
    }

    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    record = json.loads(line)
                    result["records"].append(record)

                    # 提取 session_id
                    if not result["session_id"]:
                        result["session_id"] = record.get("sessionId")

                    # 检查是否为 sidechain
                    if record.get("isSidechain"):
                        result["is_sidechain"] = True

                    # 记录时间戳
                    timestamp_str = record.get("timestamp")
                    if timestamp_str:
                        try:
                            ts = datetime.fromisoformat(
                                timestamp_str.replace("Z", "+00:00")
                            )
                            if not result["first_timestamp"]:
                                result["first_timestamp"] = ts
                            result["last_timestamp"] = ts
                        except ValueError:
                            pass

                    # 统计工具调用
                    message = record.get("message", {})
                    if isinstance(message, dict):
                        content = message.get("content", [])
                        if isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict):
                                    if block.get("type") == "tool_use":
                                        result["tool_call_count"] += 1

                except json.JSONDecodeError:
                    continue

    except Exception as e:
        logger.warning(f"解析文件失败 {jsonl_path}: {e}")

    return result


def sync_session(
    jsonl_path: Path,
    project_path: str,
    force: bool = False,
) -> Optional[str]:
    """同步单个会话文件

    Args:
        jsonl_path: JSONL 文件路径
        project_path: 项目路径
        force: 是否强制重新同步

    Returns:
        同步的 session_id，失败返回 None
    """
    # 跳过空文件（如 Claude CLI resume 时创建的占位文件）
    if jsonl_path.stat().st_size == 0:
        logger.debug(f"跳过空文件: {jsonl_path}")
        return None

    # 解析会话文件
    parsed = parse_session_file(jsonl_path)

    session_id = parsed["session_id"]
    if not session_id:
        logger.debug(f"文件缺少 session_id: {jsonl_path}")
        return None

    # 跳过没有有效记录的会话
    if not parsed["records"]:
        logger.debug(f"跳过无记录的会话: {jsonl_path}")
        return None

    # 跳过 sidechain 会话
    if parsed["is_sidechain"]:
        logger.debug(f"跳过 sidechain 会话: {session_id}")
        return None

    # 检查是否已存在
    existing = read_metadata(session_id, AgentType.CLAUDE)
    if existing and not force:
        # 检查源文件是否有更新（支持继续对话场景）
        file_mtime = datetime.fromtimestamp(jsonl_path.stat().st_mtime, tz=timezone.utc)
        existing_last_activity = existing.last_activity
        if existing_last_activity.tzinfo is None:
            existing_last_activity = existing_last_activity.replace(tzinfo=timezone.utc)

        # 如果文件修改时间早于记录的最后活动时间，跳过
        if file_mtime <= existing_last_activity:
            if existing.status != SessionStatus.RUNNING:
                logger.debug(f"会话已存在且无更新: {session_id}")
                return None

    # 推断状态
    last_activity = parsed["last_timestamp"] or datetime.now(timezone.utc)
    status = infer_session_status(parsed["records"], last_activity)

    # 创建或更新会话元数据
    session = MonitoredSession(
        session_id=session_id,
        agent_type=AgentType.CLAUDE,
        project_path=project_path,
        source_file=str(jsonl_path),
        started_at=parsed["first_timestamp"] or datetime.now(timezone.utc),
        ended_at=last_activity if status != SessionStatus.RUNNING else None,
        status=status,
        step_count=0,  # 稍后更新
        tool_call_count=parsed["tool_call_count"],
        last_activity=last_activity,
    )

    # 获取已存在的步骤数（用于增量同步）
    existing_step_count = existing.step_count if existing else 0

    # 如果强制同步，清空已有步骤文件
    if force and existing_step_count > 0:
        from frago.session.storage import get_session_dir
        steps_file = get_session_dir(session_id, AgentType.CLAUDE) / "steps.jsonl"
        if steps_file.exists():
            steps_file.unlink()
        existing_step_count = 0

    # 使用增量解析器解析步骤
    parser = IncrementalParser(str(jsonl_path))
    records = parser.parse_new_records()

    # 转换为步骤（跳过已同步的）
    step_id = 0
    new_steps = 0
    for record in records:
        step_id += 1
        # 跳过已同步的步骤
        if step_id <= existing_step_count:
            continue
        step, _ = record_to_step(record, step_id)
        if step:
            step.session_id = session_id
            append_step(step, AgentType.CLAUDE)
            new_steps += 1

    session.step_count = step_id

    # 写入元数据
    write_metadata(session)

    # 如果已完成，生成摘要
    if status == SessionStatus.COMPLETED:
        write_summary(session_id, AgentType.CLAUDE)

    logger.info(f"同步会话: {session_id} (steps={step_id}, status={status.value})")
    return session_id


def sync_project_sessions(
    project_path: str,
    force: bool = False,
) -> SyncResult:
    """同步指定项目的 Claude 会话

    Args:
        project_path: 项目绝对路径
        force: 是否强制重新同步

    Returns:
        同步结果
    """
    result = SyncResult()

    # 编码项目路径
    project_path = os.path.abspath(project_path)
    encoded_path = encode_project_path(project_path)
    claude_dir = CLAUDE_PROJECTS_DIR / encoded_path

    if not claude_dir.exists():
        logger.debug(f"Claude 会话目录不存在: {claude_dir}")
        return result

    # 扫描所有 JSONL 文件
    for jsonl_file in claude_dir.glob("*.jsonl"):
        if not is_main_session_file(jsonl_file.name):
            continue

        try:
            # 检查是否已同步（仅用于统计，实际判断由 sync_session 负责）
            session_id = jsonl_file.stem
            existing = read_metadata(session_id, AgentType.CLAUDE)

            # 同步会话（sync_session 内部会检查文件修改时间决定是否需要更新）
            synced_id = sync_session(jsonl_file, project_path, force)
            if synced_id:
                if existing:
                    result.updated += 1
                else:
                    result.synced += 1
            else:
                result.skipped += 1

        except Exception as e:
            error_msg = f"同步失败 {jsonl_file.name}: {e}"
            logger.warning(error_msg)
            result.errors.append(error_msg)

    logger.info(
        f"同步完成: synced={result.synced}, updated={result.updated}, "
        f"skipped={result.skipped}, errors={len(result.errors)}"
    )
    return result


def sync_all_projects(force: bool = False) -> SyncResult:
    """同步所有项目的 Claude 会话

    Args:
        force: 是否强制重新同步

    Returns:
        同步结果
    """
    result = SyncResult()

    if not CLAUDE_PROJECTS_DIR.exists():
        logger.warning(f"Claude 项目目录不存在: {CLAUDE_PROJECTS_DIR}")
        return result

    for project_dir in CLAUDE_PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue

        # 解码项目路径
        project_path = project_dir.name.replace("-", "/")
        if not project_path.startswith("/"):
            project_path = "/" + project_path

        # 同步该项目
        project_result = sync_project_sessions(project_path, force)

        result.synced += project_result.synced
        result.updated += project_result.updated
        result.skipped += project_result.skipped
        result.errors.extend(project_result.errors)

    return result
