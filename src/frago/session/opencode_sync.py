"""把 opencode 会话库里的会话归档进 frago 会话存储（spec 20260725 Phase 3）。

与 ``session/sync.py``（claude 的同类实现）同构：幂等、增量、不碰源数据。差别只在
数据来源——claude 读 ``~/.claude/projects`` 下的 JSONL 文件，这里读 opencode 的
SQLite 会话库。归档落点是 ``~/.frago/sessions/opencode/<session_id>/``，与 claude
的目录结构一致，``frago session list`` 与 WebUI 因此零改动即可展示。

归档范围是**库里的全部会话**，不只是 frago 驱动过的那些：claude 侧同步读的是整个
``~/.claude/projects``，同样包含用户自己敲起来的会话，两个内核的行为要一致。

硬约束：
- 数据库只读，NEVER 写。
- 库不存在（用户没装 opencode）返回空结果，NEVER 抛。
- 片段翻成记录的规则一律走 ``opencode_store.part_payloads``，与实时流共用同一份
  事实；步骤一律经 ``monitor`` 的 opencode adapter 与 ``parser.record_to_step``，
  NEVER 另起一套 schema。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from frago.session import opencode_store
from frago.session.models import AgentType, MonitoredSession, SessionStatus, StepType
from frago.session.monitor import get_adapter
from frago.session.parser import record_to_step
from frago.session.storage import append_step, read_metadata, write_metadata, write_summary

logger = logging.getLogger(__name__)

# 会话"安静多久算收工"的阈值。
#
# opencode 没有显式的会话状态，所以判定规则是自己定的：**最后一条助手消息已进
# ``finish=="stop"``，且该会话的 ``time_updated`` 距今超过这个阈值 → 完成，否则运行中。**
# 单看 stop 不够——常驻会话答完一轮就停在 stop 上，用户随时可能敲下一轮，那不是
# 结束；单看安静时长也不够——助手正卡在一次长工具调用上时库里同样很久没动静。
# 取值与 claude 侧的 ``INACTIVITY_TIMEOUT_MINUTES``（1 分钟）对齐。
IDLE_SECONDS = 60


@dataclass
class OpencodeSyncResult:
    """同步结果。字段语义与 claude 侧的 ``SyncResult`` 对齐。"""

    synced: int = 0  # 新归档的会话数
    updated: int = 0  # 有新内容、增量更新的
    skipped: int = 0  # 无变化跳过的
    errors: list[str] = field(default_factory=list)


def _ms_to_datetime(stamp: int) -> datetime:
    """毫秒时间戳 → 本地 naive 时刻。异常值退回当下。"""
    try:
        return datetime.fromtimestamp(stamp / 1000)
    except (OverflowError, OSError, ValueError):
        return datetime.now()


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo else value


def _infer_status(row: opencode_store.OpencodeSessionRow) -> SessionStatus:
    """判会话状态。规则见 ``IDLE_SECONDS`` 的注释。"""
    if opencode_store.last_assistant_finish(row.session_id) != opencode_store.FINISH_DONE:
        return SessionStatus.RUNNING
    idle = datetime.now() - _ms_to_datetime(row.time_updated)
    if idle > timedelta(seconds=IDLE_SECONDS):
        return SessionStatus.COMPLETED
    return SessionStatus.RUNNING


def sync_opencode_session(row: opencode_store.OpencodeSessionRow) -> str | None:
    """归档单个会话。有实质变化时返回 session_id，无变化返回 None。"""
    adapter = get_adapter(AgentType.OPENCODE)
    if adapter is None:
        return None

    session_id = row.session_id
    last_activity = _ms_to_datetime(row.time_updated)
    status = _infer_status(row)
    existing = read_metadata(session_id, AgentType.OPENCODE)

    # 无变化直接跳过：库里这个会话自上次归档以来没再动过，且它已经不在运行中。
    # 还在运行中的会话每拍都重算——步骤按已归档条数增量追加，重算不会重复写。
    if (
        existing is not None
        and last_activity <= _naive(existing.last_activity)
        and existing.status != SessionStatus.RUNNING
        # 标题被事后改写（占位 → 语义）时哪怕别的都没动也要重走一遍。
        and existing.name == (row.title or None)
    ):
        return None

    existing_step_count = existing.step_count if existing else 0

    step_id = 0
    new_steps = 0
    tool_call_count = 0
    for item in opencode_store.session_parts(session_id):
        for kind, payload in opencode_store.part_payloads(
            item, session_id, include_user=True
        ):
            # 工具结果在归档里挂 user 角色，与 claude 的记录形态一致——那边工具结果
            # 本来就是随用户消息回来的，``record_to_step`` 也只在 user 角色下才把它
            # 翻成 tool_result 步骤。实时流不做这个改写（它按助手事件推给前端）。
            if kind == opencode_store.PART_TOOL_RESULT:
                payload = {**payload, "role": "user"}
            record = adapter.parse_record(payload)
            if record is None:
                continue
            step, _tool_records = record_to_step(record, step_id + 1)
            if step is None:
                continue
            step_id += 1
            if step.type == StepType.TOOL_CALL:
                tool_call_count += 1
            # 已归档过的步骤跳过（步骤序号是稳定的：片段按创建时间排，历史不会重排）。
            if step_id <= existing_step_count:
                continue
            step.session_id = session_id
            append_step(step, AgentType.OPENCODE)
            new_steps += 1

    session = MonitoredSession(
        session_id=session_id,
        agent_type=AgentType.OPENCODE,
        project_path=row.directory,
        # 标题用 opencode 自己生成的那条（如「Ping pong test」），比截取提示词可读。
        name=row.title or None,
        source_file=str(opencode_store.db_path()),
        started_at=_ms_to_datetime(row.time_created),
        ended_at=last_activity if status != SessionStatus.RUNNING else None,
        status=status,
        step_count=step_id,
        tool_call_count=tool_call_count,
        last_activity=last_activity,
    )

    is_new = existing is None
    status_changed = existing is not None and existing.status != status
    # 标题会被 opencode 事后改写：新会话先拿到占位标题（``New session - ...``），
    # 语义标题稍后才生成。只认步骤变化的话，归档会永远停在占位值上。
    title_changed = existing is not None and existing.name != session.name
    if not (is_new or new_steps > 0 or status_changed or title_changed):
        return None

    write_metadata(session)
    if status == SessionStatus.COMPLETED:
        write_summary(session_id, AgentType.OPENCODE)

    logger.info(
        "Synced opencode session: %s (steps=%d, new=%d, status=%s)",
        session_id,
        step_id,
        new_steps,
        status.value,
    )
    return session_id


def sync_opencode_sessions(
    *, since_updated_cache: dict[str, int] | None = None
) -> OpencodeSyncResult:
    """把会话库里的全部 opencode 会话归档进 frago 会话存储。幂等。

    Args:
        since_updated_cache: 可选的内存缓存（session_id → 上次见到的 ``time_updated``）。
            作用等同 claude 同步里的 mtime 缓存：没动过的会话在任何磁盘读之前就跳过。

    Returns:
        同步结果。库不存在时是一份空结果，NEVER 抛。
    """
    result = OpencodeSyncResult()
    if not opencode_store.db_path().exists():
        logger.debug("opencode session database absent, nothing to sync")
        return result

    for row in opencode_store.list_sessions():
        try:
            cached = (
                since_updated_cache.get(row.session_id)
                if since_updated_cache is not None
                else None
            )
            if cached is not None and row.time_updated <= cached:
                result.skipped += 1
                continue

            existed = read_metadata(row.session_id, AgentType.OPENCODE) is not None
            synced_id = sync_opencode_session(row)
            if since_updated_cache is not None:
                since_updated_cache[row.session_id] = row.time_updated
            if synced_id is None:
                result.skipped += 1
            elif existed:
                result.updated += 1
            else:
                result.synced += 1
        except Exception as exc:  # noqa: BLE001 — 一个会话坏掉 NEVER 拖垮整批
            message = f"Sync failed {row.session_id}: {exc}"
            logger.warning(message)
            result.errors.append(message)

    if result.synced or result.updated or result.errors:
        logger.info(
            "opencode sync complete: synced=%d, updated=%d, skipped=%d, errors=%d",
            result.synced,
            result.updated,
            result.skipped,
            len(result.errors),
        )
    return result
