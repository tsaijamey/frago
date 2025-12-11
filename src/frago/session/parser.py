"""
JSONL 增量解析器

提供对 Claude Code 会话文件的增量解析能力，支持：
- 文件偏移量追踪，只解析新增行
- Claude Code 记录类型识别和转换
- 防御性解析，处理格式变更
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from frago.session.models import (
    SessionStep,
    StepType,
    ToolCallRecord,
    ToolCallStatus,
    extract_tool_input_summary,
    truncate_content,
)

logger = logging.getLogger(__name__)


# ============================================================
# 解析后的记录类型
# ============================================================


@dataclass
class ParsedRecord:
    """解析后的记录

    从 JSONL 原始记录提取的关键信息。
    """

    uuid: str
    session_id: str
    timestamp: datetime
    record_type: str  # user, assistant, system, file-history-snapshot
    parent_uuid: Optional[str] = None

    # 消息内容
    role: Optional[str] = None  # user, assistant
    content_text: Optional[str] = None  # 文本内容
    model: Optional[str] = None  # 模型标识

    # 工具调用信息 (assistant 消息可能包含)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)

    # 工具结果信息 (user 消息可能包含)
    tool_results: List[Dict[str, Any]] = field(default_factory=list)

    # Sidechain 标识（agent 子线程）
    is_sidechain: bool = False
    agent_id: Optional[str] = None

    # 原始数据
    raw_data: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# 增量解析器
# ============================================================


class IncrementalParser:
    """JSONL 增量解析器

    追踪文件偏移量，只解析新增的行。
    """

    def __init__(self, file_path: str):
        """初始化解析器

        Args:
            file_path: JSONL 文件路径
        """
        self.file_path = Path(file_path)
        self.offset: int = 0  # 当前文件偏移量
        self._session_id: Optional[str] = None  # 缓存的会话 ID

    @property
    def session_id(self) -> Optional[str]:
        """获取会话 ID（从文件记录中提取）

        注意：文件第一行可能是 file-history-snapshot 等无 sessionId 的记录，
        需要读取后续行直到找到 sessionId。
        """
        if self._session_id is None and self.file_path.exists():
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    for _ in range(10):  # 最多读 10 行
                        line = f.readline().strip()
                        if not line:
                            break
                        data = json.loads(line)
                        session_id = data.get("sessionId")
                        if session_id:
                            self._session_id = session_id
                            break
            except Exception as e:
                logger.warning(f"无法从文件提取 session_id: {e}")
        return self._session_id

    def parse_new_records(self) -> List[ParsedRecord]:
        """解析自上次以来新增的记录

        Returns:
            新增记录的列表
        """
        if not self.file_path.exists():
            return []

        records = []
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                # 跳到上次读取的位置
                f.seek(self.offset)

                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        data = json.loads(line)
                        record = self._parse_record(data)
                        if record:
                            records.append(record)
                    except json.JSONDecodeError as e:
                        logger.warning(f"JSON 解析错误: {e}")
                        continue

                # 更新偏移量
                self.offset = f.tell()

        except Exception as e:
            logger.error(f"读取文件失败: {e}")

        return records

    def _parse_record(self, data: Dict[str, Any]) -> Optional[ParsedRecord]:
        """解析单条记录

        采用防御性解析策略：
        - 未知字段会被忽略，不会导致解析失败
        - 关键字段缺失时会记录警告，但尽可能继续解析
        - 格式变更时保持向后兼容

        Args:
            data: 原始 JSON 数据

        Returns:
            解析后的记录，无法解析时返回 None
        """
        # 必需字段检查
        record_type = data.get("type")
        uuid = data.get("uuid")
        session_id = data.get("sessionId")

        if not record_type:
            logger.debug("记录缺少 type 字段，跳过")
            return None

        # 跳过元数据记录类型（这些不是核心对话数据，无需追踪）
        METADATA_TYPES = {"file-history-snapshot", "queue-operation", "summary"}
        if record_type in METADATA_TYPES:
            logger.debug(f"跳过元数据记录: {record_type}")
            return None

        if not uuid:
            # uuid 缺失时尝试使用其他标识（针对未知的新记录类型）
            uuid = data.get("id") or data.get("messageId") or f"unknown-{id(data)}"
            logger.debug(f"记录缺少 uuid 字段，使用备用标识: {uuid[:20]}")

        # session_id 缺失警告（但不阻止解析）
        if not session_id and not self._session_id:
            logger.warning("记录缺少 sessionId 字段，会话关联可能失败")

        # 解析时间戳
        timestamp_str = data.get("timestamp")
        if timestamp_str:
            try:
                timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except ValueError:
                timestamp = datetime.now()
        else:
            timestamp = datetime.now()

        record = ParsedRecord(
            uuid=uuid,
            session_id=session_id or self._session_id or "",
            timestamp=timestamp,
            record_type=record_type,
            parent_uuid=data.get("parentUuid"),
            is_sidechain=data.get("isSidechain", False),
            agent_id=data.get("agentId"),
            raw_data=data,
        )

        # 缓存 session_id
        if session_id and not self._session_id:
            self._session_id = session_id

        # 根据类型提取额外信息
        message = data.get("message", {})
        if message:
            record.role = message.get("role")
            record.model = message.get("model")

            # 提取内容
            content = message.get("content")
            if isinstance(content, str):
                record.content_text = content
            elif isinstance(content, list):
                # content 是内容块数组
                text_parts = []
                tool_calls = []
                tool_results = []

                for block in content:
                    if isinstance(block, dict):
                        block_type = block.get("type")
                        if block_type == "text":
                            text_parts.append(block.get("text", ""))
                        elif block_type == "tool_use":
                            tool_calls.append(block)
                        elif block_type == "tool_result":
                            tool_results.append(block)

                record.content_text = "\n".join(text_parts) if text_parts else None
                record.tool_calls = tool_calls
                record.tool_results = tool_results

        return record


# ============================================================
# 记录类型转换
# ============================================================


def record_to_step(
    record: ParsedRecord, step_id: int
) -> Tuple[Optional[SessionStep], List[ToolCallRecord]]:
    """将解析后的记录转换为 SessionStep 和 ToolCallRecord

    Args:
        record: 解析后的记录
        step_id: 步骤序号

    Returns:
        (SessionStep 或 None, ToolCallRecord 列表)
    """
    step = None
    tool_records = []

    # 确定步骤类型
    if record.record_type == "user":
        if record.tool_results:
            # 包含工具结果
            step_type = StepType.TOOL_RESULT
            content = _summarize_tool_results(record.tool_results)
        else:
            step_type = StepType.USER_MESSAGE
            content = truncate_content(record.content_text or "(空消息)")

    elif record.record_type == "assistant":
        if record.tool_calls:
            # 包含工具调用
            step_type = StepType.TOOL_CALL
            content = _summarize_tool_calls(record.tool_calls)

            # 创建工具调用记录
            for tc in record.tool_calls:
                tool_record = ToolCallRecord(
                    tool_call_id=tc.get("id", ""),
                    session_id=record.session_id,
                    step_id=step_id,
                    tool_name=tc.get("name", "Unknown"),
                    input_summary=extract_tool_input_summary(tc.get("input", {})),
                    called_at=record.timestamp,
                    status=ToolCallStatus.PENDING,
                )
                tool_records.append(tool_record)
        else:
            step_type = StepType.ASSISTANT_MESSAGE
            content = truncate_content(record.content_text or "(空回复)")

    elif record.record_type == "system":
        step_type = StepType.SYSTEM_EVENT
        content = truncate_content(record.content_text or "(系统事件)")

    else:
        # 忽略其他类型（如 file-history-snapshot）
        return None, []

    step = SessionStep(
        step_id=step_id,
        session_id=record.session_id,
        type=step_type,
        timestamp=record.timestamp,
        content_summary=content,
        raw_uuid=record.uuid,
        parent_uuid=record.parent_uuid,
    )

    return step, tool_records


def _summarize_tool_calls(tool_calls: List[Dict[str, Any]]) -> str:
    """汇总工具调用信息

    Args:
        tool_calls: 工具调用列表

    Returns:
        工具调用摘要
    """
    if not tool_calls:
        return "(无工具调用)"

    tool_names = [tc.get("name", "?") for tc in tool_calls]
    if len(tool_names) == 1:
        tc = tool_calls[0]
        input_summary = extract_tool_input_summary(tc.get("input", {}))
        return truncate_content(f"[{tool_names[0]}] {input_summary}")
    else:
        return f"[{', '.join(tool_names)}]"


def _summarize_tool_results(tool_results: List[Dict[str, Any]]) -> str:
    """汇总工具结果信息

    Args:
        tool_results: 工具结果列表

    Returns:
        工具结果摘要
    """
    if not tool_results:
        return "(无工具结果)"

    # 提取结果摘要
    summaries = []
    for tr in tool_results:
        tool_use_id = tr.get("tool_use_id", "?")
        content = tr.get("content", "")
        if isinstance(content, str):
            summaries.append(truncate_content(content, 50))
        else:
            summaries.append("(复杂结果)")

    if len(summaries) == 1:
        return f"结果: {summaries[0]}"
    else:
        return f"({len(summaries)} 个结果)"


# ============================================================
# 工具调用状态更新
# ============================================================


def update_tool_call_status(
    pending_calls: Dict[str, ToolCallRecord],
    record: ParsedRecord,
) -> List[ToolCallRecord]:
    """根据工具结果更新待处理的工具调用状态

    Args:
        pending_calls: 待处理的工具调用字典 (tool_call_id -> ToolCallRecord)
        record: 包含工具结果的记录

    Returns:
        已完成的工具调用记录列表
    """
    completed = []

    for result in record.tool_results:
        tool_use_id = result.get("tool_use_id")
        if tool_use_id and tool_use_id in pending_calls:
            call = pending_calls.pop(tool_use_id)

            # 更新状态
            call.completed_at = record.timestamp
            call.status = ToolCallStatus.SUCCESS  # 暂时假设成功

            # 计算耗时
            if call.called_at:
                delta = record.timestamp - call.called_at
                call.duration_ms = int(delta.total_seconds() * 1000)

            # 提取结果摘要
            content = result.get("content", "")
            if isinstance(content, str):
                call.result_summary = truncate_content(content, 100)
            elif isinstance(content, list):
                # 可能是包含多个块的结果
                text_parts = [
                    b.get("text", "")
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                ]
                call.result_summary = truncate_content(" ".join(text_parts), 100)

            # 检查是否有错误标记
            is_error = result.get("is_error", False)
            if is_error:
                call.status = ToolCallStatus.ERROR

            completed.append(call)

    return completed
