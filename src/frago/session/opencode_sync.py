"""把 opencode 会话库里的会话备份进 frago 会话存储（spec 20260725 Phase 3）。

与 ``session/sync.py``（claude 的同类实现）同构：只做备份，不做解读。差别只在数据
来源——claude 读 ``~/.claude/projects`` 下的 JSONL 文件，这里读 opencode 的 SQLite
会话库。落点是 ``~/.frago/sessions/opencode/<session_id>/raw.jsonl``，一行一个原始
片段，与 claude 侧同构。

备份范围是**库里的全部会话**，不只是 frago 驱动过的那些：claude 侧读的是整个
``~/.claude/projects``，同样包含用户自己敲起来的会话，两个内核的行为要一致。

备份文件就是账本：已经备到第几个片段，看它自己有多少行，不另记偏移。每轮拿库里
的片段总数与它一比，决定追加、重来还是不动。片段按创建时间排且历史不重排，所以
行数是稳定的游标。

硬约束：
- 数据库只读，NEVER 写。
- 库不存在（用户没装 opencode）返回空结果，NEVER 抛。
- 片段取 ``opencode_store.session_parts`` 的原始 ``part``，不经展示层的过滤。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from frago.session import opencode_store
from frago.session.models import AgentType
from frago.session.storage import get_session_base_dir

logger = logging.getLogger(__name__)

RAW_FILENAME = "raw.jsonl"


@dataclass
class OpencodeSyncResult:
    """备份结果。字段语义与 claude 侧的 ``SyncResult`` 对齐。"""

    synced: int = 0  # 新备份的会话数
    updated: int = 0  # 有新内容、增量追加的
    skipped: int = 0  # 无变化跳过的
    errors: list[str] = field(default_factory=list)


def raw_backup_path(session_id: str) -> Path:
    """这个会话的副本落在哪。"""
    return get_session_base_dir() / AgentType.OPENCODE.value / session_id / RAW_FILENAME


def _backed_up_lines(backup: Path) -> int:
    """备份文件里已有多少个片段——它自己就是账本。"""
    if not backup.exists():
        return 0
    with open(backup, "rb") as fh:
        return sum(1 for _ in fh)


def sync_opencode_session(row: opencode_store.OpencodeSessionRow) -> str | None:
    """备份单个会话。有实质变化时返回 session_id，无变化返回 None。"""
    session_id = row.session_id

    # 原始片段，不走 ``part_payloads``：那一层为展示服务，会丢掉 synthetic 片段与
    # reasoning，还会把 frago-hook 注入从用户正文里剥掉。备份要的是库里本来的样子，
    # 和 claude 侧一致（那边的附件记录同样原样留着）。
    payloads = [item["part"] for item in opencode_store.session_parts(session_id)]

    backup = raw_backup_path(session_id)
    backed_up = _backed_up_lines(backup)

    if len(payloads) < backed_up:
        # 库里比我们手上的还短：这个会话被重写过，手上那份是一个已经不存在的版本。
        offset, mode, action = 0, "w", "rewritten"
    elif len(payloads) > backed_up:
        offset, mode, action = backed_up, "a", "created" if backed_up == 0 else "appended"
    else:
        offset, mode, action = 0, None, "unchanged"

    if mode is not None:
        backup.parent.mkdir(parents=True, exist_ok=True)
        with open(backup, mode, encoding="utf-8") as fh:
            for payload in payloads[offset:]:
                fh.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")

    if action == "unchanged":
        return None

    logger.info(
        "Backed up opencode session: %s (%s, %d parts)", session_id, action, len(payloads)
    )
    return session_id


def sync_opencode_sessions(
    *, since_updated_cache: dict[str, int] | None = None
) -> OpencodeSyncResult:
    """把会话库里的全部 opencode 会话备份进 frago 会话存储。幂等。

    Args:
        since_updated_cache: 可选的内存缓存（session_id → 上次见到的 ``time_updated``）。
            作用等同 claude 同步里的 mtime 缓存：没动过的会话在任何磁盘读之前就跳过。

    Returns:
        备份结果。库不存在时是一份空结果，NEVER 抛。
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

            existed = raw_backup_path(row.session_id).exists()
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
