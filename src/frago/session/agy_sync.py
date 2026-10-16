"""把 agy 的会话转录备份进 frago 会话存储。

与 ``session/sync.py``（claude）、``session/opencode_sync.py``、``session/codex_sync.py``
同构：只做备份，不做解读。落点是 ``~/.frago/sessions/agy/<会话编号>/raw.jsonl``，一行
一条原始记录，与另外几家同构。

**为什么源本来就是文件了还要再备一份。** agy 的转录就在磁盘上的 JSONL，看着不需要备份。
但"frago 见过的会话不会因为另一个程序自己的清理动作而凭空消失"这件事，frago 说了不算
——claude 与 codex 各自都会删自己的记录，两家的备份就是为此而设。agy 同样把会话横跨
brain 目录、摘要库与 ``conversations/*.db`` 三处，它要不要轮转、什么时候轮转，不在
frago 手上。

备份范围是**本机全部 agy 会话**，不只是 frago 驱动过的那些：另外几家读的都是各自 agent
的全量记录，包含用户自己敲起来的会话，几家的行为要一致。

备份文件就是账本：已经备到第几条，看它自己有多少行，不另记偏移。转录只会被追加，所以
行数是稳定的游标。

硬约束：
- 源文件只读，NEVER 写。
- agy 没装（``brain/`` 不存在）返回空结果，NEVER 抛。
- 记录原样落盘，不经展示层的过滤——备份要的是本来的样子。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from frago.session import agy_store
from frago.session.models import AgentType
from frago.session.storage import get_session_base_dir

logger = logging.getLogger(__name__)

RAW_FILENAME = "raw.jsonl"


@dataclass
class AgySyncResult:
    """备份结果。字段语义与另外几家的同名结构对齐。"""

    synced: int = 0  # 新备份的会话数
    updated: int = 0  # 有新内容、增量追加的
    skipped: int = 0  # 无变化跳过的
    errors: list[str] = field(default_factory=list)


def raw_backup_path(session_id: str) -> Path:
    """这个会话的副本落在哪。"""
    return get_session_base_dir() / AgentType.AGY.value / session_id / RAW_FILENAME


def _line_count(path: Path) -> int:
    """文件里有多少行——它自己就是账本。"""
    if not path.exists():
        return 0
    with open(path, "rb") as fh:
        return sum(1 for _ in fh)


def sync_agy_session(conv: agy_store.AgyConversation) -> str | None:
    """备份单个会话。有实质变化时返回会话编号，无变化返回 None。

    转录被 agy 重写过（源比手上这份短）时整份重写，不追加——与 ``codex_sync`` 同一条
    处理。追加会让两份内容套在一起，而备份要的是"本来的样子"。
    """
    session_id = conv.conversation_id
    source = agy_store.transcript_path(session_id)
    try:
        source_lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
        source_mtime = source.stat().st_mtime
    except OSError as exc:
        raise RuntimeError(f"转录读不出来: {exc}") from exc

    backup = raw_backup_path(session_id)
    backed_up = _line_count(backup)

    if len(source_lines) < backed_up:
        offset, mode, action = 0, "w", "rewritten"
    elif len(source_lines) > backed_up:
        offset, mode, action = backed_up, "a", "created" if backed_up == 0 else "appended"
    else:
        offset, mode, action = 0, None, "unchanged"

    if mode is not None:
        backup.parent.mkdir(parents=True, exist_ok=True)
        with open(backup, mode, encoding="utf-8") as fh:
            for line in source_lines[offset:]:
                fh.write(line + "\n")
        # 副本的时刻跟着源走，不跟写盘那一刻。清单对只有副本的会话，把文件的修改时刻
        # 当成它的最后活动（见 ``storage._derive_session_from_raw``）：不改的话，一次
        # 全量备份会让每一场都读成"刚刚还在跑"，还会把清单前几名整个占满。
        os.utime(backup, (source_mtime, source_mtime))

    if action == "unchanged":
        return None

    logger.info("Backed up agy session: %s (%s, %d records)", session_id, action, len(source_lines))
    return session_id


def sync_agy_sessions(*, since_mtime_cache: dict[str, float] | None = None) -> AgySyncResult:
    """把本机全部 agy 会话备份进 frago 会话存储。幂等。

    Args:
        since_mtime_cache: 可选的内存缓存（会话编号 → 上次见到的最后修改时刻）。作用等同
            另外几家同步里的 mtime 缓存：没动过的会话在任何磁盘读之前就跳过。时刻取自
            agy 摘要库里的 ``last_modified_time``——会话一动它就变，与别家拿文件修改时刻
            当钟是同一个角色。

    Returns:
        备份结果。agy 没装时是一份空结果，NEVER 抛。
    """
    result = AgySyncResult()
    if not agy_store.brain_root().is_dir():
        logger.debug("agy brain directory absent, nothing to sync")
        return result

    for conv in agy_store.list_conversations():
        sid = conv.conversation_id
        try:
            cached = since_mtime_cache.get(sid) if since_mtime_cache is not None else None
            if cached is not None and conv.last_modified <= cached:
                result.skipped += 1
                continue

            if not agy_store.transcript_path(sid).exists():
                # 摘要库里有这一行、转录却不在：那是一场空会话（agy 连一次输入都没记下）。
                # 没有源可备，跳过，NEVER 为它建一个空的备份目录。时刻照记，免得每轮都
                # 来探一次盘。
                if since_mtime_cache is not None:
                    since_mtime_cache[sid] = conv.last_modified
                result.skipped += 1
                continue

            existed = raw_backup_path(sid).exists()
            synced_id = sync_agy_session(conv)
            if since_mtime_cache is not None:
                since_mtime_cache[sid] = conv.last_modified
            if synced_id is None:
                result.skipped += 1
            elif existed:
                result.updated += 1
            else:
                result.synced += 1
        except Exception as exc:  # noqa: BLE001 — 一个会话坏掉 NEVER 拖垮整批
            message = f"Sync failed {sid}: {exc}"
            logger.warning(message)
            result.errors.append(message)

    if result.synced or result.updated or result.errors:
        logger.info(
            "agy sync complete: synced=%d, updated=%d, skipped=%d, errors=%d",
            result.synced,
            result.updated,
            result.skipped,
            len(result.errors),
        )
    return result
