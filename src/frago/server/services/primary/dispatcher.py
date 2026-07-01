"""PA 队列路由 / 按 conv 并发派发（Phase 4 抽出）。

接 svc 首参的自由函数，跨方法调用走 svc.<method>。行为与原 PrimaryAgentService.
_queue_consumer_loop / _ensure_conv_worker / _conv_worker_loop 逐字一致（self → svc）。
核心 _dispatch_group_tmux 仍在门面（经 svc 调用）。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def queue_consumer_loop(svc: Any) -> None:
    """Router loop: drain queue, derive conv_key, fan out to per-conv workers.

    Phase 4 (删 claude-p): the resident tmux session IS the PA.去喂料门后这里
    从「串行派发」改成「路由分发」：把每条消息按 conv_key 路由到各自的子队列，
    每个 conv 一条独立 worker 协程串行处理（保序）但跨 conv 并发——一个 conv 跑
    长回合（含「先回稍等、后台 worker 续干」）不再阻塞其他 conv 的派发与回复。
    投递仍由 transcript 持续转发器逐 conv 独立完成，与本路由解耦。
    """
    logger.info("PA queue router started (per-conv concurrent dispatch)")
    while True:
        try:
            first = await svc._message_queue.get()
            await asyncio.sleep(0.1)

            messages = [first]
            while not svc._message_queue.empty():
                try:
                    messages.append(svc._message_queue.get_nowait())
                except asyncio.QueueEmpty:
                    break

            # Resolve conv_key for each message, group by conv_key.
            from collections import defaultdict
            grouped: dict[str | None, list[dict]] = defaultdict(list)
            for m in messages:
                tid = svc._resolve_thread_id(m)
                svc._set_msg_thread_id(m, tid)
                grouped[tid].append(m)

            # 路由到各 conv 的子队列，并确保该 conv 有 worker 在跑。
            for tid, group in grouped.items():
                q = svc._conv_queues.get(tid)
                if q is None:
                    q = asyncio.Queue()
                    svc._conv_queues[tid] = q
                q.put_nowait(group)
                svc._ensure_conv_worker(tid)

        except asyncio.CancelledError:
            logger.info("PA queue router cancelled")
            raise
        except Exception:
            logger.exception("Queue router error")
            await asyncio.sleep(1)


def ensure_conv_worker(svc: Any, tid: str | None) -> None:
    """确保该 conv 有一条活 worker 协程；已死/不存在则（重）建。"""
    t = svc._conv_workers.get(tid)
    if t is None or t.done():
        svc._conv_workers[tid] = asyncio.create_task(svc._conv_worker_loop(tid))


async def conv_worker_loop(svc: Any, tid: str | None) -> None:
    """单个 conv 的 worker：串行消费本 conv 子队列，逐组 ``_dispatch_group_tmux``。

    闲置超阈值自行退出回收 worker，子队列保留供下条消息复用（NEVER 删队列，
    避免与 router 的 put 竞态丢消息）；退出后下条路由到该 conv 时由
    ``_ensure_conv_worker`` 的 done 分支重建。
    """
    q = svc._conv_queues[tid]
    idle_exit_s = 300.0
    while True:
        try:
            try:
                group = await asyncio.wait_for(q.get(), timeout=idle_exit_s)
            except TimeoutError:
                if q.empty():
                    svc._conv_workers.pop(tid, None)
                    return
                continue
            await svc._dispatch_group_tmux(tid, group)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("conv worker error (thread=%s)", tid)
            await asyncio.sleep(1)


# ── 真空闲判定（喂料门 + 回收共用）+ runner 懒构造 ──────────────────────────


def is_truly_idle(svc: Any, session_key: str) -> bool:
    """该 key 的常驻会话当前是否真空闲（四信号缺一不可）。无活会话视为空闲。"""
    runner = svc._pa_tmux_runner
    if runner is None:
        return True
    session = runner.session(session_key)
    if session is None:
        return True
    from frago.agent_driver.drivers.claude import is_truly_idle as _is_idle

    return _is_idle(
        session, silence_s=float(svc._watch_config["idle_silence_seconds"])
    )


async def wait_until_truly_idle(svc: Any, session_key: str) -> None:
    """等到该会话真空闲再返回（喂料门 / 回合收尾用）。

    给足够大的上限 + 超时日志，别死等一个永远不空闲的会话。无活会话立即返回。
    """
    runner = svc._pa_tmux_runner
    if runner is None or runner.session(session_key) is None:
        return
    max_wait = float(svc._watch_config["feeding_gate_max_seconds"])
    poll = float(svc._watch_config["idle_poll_seconds"])
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max_wait
    while True:
        if await asyncio.to_thread(svc._is_truly_idle, session_key):
            return
        if loop.time() >= deadline:
            logger.warning(
                "feeding gate: waited %.0fs for conv=%s to go truly idle, "
                "proceeding anyway", max_wait, session_key,
            )
            return
        await asyncio.sleep(poll)


async def dispatch_group_tmux(
    svc: Any,
    tid: str | None,
    group: list[dict],
    fallback_key: str,
    system_prompt: str,
) -> None:
    """Feed a message group to PA's resident session; delivery is decoupled (Phase 6).

    喂 prompt + 等到真空闲再 return——本方法不再负责投递。投递的唯一来源是
    transcript 持续转发器；ok 分支 NEVER 自己 deliver（否则与转发器双投）。
    """
    from frago.telemetry.trace import trace_entry

    for _m in group:
        if not isinstance(_m, dict):
            continue
        _mtype = _m.get("type", "")
        _channel = _m.get("channel", "") or _mtype
        trace_entry(
            origin="internal",
            subkind="pa",
            data_type="message",
            thread_id=_m.get("thread_id"),
            parent_id=None,
            task_id=_m.get("task_id"),
            data={"queue_msg_type": _mtype, "channel": _m.get("channel")},
            msg_id=_m.get("msg_id"),
            role="pa",
            event=f"收到消息队列: {_channel}",
        )

    merged = svc._format_queue_messages(group)
    bootstrap, _ = svc._build_bootstrap_prompt(
        thread_id=tid, create_reason="message_dispatch"
    )
    full_bootstrap = system_prompt + "\n\n" + bootstrap
    session_key = tid or fallback_key

    # 真实 conv_key（非 None / 非 __fallback__）这条路径：把它提到 warm_convs 最前、
    # 去重、截断到上限并持久化，供 server 重启后预热——消首句冷启动。
    if tid:
        svc._record_warm_conv(tid)

    runner = svc._get_pa_tmux_runner()
    input_len = len(merged)
    logger.info(
        "Queue consumer [tmux]: sending %d merged messages to PA (thread=%s, %d chars)",
        len(group), tid, len(merged),
    )

    from frago.agent_driver.tmux_session import TmuxStartupError

    # on_ready：bootstrap 注入后、真实 prompt 提交前锚定转发器 baseline。期间把
    # conv 标记 bootstrapping，转发器跳过该 conv，规避「bootstrap 回复被当新终答
    # 抢先投出」的竞态；seed 完成即清标记，转发器恢复盯本轮终答。
    if tid:
        svc._bootstrapping_convs.add(tid)

    def _on_ready(_key: str) -> None:
        svc._seed_marker(tid)
        if tid:
            svc._bootstrapping_convs.discard(tid)

    try:
        result = await asyncio.to_thread(
            runner.run, session_key, merged,
            bootstrap=full_bootstrap, on_ready=_on_ready,
        )
    except TmuxStartupError:
        logger.exception(
            "PA tmux session failed to start (thread=%s); dropping this round "
            "to avoid infinite re-enqueue", tid,
        )
        if tid:
            svc._bootstrapping_convs.discard(tid)
        return
    except Exception:
        logger.exception("PA tmux run failed (thread=%s), re-enqueueing group", tid)
        if tid:
            svc._bootstrapping_convs.discard(tid)
        for m in group:
            await svc._message_queue.put(m)
        return

    text = result.text or ""

    # Token accounting drives rotation (rough char/4 estimate).
    estimated_tokens = (input_len + len(text)) // 4
    if tid:
        svc._total_turns[tid] = svc._total_turns.get(tid, 0) + 1
        svc._accumulated_tokens[tid] = svc._accumulated_tokens.get(tid, 0) + estimated_tokens
    else:
        svc._fallback_total_turns += 1
        svc._fallback_accumulated_tokens += estimated_tokens

    # Phase 1: 撞上阻断门（认证墙 / agent 自抛的选择菜单）。
    if result.status == "needs_input":
        logger.info(
            "Queue consumer [tmux]: PA needs_input at blocking gate (thread=%s)", tid
        )
        svc._suspended_convs.add(tid)
        await svc._deliver_needs_input(tid, group, result.raw_delta)
        return

    svc._suspended_convs.discard(tid)

    # Phase 6: ok 分支 NEVER 自己 deliver——投递已交给 transcript 持续转发器。
    runner_text_logged = len(text)
    logger.info(
        "Queue consumer [tmux]: turn fed; delivery deferred to watcher "
        "(first-end_turn %d chars, thread=%s)", runner_text_logged, tid,
    )
    svc._writeback_schedules(group)

    # 等到真空闲再收尾：确保本轮（含异步续干）全部落定、转发器已投，再考虑轮换。
    await svc._wait_until_truly_idle(session_key)

    # Rotation is token-driven; Phase 7: 就地驱动 /compact 真压上下文、会话保活。
    if svc._should_rotate(tid):
        await svc._compact_tmux_session(tid)


# ── conv_key 路由 + scheduled 回写 + needs_input 阻断门（Phase 4） ────────────

import re as _re

# Phase 1: 阻断门可见 pane → "需要你选/确认"回复文本。raw_delta 在 needs_input
# 分支下是整屏可见 pane（含 TUI 边框/页脚 chrome），抠掉纯装饰行只留菜单/问题。
_GATE_CHROME = _re.compile(
    r"^\s*(?:[╭╮╯╰│─┌┐└┘├┤┬┴┼]+\s*$|[╭╮╯╰┌┐└┘├┤┬┴┼].*"
    r"|—\s*for shortcuts|esc to interrupt|⏵|\?\s+for shortcuts)",
)


def resolve_thread_id(msg: dict) -> str | None:
    """Resolve which resident session a queue message routes to (Phase 3: conv_key).

    去账本后路由退化成纯 conv_key：入站消息在 ingestion 时已派生 ``conv_key``
    并随消息携带；这里直接读它。无 conv_key（scheduled / internal / reflection
    等无会话单元的消息）返回 None → 路由到 fallback 常驻会话。
    """
    conv_key = msg.get("conv_key")
    if conv_key:
        return str(conv_key)
    # 兼容旧字段名 thread_id（worker_done / 内部消息可能仍带）。
    tid = msg.get("thread_id")
    return str(tid) if tid else None


def set_msg_thread_id(msg: dict, thread_id: str | None) -> None:
    """Backfill thread_id on msg dict for downstream tracing."""
    if thread_id is not None:
        msg["thread_id"] = thread_id


def writeback_schedules(svc: Any, group: list[dict]) -> None:
    """Mark scheduled_task entries in this group as handled after a turn.

    Phase 2: with the JSON decision protocol gone, schedule status no longer
    keys off run/reply actions. A delivered turn that consumed a scheduled_task
    marks that schedule ``dispatched`` so the scheduler doesn't see it as stuck.
    """
    if not svc._scheduler_service:
        return
    for m in group:
        if not isinstance(m, dict):
            continue
        sid = svc._schedule_msg_map.pop(m.get("msg_id", ""), None)
        if sid:
            svc._scheduler_service.update_schedule_result(sid, "dispatched")


def format_needs_input_prompt(raw_delta: str) -> str:
    lines = [
        ln.strip(" │").rstrip()
        for ln in (raw_delta or "").splitlines()
        if ln.strip() and not _GATE_CHROME.match(ln)
    ]
    menu = "\n".join(ln for ln in lines if ln).strip()
    if not menu:
        return "需要你确认才能继续，请回复你的选择。"
    return f"需要你选择 / 确认才能继续：\n\n{menu}"


async def deliver_needs_input(
    svc: Any, tid: str | None, group: list[dict], raw_delta: str
) -> None:
    """把阻断门提示作为一条普通回复投递回触发该轮的渠道。"""
    text = svc._format_needs_input_prompt(raw_delta)
    route = svc._route_for_group(group)
    channel = route.get("channel", "") or route.get("type", "")
    if not channel:
        logger.warning(
            "needs_input gate hit but no channel to reply (thread=%s); dropping prompt", tid
        )
        return
    await svc.deliver(text, route)
