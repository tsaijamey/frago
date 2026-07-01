"""PA 生命周期相关的无状态配置 helper（Phase 4 抽出）。

这些函数原是 PrimaryAgentService 上不依赖任何实例状态的配置读写方法，搬来作自由函数。
常量（CONFIG_FILE / *_DEFAULTS / WARM_CONVS_MAX / fallback_key）由调用方（门面）传入，
避免与 primary_agent_service.py 循环导入。行为与原方法逐字一致。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def load_watch_config(config_file: Path, defaults: dict[str, Any]) -> dict[str, Any]:
    """Load Phase 6 transcript-watch / idle config from config.json."""
    try:
        if config_file.exists():
            raw = json.loads(config_file.read_text(encoding="utf-8"))
            pa = raw.get("primary_agent") or {}
            user = {**(pa.get("watch") or {}), **(pa.get("idle") or {})}
            return {**defaults, **user}
    except (json.JSONDecodeError, OSError):
        pass
    return dict(defaults)


def load_heartbeat_config(config_file: Path, defaults: dict[str, Any]) -> dict[str, Any]:
    """Load heartbeat config from config.json."""
    try:
        if config_file.exists():
            raw = json.loads(config_file.read_text(encoding="utf-8"))
            user_config = (raw.get("primary_agent") or {}).get("heartbeat") or {}
            return {**defaults, **user_config}
    except (json.JSONDecodeError, OSError):
        pass
    return dict(defaults)


def load_warm_convs(config_file: Path) -> list[str]:
    """读 config 里 primary_agent.warm_convs（最近在前的 conv_key 列表）。"""
    try:
        if config_file.exists():
            raw = json.loads(config_file.read_text(encoding="utf-8"))
            convs = (raw.get("primary_agent") or {}).get("warm_convs") or []
            return [str(c) for c in convs if c]
    except (json.JSONDecodeError, OSError):
        pass
    return []


def record_warm_conv(
    conv_key: str, config_file: Path, max_convs: int, fallback_key: str
) -> None:
    """把 conv_key 提到 warm_convs 最前、去重、截断到上限，持久化回 config.json。

    read-modify-write 只改 ``primary_agent.warm_convs`` 一个字段，NEVER 整体覆盖
    把别的字段冲掉。列表无变化（已在最前）时不写盘，避免每次派发都打 IO。
    """
    if not conv_key or conv_key == fallback_key:
        return
    # 只记真实 channel 会话：conv_key 形如 "<已注册channel>:<id>"（feishu:/voice:/
    # email:/slack:）。内部消息的裸 ULID thread_id（反思 tick 等）和无 channel 前缀的
    # 测试夹具值（thread-A）一律不记——否则 warm_convs 会被反思 ULID 持续刷满、把真实
    # 会话挤出去，预热还会白拉一堆空会话。
    from frago.server.services.routing.conv_key import CONV_KEY_DERIVERS

    channel = conv_key.split(":", 1)[0] if ":" in conv_key else ""
    if channel not in CONV_KEY_DERIVERS:
        return
    try:
        raw = (
            json.loads(config_file.read_text(encoding="utf-8"))
            if config_file.exists()
            else {}
        )
    except (json.JSONDecodeError, OSError):
        return
    if not isinstance(raw, dict):
        return
    pa = raw.get("primary_agent")
    if not isinstance(pa, dict):
        pa = {}
    old = [str(c) for c in (pa.get("warm_convs") or []) if c]
    new = [conv_key] + [c for c in old if c != conv_key]
    new = new[:max_convs]
    if new == old:
        return
    pa["warm_convs"] = new
    raw["primary_agent"] = pa
    try:
        config_file.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        logger.debug("warm_convs persist failed", exc_info=True)


# ── Heartbeat / idle-eviction runtime (Phase 4) ──────────────────────────────
# 接 svc 首参的自由函数；跨方法调用一律走 svc.<method>（保持与门面委托一致）。
# 行为与原 PrimaryAgentService._{start,stop}_heartbeat / _heartbeat_loop /
# _send_heartbeat / _evict_idle_sessions 逐字一致（self → svc）。


async def start_heartbeat(svc: Any) -> None:
    config = svc._load_heartbeat_config()
    if not config.get("enabled", True):
        logger.info("PA heartbeat disabled by config")
        return

    svc._heartbeat_stop.clear()
    svc._heartbeat_task = asyncio.create_task(
        svc._heartbeat_loop(
            interval=config["interval_seconds"],
            initial_delay=config["initial_delay_seconds"],
        )
    )
    logger.info("PA heartbeat started (interval=%ds)", config["interval_seconds"])


async def stop_heartbeat(svc: Any) -> None:
    if svc._heartbeat_task is None or svc._heartbeat_task.done():
        return
    svc._heartbeat_stop.set()
    svc._heartbeat_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await svc._heartbeat_task
    svc._heartbeat_task = None
    logger.info("PA heartbeat stopped")


async def heartbeat_loop(svc: Any, interval: int, initial_delay: int) -> None:
    logger.info("Heartbeat loop: waiting %ds initial delay", initial_delay)
    await asyncio.sleep(initial_delay)
    logger.info("Heartbeat loop: starting main loop")
    while not svc._heartbeat_stop.is_set():
        try:
            await svc._send_heartbeat()
        except Exception:
            logger.exception("Heartbeat failed")
        try:
            await asyncio.wait_for(
                svc._heartbeat_stop.wait(), timeout=interval
            )
            break
        except TimeoutError:
            continue


async def send_heartbeat(svc: Any) -> None:
    """Heartbeat: keep the queue consumer alive + idle rotation check.

    Phase 4: with the resident tmux backend as the sole path, turn accounting
    and rotation happen inline in ``_dispatch_group_tmux``. The heartbeat only
    resurrects a dead consumer task and triggers idle rotation for any conv
    whose token window crossed the threshold while sitting quiet.
    """
    logger.info("Heartbeat [%d]: tick", svc._heartbeat_seq)

    if svc._queue_consumer_task is None or svc._queue_consumer_task.done():
        if svc._queue_consumer_task and svc._queue_consumer_task.done():
            exc = svc._queue_consumer_task.exception() if not svc._queue_consumer_task.cancelled() else None
            logger.error(
                "Queue consumer task died (exc=%s), restarting",
                exc,
            )
        svc._queue_consumer_task = asyncio.create_task(svc._queue_consumer_loop())
        logger.info("Queue consumer task restarted by heartbeat [%d]", svc._heartbeat_seq)

    if svc._busy:
        logger.debug("Heartbeat skipped: PA is busy")
        return

    # Idle rotation check: iterate all conv keys with accrued token counters.
    for tid in list(svc._accumulated_tokens.keys()):
        if svc._should_rotate(tid):
            await svc._compact_tmux_session(tid)
    if svc._should_rotate(None):
        await svc._compact_tmux_session(None)

    # Phase 6: 周期回收真空闲超阈值的常驻会话（关 tmux）。仅当真空闲才参与回收，
    # 在跑活的会话返回 None 永不回收；回收后再来消息走 Phase 5 --resume 接回。
    await svc._evict_idle_sessions()

    # 去账本：不再 recover board pending tasks，也不再托管 executor 回路。
    # 会话按需建；跨重启连续性交给 claude 原生 transcript。
    svc._heartbeat_seq += 1


async def evict_idle_sessions(svc: Any) -> None:
    """heartbeat 周期回收真空闲超阈值的常驻会话。

    idle_age_fn：仅当会话真空闲（四信号成立）且能取到 transcript 终结时间戳时，
    才以「自该时间戳起的静默秒数」计；仍在干活 / 无锚点返回 None → NEVER 回收。
    """
    runner = svc._pa_tmux_runner
    if runner is None:
        return
    from datetime import UTC

    from frago.agent_driver.drivers.claude import is_truly_idle

    silence = float(svc._watch_config["idle_silence_seconds"])
    timeout_s = float(svc._watch_config["idle_evict_seconds"])
    now = datetime.now(UTC)

    def idle_age(session: Any) -> float | None:
        if not is_truly_idle(session, silence_s=silence):
            return None
        # idle 时长用「会话在本池里自己的最后活动时间」(open/send 刷新)，NEVER 用
        # transcript 时间戳——预热是 --resume 一个旧 transcript，其最后记录可能几小时前，
        # 那样会让刚预热的会话被秒判「闲了几小时」当场回收（预热与回收咬死）。
        last = getattr(session, "last_active_at", None)
        if last is None:
            return None
        return (now - last).total_seconds()

    try:
        evicted = await asyncio.to_thread(
            runner._pool.evict_idle, idle_age, timeout_s
        )
    except Exception:
        logger.debug("PA idle eviction error", exc_info=True)
        return
    for sid in evicted:
        logger.info("PA idle eviction: closed resident session conv=%s", sid)
        # 重置该 key 的轮换计数（与 rotation 一致），下条消息触发干净重建 + resume。
        svc._total_turns.pop(sid, None)
        svc._accumulated_tokens.pop(sid, None)
        svc._last_delivered_marker.pop(sid, None)
        svc._watch_mtime.pop(sid, None)
