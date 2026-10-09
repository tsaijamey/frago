"""把 CoreAgent 的会话记录备份进 frago 会话存储。

与 ``session/sync.py``（claude）、``session/opencode_sync.py``、``session/codex_sync.py``
同构：只做备份，不做解读。落点是 ``~/.frago/sessions/coreagent/<session_id>/raw.jsonl``，
一行一条原始记录，与另外三家同构。

**为什么已经是 frago 自己的文件了还要再备一份。** CoreAgent 的记录本来就是磁盘上的
JSONL（``~/.frago/coreagent/sessions/<工作目录编码>/<会话编号>.jsonl``），看着不需要备份。
但**命令行那一侧读的不是那个目录**：``frago session list`` 扫的是
``~/.frago/sessions/<家名>/<会话编号>/raw.jsonl``，``frago session search`` 的语料也是
同一棵树（``search.py`` 的 ``_CORE_DIRS`` 自己写着「MUST 与会话备份的写入侧对齐」）。
少这一份，CoreAgent 的会话在命令行上就是不存在——清单里没有、检索也搜不到，而网页会话页
因为直接读原生根，一直看得见。两边对不上，人才会以为"没做过"。

备份文件就是账本：已经备到第几条，看它自己有多少行，不另记偏移。记录只会被追加，所以行数
是稳定的游标。

硬约束：
- 源文件只读，NEVER 写。
- CoreAgent 目录不在（没跑过）返回空结果，NEVER 抛。
- 记录原样落盘，不经展示层的过滤——备份要的是本来的样子。
- 观察者槽位与记录同一个会话目录（``observer-slots.json`` 等），只写 ``raw.jsonl``
  这个名字，NEVER 动别人的文件。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from frago.session import coreagent_store
from frago.session.models import AgentType
from frago.session.storage import get_session_base_dir

logger = logging.getLogger(__name__)

RAW_FILENAME = "raw.jsonl"


@dataclass
class CoreAgentSyncResult:
    """备份结果。字段语义与另外三家的同名结构对齐。"""

    synced: int = 0  # 新备份的会话数
    updated: int = 0  # 有新内容、增量追加的
    skipped: int = 0  # 无变化跳过的
    errors: list[str] = field(default_factory=list)


def raw_backup_path(session_id: str) -> Path:
    """这个会话的副本落在哪。"""
    return get_session_base_dir() / AgentType.COREAGENT.value / session_id / RAW_FILENAME


def _line_count(path: Path) -> int:
    """文件里有多少行——它自己就是账本。"""
    if not path.exists():
        return 0
    with open(path, "rb") as fh:
        return sum(1 for _ in fh)


def sync_coreagent_session(source: Path) -> str | None:
    """备份单个会话。有实质变化时返回 session_id，无变化返回 None。"""
    session_id = source.stem
    try:
        source_lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
        source_mtime = source.stat().st_mtime
    except OSError as exc:
        raise RuntimeError(f"CoreAgent 会话记录读不出来: {exc}") from exc

    backup = raw_backup_path(session_id)
    backed_up = _line_count(backup)

    if len(source_lines) < backed_up:
        # 源比手上这份还短：这个会话被重写过，手上那份是一个已经不存在的版本。
        offset, mode, action = 0, "w", "rewritten"
    elif len(source_lines) > backed_up:
        offset, mode, action = (
            backed_up,
            "a",
            "created" if backed_up == 0 else "appended",
        )
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

    logger.info(
        "Backed up CoreAgent session: %s (%s, %d records)",
        session_id,
        action,
        len(source_lines),
    )
    return session_id


def sync_coreagent_sessions(
    *, since_mtime_cache: dict[str, float] | None = None
) -> CoreAgentSyncResult:
    """把本机全部 CoreAgent 会话备份进 frago 会话存储。幂等。

    Args:
        since_mtime_cache: 可选的内存缓存（session_id → 上次见到的 mtime）。作用等同
            claude 同步里的 mtime 缓存：没动过的会话在任何磁盘读之前就跳过。

    Returns:
        备份结果。CoreAgent 还没跑过时是一份空结果，NEVER 抛。
    """
    result = CoreAgentSyncResult()
    if not coreagent_store.sessions_root().is_dir():
        logger.debug("coreagent sessions directory absent, nothing to sync")
        return result

    for source in coreagent_store.iter_session_files():
        session_id = source.stem
        try:
            cached = since_mtime_cache.get(session_id) if since_mtime_cache is not None else None
            try:
                mtime = source.stat().st_mtime
            except OSError as exc:
                raise RuntimeError(f"记录文件摸不到: {exc}") from exc

            if cached is not None and mtime <= cached:
                result.skipped += 1
                continue

            existed = raw_backup_path(session_id).exists()
            synced_id = sync_coreagent_session(source)
            if since_mtime_cache is not None:
                since_mtime_cache[session_id] = mtime
            if synced_id is None:
                result.skipped += 1
            elif existed:
                result.updated += 1
            else:
                result.synced += 1
        except Exception as exc:  # noqa: BLE001 — 一个会话坏掉 NEVER 拖垮整批
            message = f"Sync failed {session_id}: {exc}"
            logger.warning(message)
            result.errors.append(message)

    if result.synced or result.updated or result.errors:
        logger.info(
            "coreagent sync complete: synced=%d, updated=%d, skipped=%d, errors=%d",
            result.synced,
            result.updated,
            result.skipped,
            len(result.errors),
        )
    return result
