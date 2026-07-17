"""PA 会话轮换 / compact / 计数（Phase 4 抽出）。

接 svc 首参的自由函数；模块常量（fallback_key / 轮换阈值）由门面传入，避免与
primary_agent_service.py 循环导入。跨方法调用一律走 svc.<method>（与门面委托一致）。
行为与原 PrimaryAgentService._compact_tmux_session / _reset_rotation_counters /
_rotate_tmux_session / _should_rotate 逐字一致（self → svc）。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def compact_tmux_session(
    svc: Any, thread_id: str | None, fallback_key: str
) -> None:
    """token-rotation 触发时就地驱动常驻会话执行 ``/compact`` 真压上下文（Phase 7）。"""
    is_fallback = thread_id is None
    tag = f"thread={thread_id}" if thread_id else "fallback"
    session_key = thread_id or fallback_key

    count = svc._fallback_rotation_count if is_fallback else svc._rotation_count.get(thread_id, 0)

    runner = svc._get_pa_tmux_runner()

    # 无活会话：无可压缩，直接复位计数（下条消息走 --resume 干净重建）。
    if runner.session(session_key) is None:
        logger.info(
            "PA compact (%s): no live session, resetting counters only", tag
        )
        svc._reset_rotation_counters(thread_id, count)
        return

    # a. 等真空闲——busy 不发 /compact；超时则跳过本次，NEVER 回退 kill。
    await svc._wait_until_truly_idle(session_key)
    if not await asyncio.to_thread(svc._is_truly_idle, session_key):
        logger.warning(
            "PA compact (%s): session not truly idle within window, "
            "skipping this compact (NEVER fall back to kill)", tag,
        )
        return

    logger.info("PA compact (%s, rotation_count=%d): driving /compact in place", tag, count)

    # b. 标记 compacting，转发器跳过该 conv（fallback 无 conv 归属，转发器本就跳过）。
    if thread_id:
        svc._compacting_convs.add(thread_id)
    try:
        # c. 发 /compact + 提交。
        sent = await asyncio.to_thread(runner.compact, session_key)
        if not sent:
            logger.warning("PA compact (%s): session vanished before /compact", tag)
            return
        # d. 等 /compact 完成（再次真空闲）。
        await svc._wait_until_truly_idle(session_key)
        # e. 重锚 baseline + 清 mtime（/compact 产出落在 baseline 之内、绝不转发）。
        svc._seed_marker(thread_id)
        svc._watch_mtime.pop(session_key, None)
    finally:
        if thread_id:
            svc._compacting_convs.discard(thread_id)

    # f. 重置计数，会话保活（NEVER evict）。
    svc._reset_rotation_counters(thread_id, count)


def reset_rotation_counters(svc: Any, thread_id: str | None, count: int) -> None:
    """复位该 conv 的 token/轮次计数并 rotation_count+1（compact / rotation 共用）。"""
    if thread_id is None:
        svc._fallback_total_turns = 0
        svc._fallback_accumulated_tokens = 0
        svc._fallback_rotation_count = count + 1
    else:
        svc._total_turns[thread_id] = 0
        svc._accumulated_tokens[thread_id] = 0
        svc._rotation_count[thread_id] = count + 1


async def rotate_tmux_session(
    svc: Any, thread_id: str | None, fallback_key: str
) -> None:
    """Rotate a resident-tmux PA session: evict it and reset that key's counters.

    No subprocess exists in the tmux backend — rotation just evicts the
    resident session from the warm pool. The next ``run`` for this key
    re-injects bootstrap on a fresh resident session.
    """
    is_fallback = thread_id is None
    tag = f"thread={thread_id}" if thread_id else "fallback"
    session_key = thread_id or fallback_key

    count = svc._fallback_rotation_count if is_fallback else svc._rotation_count.get(thread_id, 0)

    logger.info("PA tmux session rotation (%s, rotation_count=%d)", tag, count)

    try:
        svc._get_pa_tmux_runner().evict(session_key)
    except Exception:
        logger.debug("PA tmux evict error for %s", tag, exc_info=True)

    if is_fallback:
        svc._fallback_total_turns = 0
        svc._fallback_accumulated_tokens = 0
        svc._fallback_rotation_count = count + 1
    else:
        svc._total_turns[thread_id] = 0
        svc._accumulated_tokens[thread_id] = 0
        svc._rotation_count[thread_id] = count + 1


def should_rotate(
    svc: Any,
    thread_id: str | None,
    turn_threshold: int | None,
    token_threshold: int,
) -> bool:
    """Check if session rotation is needed for a given thread.

    ``thread_id=None`` checks fallback session.
    """
    if thread_id is None:
        turns = svc._fallback_total_turns
        tokens = svc._fallback_accumulated_tokens
    else:
        turns = svc._total_turns.get(thread_id, 0)
        tokens = svc._accumulated_tokens.get(thread_id, 0)
    if turn_threshold is not None and turns >= turn_threshold:
        return True
    return tokens >= token_threshold
