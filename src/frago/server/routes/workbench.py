"""会话工作台的三个只读接口（spec 20260729-session-workbench-webui Phase 2）。

这一层只做取用与序列化：把 :mod:`frago.session.record_reader` 给的数据类拍成 JSON，
把它抛的异常翻成状态码。记录归类、字段推导、家族判定这些全在核心数据层做完了，
本模块 NEVER 重做一遍——重做两份判据迟早会各走各的。

与 ``/api/claude-sessions`` 系列井水不犯河水：那条路背后有正在跑的 React 页面，
本模块另起 ``/api/workbench`` 前缀，两边各读各的。

分层：服务层。可以 import ``session/``，NEVER import ``cli/``。
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from frago.session import record_reader
from frago.session.record_reader import DEFAULT_LIMIT, UnknownSessionFamily

router = APIRouter()


@router.get("/workbench/sessions")
async def list_workbench_sessions() -> list[dict[str, Any]]:
    """两家的会话合并成一份清单，按最后活动时刻倒序。

    每条卡片带四档状态与两格摘要（已完成 / 卡在）。这三样在核心数据层跟会话索引一起算、
    一起缓存，本模块一个字都不推导——判据摆在两处迟早各走各的。「要你做」那一格判不出来，
    连字段都不给。

    落盘扫描是同步的，丢进工作线程跑，免得清单一慢整个事件循环跟着停。
    """
    cards = await asyncio.to_thread(record_reader.list_sessions)
    return [asdict(card) for card in cards]


@router.get("/workbench/sessions/{sid}/records")
async def read_workbench_records(
    sid: str,
    after: int = Query(0, description="本批第一条的 seq，闭区间起点"),
    limit: int = Query(
        DEFAULT_LIMIT,
        description=f"本批最多几条。默认 {DEFAULT_LIMIT}，超过 {record_reader.MAX_LIMIT} 一律截到上限",
    ),
    tail: bool = Query(False, description="为真时忽略 after，取整场最后 limit 条"),
) -> list[dict[str, Any]]:
    """取这场会话从 ``after`` 起的统一记录；``tail`` 为真时取整场最后 ``limit`` 条。

    ``limit`` 越界不报错，直接截到 :data:`~frago.session.record_reader.MAX_LIMIT`——
    界面传大了是它自己的事，服务端不该因此把这一屏内容整个扣下。截断本身由核心数据层
    执行，这里一个数字都不算，NEVER 在两处各写一遍上限。

    会话编号两家的形状都不像时回 404，NEVER 猜一家试试。
    """
    try:
        records = await asyncio.to_thread(record_reader.read_records, sid, after, limit, tail)
    except UnknownSessionFamily as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    # Lazily start file watching for this session's project so that
    # subsequent record deltas are pushed via WebSocket instead of polling.
    _ensure_watching(sid)

    return [asdict(record) for record in records]


@router.get("/workbench/records/{rid}/raw")
async def read_workbench_record_raw(
    rid: str,
    session_id: str = Query(..., description="这条记录属于哪一场会话"),
) -> dict[str, Any]:
    """取单条记录的原文。

    **报错类恒 403。** 那条原文的响应头里带着 Cloudflare 的登录凭据，服务端直接拒，
    NEVER 靠前端自觉不去点。上游对报错类返回空，这里把空翻成 403 而不是 200 加空值——
    200 加空值会让界面以为「这条没原文」而照常展开，判断权就又回到了前端手上。

    取不到的记录同样回 403 而不是 404：只有拿到原文才算放行，其余一律不放行。
    """
    try:
        raw = await asyncio.to_thread(record_reader.read_raw, session_id, rid)
    except UnknownSessionFamily as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    if raw is None:
        raise HTTPException(status_code=403, detail=f"记录 {rid} 的原文不予提供")
    return raw


# ── internal helpers ─────────────────────────────────────────────────


def _ensure_watching(session_id: str) -> None:
    """Trigger lazy file watching for the project of *session_id*.

    Claude Code sessions (UUID-shaped) start a ``SessionStream`` per project;
    opencode sessions (``ses_`` prefix) start a shared ``OpencodeStream``.
    """
    try:
        from frago.server.services.workbench_stream_bridge import (
            WorkbenchStreamBridge,
        )

        bridge = WorkbenchStreamBridge.get_instance()
        bridge.ensure_watching(session_id)
    except Exception:
        import logging

        logging.getLogger(__name__).warning(
            "Failed to start workbench watching for %s", session_id, exc_info=True
        )
