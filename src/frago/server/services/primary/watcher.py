"""PA transcript 持续转发器（Phase 4 抽出）。

接 svc 首参的自由函数；fallback 常量由门面传入，跨方法调用走 svc.<method>。行为与原
PrimaryAgentService._eval_conv_transcript / _watch_poll / _seed_marker /
_transcript_watch_loop / _watch_tick 逐字一致（self → svc）。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def eval_conv_transcript(svc: Any, conv_key: str) -> Any | None:  # noqa: ARG001 — uniform svc-first signature
    """读该 conv 常驻会话的 claude transcript，返回 TurnCompletion（无则 None）。

    定位走 ``locate_transcript(uuid5(conv_key), cwd=$HOME)``——与 claude driver
    的 completion_probe 同一套派生，路径在起会话那刻就锁定。
    """
    from frago.agent_driver.drivers.claude import _claude_session_uuid
    from frago.session.transcript_completion import (
        evaluate_file,
        locate_transcript,
    )

    sid = _claude_session_uuid(conv_key)
    path = locate_transcript(sid, cwd=str(Path.home()))
    if path is None:
        return None
    return evaluate_file(path)


def watch_poll(
    svc: Any, conv_key: str, since_mtime: float | None  # noqa: ARG001 — uniform svc-first signature
) -> tuple[float | None, Any | None]:
    """转发器专用：stat transcript，mtime 没变就跳过全量解析（省每拍重读几 MB）。

    返回 ``(mtime, TurnCompletion | None)``：mtime 与上拍相同 → ``(mtime, None)``
    不解析；变了 / 首次 → 全量 ``evaluate_file``；文件不存在 → ``(None, None)``。
    stat 是微秒级，evaluate 是 O(文件大小)（十几 MB ~ 几十 ms），故空闲期只付 stat。
    """
    import os as _os

    from frago.agent_driver.drivers.claude import _claude_session_uuid
    from frago.session.transcript_completion import (
        evaluate_file,
        locate_transcript,
    )

    sid = _claude_session_uuid(conv_key)
    path = locate_transcript(sid, cwd=str(Path.home()))
    if path is None:
        return None, None
    try:
        mtime = _os.path.getmtime(path)
    except OSError:
        return None, None
    if since_mtime is not None and mtime <= since_mtime:
        return mtime, None  # 未变，跳过全量解析
    return mtime, evaluate_file(path)


def seed_marker(svc: Any, conv_key: str | None) -> None:
    """把该 conv 的 last_delivered_marker 锚到 transcript 当前 tail（baseline）。

    喂真实 prompt 之前调用：bootstrap 那一轮（及 --resume 载回的历史）的终结
    marker 都落在 baseline 之内，转发器只投 baseline 之后新增的终答。
    """
    if not conv_key:
        return
    tc = svc._eval_conv_transcript(conv_key)
    svc._last_delivered_marker[conv_key] = tc.last_uuid if tc else None


async def transcript_watch_loop(svc: Any) -> None:
    """每个常驻 PA 会话的 transcript 持续转发器（单任务轮询全部活会话）。

    把「投递」从「喂的那一轮」解耦：PA 常「先回一句稍等、再用自己的 harness 异步
    续干」，真正完整结果在第一个 end_turn 之后才写进同一 transcript。本循环持续
    盯每个活会话的 transcript，每出现一条新的、答完的 assistant 终答就投递、推进
    marker，每个 marker 只投一次。NEVER 转发 user 记录 / 工具调用 / thinking /
    流式半截——只投 evaluate_file 判 done 的终答。
    """
    interval = float(svc._watch_config["watch_interval_seconds"])
    logger.info("PA transcript watcher started (interval=%.1fs)", interval)
    while True:
        try:
            await asyncio.sleep(interval)
            await svc._watch_tick()
        except asyncio.CancelledError:
            logger.info("PA transcript watcher cancelled")
            raise
        except Exception:
            logger.exception("PA transcript watcher tick error")


async def watch_tick(svc: Any, fallback_key: str) -> None:
    """转发器一拍：遍历活会话，投递每条新终答。"""
    runner = svc._pa_tmux_runner
    if runner is None:
        return
    for key in runner.active_session_keys():
        if key == fallback_key:
            continue  # fallback 无 conv 归属，无处投递
        conv_key = key
        if conv_key in svc._bootstrapping_convs or conv_key in svc._compacting_convs:
            continue  # baseline 未锚定 / 正在 /compact，跳过本拍避免误投该轮产出
        route = svc._conv_route_cache.get(conv_key)
        if not route:
            continue
        since = svc._watch_mtime.get(conv_key)
        mtime, tc = await asyncio.to_thread(svc._watch_poll, conv_key, since)
        if mtime is not None:
            svc._watch_mtime[conv_key] = mtime
        if tc is None or not tc.done:
            continue  # 文件没变（stat 短路，未解析）/ 解析了但本轮未答完
        marker = tc.last_uuid
        if not marker or svc._last_delivered_marker.get(conv_key) == marker:
            continue  # 无新终答 / 已投过该 marker
        # 推进 marker 后再投：投递失败不回退 marker，避免失败重投把同一终答刷屏。
        svc._last_delivered_marker[conv_key] = marker
        text = (tc.final_text or "").strip()
        if text:
            logger.info(
                "Transcript watcher: delivering new终答 (%d chars, conv=%s)",
                len(text), conv_key,
            )
            await svc.deliver(text, route)
