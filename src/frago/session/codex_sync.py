"""把 codex 的 rollout 会话备份进 frago 会话存储。

与 ``session/sync.py``（claude）和 ``session/opencode_sync.py`` 同构：只做备份，不做
解读。落点是 ``~/.frago/sessions/codex/<session_id>/raw.jsonl``，一行一条原始记录，
与另外两家同构。

**为什么已经是文件了还要再备一份。** codex 的 rollout 本来就是磁盘上的 JSONL，看着
不需要备份。但 codex 自己会删：``codex archive`` / ``codex delete`` 都会动它，会话
也可能随 ``$CODEX_HOME`` 被清理而消失。备份的意义是"frago 见过的会话不会因为另一个
程序的清理动作而凭空消失"，与 claude 侧的道理一样。

备份范围是**本机全部 codex 会话**，不只是 frago 驱动过的那些：另外两家读的都是各自
agent 的全量记录，包含用户自己敲起来的会话，三家的行为要一致。

备份文件就是账本：已经备到第几条，看它自己有多少行，不另记偏移。rollout 只会被追加，
所以行数是稳定的游标。

硬约束：
- 源文件只读，NEVER 写。
- codex 没装（``sessions/`` 不存在）返回空结果，NEVER 抛。
- 记录原样落盘，不经展示层的过滤——备份要的是本来的样子。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from frago.session import codex_store
from frago.session.models import AgentType
from frago.session.storage import get_session_base_dir

logger = logging.getLogger(__name__)

RAW_FILENAME = "raw.jsonl"


@dataclass
class CodexSyncResult:
    """备份结果。字段语义与另外两家的同名结构对齐。"""

    synced: int = 0  # 新备份的会话数
    updated: int = 0  # 有新内容、增量追加的
    skipped: int = 0  # 无变化跳过的
    errors: list[str] = field(default_factory=list)


def raw_backup_path(session_id: str) -> Path:
    """这个会话的副本落在哪。"""
    return get_session_base_dir() / AgentType.CODEX.value / session_id / RAW_FILENAME


def _line_count(path: Path) -> int:
    """文件里有多少行——它自己就是账本。"""
    if not path.exists():
        return 0
    with open(path, "rb") as fh:
        return sum(1 for _ in fh)


def sync_codex_session(meta: codex_store.RolloutMeta) -> str | None:
    """备份单个会话。有实质变化时返回 session_id，无变化返回 None。"""
    try:
        source_lines = meta.path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise RuntimeError(f"rollout 读不出来: {exc}") from exc

    backup = raw_backup_path(meta.session_id)
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

    if action == "unchanged":
        return None

    logger.info(
        "Backed up codex session: %s (%s, %d records)",
        meta.session_id,
        action,
        len(source_lines),
    )
    return meta.session_id


def sync_codex_sessions(
    *, since_mtime_cache: dict[str, float] | None = None
) -> CodexSyncResult:
    """把本机全部 codex 会话备份进 frago 会话存储。幂等。

    Args:
        since_mtime_cache: 可选的内存缓存（session_id → 上次见到的 mtime）。作用等同
            claude 同步里的 mtime 缓存：没动过的会话在任何磁盘读之前就跳过。

    Returns:
        备份结果。codex 没装时是一份空结果，NEVER 抛。
    """
    result = CodexSyncResult()
    if not codex_store.sessions_root().is_dir():
        logger.debug("codex sessions directory absent, nothing to sync")
        return result

    for meta in codex_store.list_sessions():
        try:
            cached = (
                since_mtime_cache.get(meta.session_id)
                if since_mtime_cache is not None
                else None
            )
            if cached is not None and meta.mtime <= cached:
                result.skipped += 1
                continue

            existed = raw_backup_path(meta.session_id).exists()
            synced_id = sync_codex_session(meta)
            if since_mtime_cache is not None:
                since_mtime_cache[meta.session_id] = meta.mtime
            if synced_id is None:
                result.skipped += 1
            elif existed:
                result.updated += 1
            else:
                result.synced += 1
        except Exception as exc:  # noqa: BLE001 — 一个会话坏掉 NEVER 拖垮整批
            message = f"Sync failed {meta.session_id}: {exc}"
            logger.warning(message)
            result.errors.append(message)

    if result.synced or result.updated or result.errors:
        logger.info(
            "codex sync complete: synced=%d, updated=%d, skipped=%d, errors=%d",
            result.synced,
            result.updated,
            result.skipped,
            len(result.errors),
        )
    return result
