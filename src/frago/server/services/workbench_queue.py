"""会话工作台的消息队列（per-session message queue）。

作用与边界：
1. **不在 agent 执行过程中把消息塞进其原生运行队列**（Claude Code 的 tmux 实时插话队列或
   CoreAgent 的 stdin 中途插话），因为实践证明中途插话会打断 agent 正在执行的流程。
2. 当会话正在执行（或队列中已有待发消息、或用户把消息加入队列）时，消息堆积到 frago 会话自有的
   持久化队列（``~/.frago/sessions/<family>/<sid>/workbench-queue.json``）中。
3. **自动注入条件**：当且仅当会话已停止（``stop``）且检测到含实际内容（如 assistant response 文本）的 stop 轮次出现后，
   其最后一轮实际内容会话没有未作答的交互卡，才自动从队列头部取出最早的那一条消息注入会话，并从队列中删除该消息。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None  # type: ignore[assignment]

from frago.server.services.schedule_pending import _extract_ui_component_dict, card_in
from frago.session.unified_record import UnifiedRecord

logger = logging.getLogger(__name__)

QUEUE_FILENAME = "workbench-queue.json"
QUEUE_LOCK_FILENAME = "workbench-queue.lock"
INJECT_LOCK_FILENAME = "workbench-inject.lock"
QUEUE_STATE_FILENAME = "workbench-queue-state.json"

#: 活跃队列索引文件名（落在会话根下：``<会话根>/active-workbench-queues.json``）。
#:
#: **这是一份可随时重建的缓存，不是事实来源。** 它记的是「哪些会话此刻队列非空」，
#: 用来把巡检从「每次扫上万个历史目录」换成「读几百字节」。事实是每个会话目录下那份
#: ``workbench-queue.json``；索引丢了、坏了、或版本对不上，``_seed_queued_sessions_once``
#: 会全盘扫一次重建（``seeded`` 标记就是「这份索引已经由全盘扫描建过一次」）。
#: 删掉它不会丢任何用户数据，最坏后果只是下一次巡检慢一拍。
ACTIVE_QUEUES_FILENAME = "active-workbench-queues.json"
ACTIVE_QUEUES_LOCK_FILENAME = "active-workbench-queues.lock"
QUEUE_VERSION = 1

#: 跨进程注入状态锁的最大保活毫秒数（防止极端情况下进程被 SIGKILL 后残留死锁）。
CROSS_PROCESS_INJECT_STALE_MS = 60_000

MAX_QUEUE_ITEMS = 100
MAX_TEXT = 100_000
MAX_ID = 64

#: 仅检测最后一轮实际内容会话是否存在交互卡。
TAIL_TURN_WINDOW = 1

#: 放送给前端的 WebSocket 消息类型。
WS_SESSION_QUEUE_UPDATE = "session_queue_update"

#: 引擎记账类记录：不单独构成对话轮次，也不代表用户或 agent 的实质发言。
_BOOKKEEPING_KINDS = frozenset(
    {"call.envelope", "session.state", "todo.snapshot", "usage.tick"}
)

_locks_guard = threading.Lock()
_session_locks: dict[str, threading.RLock] = {}
_file_lock_state: dict[str, list[Any]] = {}

#: 正在执行自动注入的会话集合（防止同一时刻并发触发两次 pop）。
_injecting_sessions: set[str] = set()

#: 记录每场会话上一次触发自动注入时的末尾 stop 轮次记录 ID，防止同一轮 stop 连续弹出多条消息。
_last_injected_turn: dict[str, str] = {}

#: 当前队列非空的会话编号集合（由内存态直接维护，避免每次巡检全盘扫描）。
_queued_sessions: set[str] = set()
_seeded_from_disk: bool = False

#: 每场会话的后台静置重试定时器（session_id → Timer），用于跨过 Stop hook 忙碌窗口。
_settle_timers: dict[str, threading.Timer] = {}

#: Stop hook 或驱动层收尾通常持续 1～15 秒；首次 0.8s 探针遇到 not_stopped 时按退避序列继续重试。
SETTLE_RETRY_DELAYS: tuple[float, ...] = (
    1.0,
    1.5,
    2.0,
    2.5,
    3.0,
    4.0,
    4.0,
    5.0,
    5.0,
    5.0,
)

#: 测试或自定义注入器可替换此回调；默认使用 ``session_send.send``。
_sender_override: Callable[[str, str, str | None], Any] | None = None


class QueueError(ValueError):
    """队列请求不合规矩，路由据此返回 400。"""


def _thread_lock_for(session_id: str) -> threading.RLock:
    with _locks_guard:
        lock = _session_locks.get(session_id)
        if lock is None:
            lock = threading.RLock()
            _session_locks[session_id] = lock
        return lock


@contextlib.contextmanager
def _lock_for(session_id: str) -> Iterator[None]:
    """同时获取进程内可重入线程锁与基于会话目录 ``workbench-queue.lock`` 的跨进程文件排他锁。"""
    tlock = _thread_lock_for(session_id)
    with tlock:
        entry = _file_lock_state.get(session_id)
        if entry is None:
            fd: int | None = None
            if fcntl is not None:
                with contextlib.suppress(OSError):
                    d = queue_dir(session_id)
                    d.mkdir(parents=True, exist_ok=True)
                    lock_path = d / QUEUE_LOCK_FILENAME
                    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
                    fcntl.flock(fd, fcntl.LOCK_EX)
            entry = [fd, 1]
            _file_lock_state[session_id] = entry
        else:
            entry[1] += 1
        try:
            yield
        finally:
            entry[1] -= 1
            if entry[1] <= 0:
                _file_lock_state.pop(session_id, None)
                held_fd = entry[0]
                if held_fd is not None:
                    if fcntl is not None:
                        with contextlib.suppress(OSError):
                            fcntl.flock(held_fd, fcntl.LOCK_UN)
                    with contextlib.suppress(OSError):
                        os.close(held_fd)


def _try_acquire_inject_lock(session_id: str) -> int | None:
    """尝试以非阻塞方式获取跨进程注入排他锁（``workbench-inject.lock``）。

    若当前已有其他进程正在向该会话执行终端投喂，立即返回 ``None``；
    在无 ``fcntl`` 的平台上返回 ``-1`` 作为占位符。
    """
    if fcntl is None:
        return -1
    fd: int | None = None
    try:
        d = queue_dir(session_id)
        d.mkdir(parents=True, exist_ok=True)
        lock_path = d / INJECT_LOCK_FILENAME
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except OSError:
        if fd is not None:
            with contextlib.suppress(OSError):
                os.close(fd)
        return None


def _release_inject_lock(fd: int | None) -> None:
    """释放 ``_try_acquire_inject_lock`` 获取的跨进程注入排他锁。"""
    if fd is None or fd < 0:
        return
    if fcntl is not None:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
    with contextlib.suppress(OSError):
        os.close(fd)


@contextlib.contextmanager
def cross_process_inject_guard(session_id: str) -> Iterator[bool]:
    """供外部调用方（如 ``async_dispatch`` 兜底直发路径）使用的非阻塞跨进程注入互斥护栏。"""
    fd = _try_acquire_inject_lock(session_id)
    if fd is None:
        yield False
        return
    try:
        yield True
    finally:
        _release_inject_lock(fd)


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _read_queue_state(directory: Path) -> dict[str, Any]:
    path = directory / QUEUE_STATE_FILENAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_queue_state(directory: Path, state_data: dict[str, Any]) -> None:
    with contextlib.suppress(OSError):
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / QUEUE_STATE_FILENAME
        tmp = target.with_name(f"{QUEUE_STATE_FILENAME}.tmp{os.getpid()}.{uuid.uuid4().hex[:6]}")
        tmp.write_text(json.dumps(state_data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, target)


def get_queue_delivery_receipt(session_id: str) -> dict[str, Any]:
    """读取指定会话的投递回执持久化状态（delivered_items, delivered_job_ids, inflight_item_id 等）。"""
    directory = queue_dir(session_id)
    return _read_queue_state(directory)


def sessions_root() -> Path:
    """所有会话目录的根：``<会话根>``（默认 ``~/.frago/sessions``）。

    **每次现算，不在 import 期算死。** 从前这里是拿一个虚拟会话编号
    （``"__probe__"``）去问 ``session_dir`` 要路径、再上跳两层反推出根目录：为了拿
    一个目录而先构造一场假会话，还依赖 ``session_dir`` 的层级不变。更要紧的是，
    测试里改 ``FRAGO_HOME`` / ``FRAGO_SESSION_DIR`` 时这种「算死的常量」不会跟着走——
    用例以为自己写进了临时目录，实际写到了真人会话目录里（2026-07 那次事故就是这么
    发生的）。现在改成函数式惰性求值：谁调用、按谁此刻的环境算。
    """
    from frago.session.storage import get_session_base_dir

    return get_session_base_dir()


def _sessions_root() -> Path:
    """向后兼容的私有别名；新代码用 :func:`sessions_root`。"""
    return sessions_root()


@contextlib.contextmanager
def _active_queues_file_lock() -> Iterator[None]:
    root = _sessions_root()
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ACTIVE_QUEUES_LOCK_FILENAME
    fd = None
    try:
        if fcntl is not None:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        if fd is not None:
            if fcntl is not None:
                with contextlib.suppress(OSError):
                    fcntl.flock(fd, fcntl.LOCK_UN)
            with contextlib.suppress(OSError):
                os.close(fd)


def _read_active_queues_index_with_meta() -> tuple[set[str], bool]:
    root = _sessions_root()
    path = root / ACTIVE_QUEUES_FILENAME
    if not path.is_file():
        return set(), False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return set(data.get("session_ids") or []), bool(data.get("seeded", False))
        if isinstance(data, list):
            return set(data), False
    except Exception:
        return set(), False
    return set(), False


def _read_active_queues_index() -> set[str]:
    return _read_active_queues_index_with_meta()[0]


def _write_active_queues_index(sids: set[str], *, seeded: bool = False) -> None:
    root = _sessions_root()
    root.mkdir(parents=True, exist_ok=True)
    path = root / ACTIVE_QUEUES_FILENAME
    tmp = path.with_name(f"{ACTIVE_QUEUES_FILENAME}.tmp{os.getpid()}.{uuid.uuid4().hex[:6]}")
    data = {
        "version": 1,
        "session_ids": sorted(sids),
        "seeded": bool(seeded),
        "updated_at_ms": int(time.time() * 1000),
    }
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def register_active_queue_session(session_id: str) -> None:
    """原子将会话加入跨进程活跃队列索引。"""
    if not session_id:
        return
    with _locks_guard:
        _queued_sessions.add(session_id)
    try:
        with _active_queues_file_lock():
            current, is_seeded = _read_active_queues_index_with_meta()
            if session_id not in current:
                current.add(session_id)
                _write_active_queues_index(current, seeded=is_seeded)
    except Exception:
        logger.debug("Failed to register active queue session %s", session_id, exc_info=True)


def unregister_active_queue_session(session_id: str) -> None:
    """原子将已排空且无 inflight 的会话从跨进程活跃队列索引移出。"""
    if not session_id:
        return
    with _locks_guard:
        _queued_sessions.discard(session_id)
    try:
        with _active_queues_file_lock():
            current, is_seeded = _read_active_queues_index_with_meta()
            if session_id in current:
                current.discard(session_id)
                _write_active_queues_index(current, seeded=is_seeded)
    except Exception:
        logger.debug("Failed to unregister active queue session %s", session_id, exc_info=True)


def _is_cross_process_injecting(session_id: str, state_data: dict[str, Any] | None = None) -> bool:
    """检查是否有本进程或其他存活子进程正在向 ``session_id`` 投喂消息。"""
    if session_id in _injecting_sessions:
        return True
    probe_fd = _try_acquire_inject_lock(session_id)
    if probe_fd is None:
        return True
    _release_inject_lock(probe_fd)
    if state_data is None:
        state_data = _read_queue_state(queue_dir(session_id))
    inj_pid = state_data.get("injecting_pid")
    inj_started = state_data.get("injecting_started_at_ms")
    if isinstance(inj_pid, int) and inj_pid > 0:
        now_ms = int(time.time() * 1000)
        started_ms = int(inj_started) if isinstance(inj_started, (int, float)) else 0
        if (now_ms - started_ms) < CROSS_PROCESS_INJECT_STALE_MS and _pid_is_alive(inj_pid):
            return True
    return False


def _cancel_settle_timer(session_id: str) -> None:
    with _locks_guard:
        timer = _settle_timers.pop(session_id, None)
    if timer is not None:
        timer.cancel()


def reset_runtime_state() -> None:
    """清理内存态锁与注入游标（供单元测试隔离使用）。"""
    global _seeded_from_disk
    with _locks_guard:
        timers = list(_settle_timers.values())
        _settle_timers.clear()
        _session_locks.clear()
        _file_lock_state.clear()
        _injecting_sessions.clear()
        _last_injected_turn.clear()
        _queued_sessions.clear()
        _seeded_from_disk = False
    for timer in timers:
        timer.cancel()


def queue_dir(session_id: str) -> Path:
    """该会话的持久化边车目录（与 ``workbench-marks.json`` 同目录）。"""
    from frago.server.services.session_observer import session_dir
    from frago.session.record_reader import detect_family

    family = detect_family(session_id)
    return session_dir(session_id, family)


def empty_queue() -> dict[str, Any]:
    return {"version": QUEUE_VERSION, "items": []}


def _normalize_item(raw: Any, *, from_disk: bool = False) -> dict[str, Any]:
    """把一条原始队列项规整成内部形态。

    ``from_disk=True`` 表示这条是从队列文件里读回来的（可能是 2026-11 之前写下的旧条目），
    此时才允许那条一次性的 ``job_id`` 文本反解迁移；入队路径一律 ``from_disk=False``，
    要求入队方把 ``job_id`` 当结构化字段传进来。
    """
    if not isinstance(raw, dict):
        raise QueueError("队列项必须是对象")
    item_id = str(raw.get("id") or "").strip()
    if not item_id or len(item_id) > MAX_ID:
        raise QueueError("队列项 id 无效")
    text = raw.get("text", "")
    if not isinstance(text, str) or len(text) > MAX_TEXT:
        raise QueueError("队列项 text 无效或超长")
    prompt = raw.get("prompt", text)
    if not isinstance(prompt, str) or not prompt.strip():
        raise QueueError("队列项 prompt 不能为空")
    skills_raw = raw.get("skills") or []
    if not isinstance(skills_raw, list) or not all(isinstance(s, str) for s in skills_raw):
        raise QueueError("队列项 skills 必须是字符串列表")
    image_paths_raw = raw.get("image_paths") or []
    doc_paths_raw = raw.get("doc_paths") or []
    image_paths = [str(p) for p in image_paths_raw if isinstance(p, str)]
    doc_paths = [str(p) for p in doc_paths_raw if isinstance(p, str)]
    attachments = raw.get("attachments")
    if isinstance(attachments, bool) or not isinstance(attachments, int):
        attachments = len(image_paths) + len(doc_paths)
    created_at = raw.get("created_at", 0)
    if isinstance(created_at, bool) or not isinstance(created_at, int):
        created_at = int(time.time() * 1000)
    cwd = raw.get("cwd")
    if cwd is not None and not isinstance(cwd, str):
        cwd = None
    job_id = raw.get("job_id")
    if job_id is not None and not isinstance(job_id, str):
        job_id = str(job_id)
    if not job_id and from_disk and isinstance(prompt, str):
        # ── 一次性兼容迁移（只对读旧文件生效） ──────────────────────────────
        # 2026-11 之前写下的队列文件里，回传条目的 `job_id` 只存在于提示词文本的
        # `<frago-async-callback job_id="...">` 标签里，没有独立字段。读旧文件时不反解，
        # 等于把这些历史条目从「可幂等去重」降级成「可能重复投喂」，所以留这最后一条
        # 迁移路径。
        #
        # **退役说明**：新写入的条目一律由入队方传结构化 `job_id`（`enqueue(job_id=...)`），
        # 入队路径不会走到这里。等旧队列文件自然排空（或统一清理一次）后，本分支连同
        # 模块顶部的 `re` 导入一并删除。此前这条反解在 `_normalize_item` / `enqueue` /
        # `try_auto_inject` 三处各写一遍，三处都会随标签格式变化静默失配。
        m = re.search(r'<frago-async-callback[^>]*job_id="([^"]+)"', prompt)
        if m:
            job_id = m.group(1)
    return {
        "id": item_id,
        "text": text,
        "skills": list(skills_raw),
        "image_paths": image_paths,
        "doc_paths": doc_paths,
        "attachments": max(0, attachments),
        "prompt": prompt,
        "cwd": cwd,
        "job_id": job_id,
        "created_at": created_at,
    }


def _public_item(item: dict[str, Any]) -> dict[str, Any]:
    """返回给前端展示的字段。"""
    res: dict[str, Any] = {
        "id": item["id"],
        "text": item["text"],
        "skills": item.get("skills") or [],
        "attachments": item.get("attachments", 0),
        "created_at": item.get("created_at", 0),
    }
    if item.get("job_id"):
        res["job_id"] = item["job_id"]
    return res


def read_queue(directory: Path) -> dict[str, Any]:
    path = directory / QUEUE_FILENAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return empty_queue()
    except (OSError, ValueError) as exc:
        logger.warning("消息队列文件读取失败，按空队列处理：%s（%s）", path, exc)
        return empty_queue()
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return empty_queue()
    items: list[dict[str, Any]] = []
    for raw in data["items"]:
        try:
            # 从盘上读回来的条目可能来自 2026-11 之前，允许那条一次性 job_id 迁移。
            items.append(_normalize_item(raw, from_disk=True))
        except QueueError as exc:
            logger.warning("跳过损坏的队列项：%s（%s）", path, exc)
    return {"version": QUEUE_VERSION, "items": items}


def write_queue(directory: Path, queue_data: dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / QUEUE_FILENAME
    tmp = target.with_name(f"{QUEUE_FILENAME}.tmp{os.getpid()}.{uuid.uuid4().hex[:6]}")
    tmp.write_text(json.dumps(queue_data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)


def _broadcast_queue_update(session_id: str, items: list[dict[str, Any]]) -> None:
    """通过 WebSocket 广播队列变更，让会话工作台实时刷新队列条。"""
    try:
        from frago.server.services.workbench_stream_bridge import WorkbenchStreamBridge
        from frago.server.websocket import create_message, manager

        bridge = WorkbenchStreamBridge.get_instance()
        loop = bridge._loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
        msg = create_message(
            WS_SESSION_QUEUE_UPDATE,
            {
                "session_id": session_id,
                "items": [_public_item(it) for it in items],
            },
        )
        asyncio.run_coroutine_threadsafe(manager.broadcast(msg), loop)
    except Exception:  # noqa: BLE001 — 广播失败不影响落盘数据
        logger.debug("广播消息队列更新失败（session=%s）", session_id, exc_info=True)


def list_queue(session_id: str) -> list[dict[str, Any]]:
    """读取会话当前的排队消息列表（供接口返回）。"""
    with _lock_for(session_id):
        data = read_queue(queue_dir(session_id))
        return [_public_item(it) for it in data["items"]]


def list_raw_queue(session_id: str) -> list[dict[str, Any]]:
    """读取包含完整 ``prompt`` 的内部队列列表。"""
    with _lock_for(session_id):
        data = read_queue(queue_dir(session_id))
        return list(data["items"])


def enqueue(
    session_id: str,
    *,
    text: str,
    prompt: str,
    skills: list[str] | None = None,
    image_paths: list[str] | None = None,
    doc_paths: list[str] | None = None,
    cwd: str | None = None,
    job_id: str | None = None,
    auto_schedule: bool = True,
) -> dict[str, Any]:
    """把一条消息追加到会话自有队列末尾（FIFO）。

    ``job_id`` 是**结构化身份**，要幂等去重就由入队方传进来；这里不再从 ``prompt`` 文本
    里反解（那条路只在 ``read_queue`` 读旧文件时作为一次性迁移保留）。传不传都能入队，
    区别只在于：带了 ``job_id`` 的条目在投喂前能判「这场会话历史里是否已经收到过同一份
    回传」，不带就没有这道保护。
    """
    if not prompt.strip():
        raise QueueError("要入队的消息内容不能为空")
    imgs = list(image_paths or [])
    docs = list(doc_paths or [])
    now_ms = int(time.time() * 1000)
    item = _normalize_item(
        {
            "id": f"q-{now_ms}-{uuid.uuid4().hex[:6]}",
            "text": text.strip(),
            "skills": list(skills or []),
            "image_paths": imgs,
            "doc_paths": docs,
            "attachments": len(imgs) + len(docs),
            "prompt": prompt,
            "cwd": cwd,
            "job_id": job_id,
            "created_at": now_ms,
        }
    )
    with _lock_for(session_id):
        directory = queue_dir(session_id)
        data = read_queue(directory)
        if len(data["items"]) >= MAX_QUEUE_ITEMS:
            raise QueueError(f"消息队列已满（最多 {MAX_QUEUE_ITEMS} 条）")
        data["items"].append(item)
        write_queue(directory, data)
        items = list(data["items"])
    register_active_queue_session(session_id)
    _broadcast_queue_update(session_id, items)
    if auto_schedule and _sender_override is None:
        schedule_auto_inject_after_settle(session_id, delay_s=0.3)
    return _public_item(item)


def remove_item(session_id: str, item_id: str) -> list[dict[str, Any]]:
    """从队列中删除指定 ``item_id`` 的消息，返回删除后的公开列表。"""
    with _lock_for(session_id):
        directory = queue_dir(session_id)
        data = read_queue(directory)
        before = len(data["items"])
        removed_ids = [it["id"] for it in data["items"] if it["id"] == item_id]
        data["items"] = [it for it in data["items"] if it["id"] != item_id]
        if len(data["items"]) != before:
            write_queue(directory, data)
            st = _read_queue_state(directory)
            rem_list = list(st.get("removed_item_ids") or [])
            rem_list.extend(removed_ids)
            st["removed_item_ids"] = rem_list[-50:]
            _write_queue_state(directory, st)
        items = list(data["items"])
    if not items:
        directory = queue_dir(session_id)
        st = _read_queue_state(directory)
        if not st.get("inflight_item_id"):
            unregister_active_queue_session(session_id)
        _cancel_settle_timer(session_id)
    _broadcast_queue_update(session_id, items)
    return [_public_item(it) for it in items]


def reorder_queue(session_id: str, item_ids: list[str]) -> list[dict[str, Any]]:
    """按给定的 ``item_ids`` 顺序重排或裁剪队列，返回更新后的公开列表。"""
    with _lock_for(session_id):
        directory = queue_dir(session_id)
        data = read_queue(directory)
        by_id = {it["id"]: it for it in data["items"]}
        seen: set[str] = set()
        next_items: list[dict[str, Any]] = []
        for iid in item_ids:
            if iid in by_id and iid not in seen:
                next_items.append(by_id[iid])
                seen.add(iid)
        dropped_ids = [it["id"] for it in data["items"] if it["id"] not in seen]
        data["items"] = next_items
        write_queue(directory, data)
        if dropped_ids:
            st = _read_queue_state(directory)
            rem_list = list(st.get("removed_item_ids") or [])
            rem_list.extend(dropped_ids)
            st["removed_item_ids"] = rem_list[-50:]
            _write_queue_state(directory, st)
        items = list(data["items"])
    if not items:
        directory = queue_dir(session_id)
        st = _read_queue_state(directory)
        if not st.get("inflight_item_id"):
            unregister_active_queue_session(session_id)
        _cancel_settle_timer(session_id)
    _broadcast_queue_update(session_id, items)
    return [_public_item(it) for it in items]


def pop_earliest(session_id: str) -> dict[str, Any] | None:
    """弹出队列里最早的那一条消息（队首），并从持久化队列里删除。"""
    with _lock_for(session_id):
        directory = queue_dir(session_id)
        data = read_queue(directory)
        if not data["items"]:
            directory = queue_dir(session_id)
            st = _read_queue_state(directory)
            if not st.get("inflight_item_id"):
                unregister_active_queue_session(session_id)
            return None
        earliest = data["items"].pop(0)
        write_queue(directory, data)
        items = list(data["items"])
    if not items:
        directory = queue_dir(session_id)
        st = _read_queue_state(directory)
        if not st.get("inflight_item_id"):
            unregister_active_queue_session(session_id)
    _broadcast_queue_update(session_id, items)
    return earliest


def prepend_item(session_id: str, item: dict[str, Any]) -> None:
    """当自动注入因瞬时忙碌未能投出时，把刚取出的消息放回队首，避免丢消息。"""
    with _lock_for(session_id):
        directory = queue_dir(session_id)
        data = read_queue(directory)
        if not any(it["id"] == item["id"] for it in data["items"]):
            data["items"].insert(0, _normalize_item(item))
            write_queue(directory, data)
        items = list(data["items"])
    register_active_queue_session(session_id)
    _broadcast_queue_update(session_id, items)


# ── 轮次切分与最后一轮交互卡检测 ────────────────────────────────────


def _record_field(rec: UnifiedRecord | dict[str, Any], name: str, default: Any = None) -> Any:
    if isinstance(rec, dict):
        return rec.get(name, default)
    return getattr(rec, name, default)


def _has_substantive_assistant_response(rec: UnifiedRecord | dict[str, Any]) -> bool:
    """判断单条主会话记录是否为含实际文本内容的 assistant 回复（``agent.say`` 非空文本）。"""
    agent_path = _record_field(rec, "agent_path") or []
    if agent_path:
        return False
    if _record_field(rec, "kind") != "agent.say":
        return False
    payload = _record_field(rec, "payload") or {}
    if not isinstance(payload, dict):
        return False
    text = payload.get("text")
    return isinstance(text, str) and bool(text.strip())


#: 相邻记录之间超过这个间隔，说明 agent 已经停过一段（人在等，或定时器在等），不再算同一轮。
#:
#: 取 120 秒：正常工具流的间隔是秒级，切不到；而「每隔 45～120 秒自查一次」的长驻轮询会被
#: 切成独立轮次。2026-11-13 那场会话正是因为没有这道切分，把 11:38～15:42 四个多小时、
#: 中间无人发言的全部内容算成一个巨型末轮，轮内任何一次误判都无法被后续轮次冲掉。
TURN_SILENCE_GAP_MS = 120_000

#: 定时唤醒类工具：agent 给自己挂定时器，或查看 / 撤销定时器，标志新一轮自查开始。
_ASYNC_WAKEUP_TOOL_NAMES = frozenset(
    {"schedulewakeup", "croncreate", "crondelete", "cronlist"}
)


def _record_ts_ms(rec: UnifiedRecord | dict[str, Any]) -> int | None:
    """取记录的毫秒时间戳；缺失或形状不对时返回 ``None``（此时不做静默切分）。"""
    ts = _record_field(rec, "ts")
    if isinstance(ts, bool) or not isinstance(ts, (int, float)):
        return None
    return int(ts)


def _is_async_wakeup_boundary(rec: UnifiedRecord | dict[str, Any]) -> bool:
    """这条记录是否标志「一次异步定时唤醒」的开始。

    两种形态：agent 自己挂 / 查定时器（``schedule`` 族工具调用），以及后台任务跑完那一刻
    落下的通知（``task-notification`` 注入）。两者都意味着上一段自查到此为止、下一段另起。
    """
    kind = _record_field(rec, "kind")
    payload = _record_field(rec, "payload") or {}
    if not isinstance(payload, dict):
        return False
    if kind == "tool.call":
        family = str(payload.get("tool_family") or "").strip().lower()
        name = str(payload.get("tool_name") or "").strip().lower()
        return family == "schedule" or name in _ASYNC_WAKEUP_TOOL_NAMES
    if kind == "context.inject":
        return (
            payload.get("channel") == "task-notification"
            or payload.get("source") == "task-notification"
        )
    return False


def _has_ui_decision_card(text: str) -> bool:
    """检查文本是否包含 ``frago_ui_component == "decision-card"`` 结构。"""
    if not text or '"frago_ui_component"' not in text:
        return False
    if _extract_ui_component_dict(text) is not None:
        return True
    idx = text.rfind('"frago_ui_component"')
    start = text.rfind("{", 0, idx)
    if start < 0:
        return False
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return False
    return isinstance(obj, dict) and obj.get("frago_ui_component") == "decision-card"


#: 独立的 ``frago ask`` / ``frago app ask`` 命令行：命令名之前只允许 shell 连接符与空白，
#: 命令名之后只允许选项与空白。用来把「真的挂了张卡」和「命令回显里出现卡片 JSON」分开。
_STANDALONE_ASK_CMD_RE = re.compile(
    r"^\s*(?:[A-Za-z0-9_./-]*/)?frago(?:\.exe)?\s+(?:app\s+)?ask\b"
)
#: 帮助类选项：带这些的调用只是在查用法，不会真的产出待人回答的卡片。
_ASK_HELP_FLAG_RE = re.compile(r"(?:^|\s)(?:-h|--help)\b")
#: shell 命令分隔符：出现即说明这不是一条独立命令，而是复合脚本的一部分。
_SHELL_CHAIN_RE = re.compile(r"(?:&&|\|\||;|\||\n)")


def _is_standalone_ask_command(command: str) -> bool:
    """判断一段命令行是不是**独立**的 ``frago ask`` / ``frago app ask`` 调用。

    只有独立调用才可能产出「等着人点选」的卡片。复合脚本（``a && b``、``a; b``）里的
    ``frago ask`` 往往是校验用例、演示或探测，它打印出来的卡片 JSON 是**命令输出内容**，
    不是挂给人类的卡。带 ``-h`` / ``--help`` 的调用同理。
    """
    cmd = (command or "").strip()
    if not cmd:
        return False
    if _ASK_HELP_FLAG_RE.search(cmd):
        return False
    # 去掉命令末尾用于抑制报错的重定向（如 `2>&1 || true`）后再判连接符
    head = _SHELL_CHAIN_RE.split(cmd, maxsplit=1)[0]
    return bool(_STANDALONE_ASK_CMD_RE.match(head))


def _paired_tool_call(
    records: Sequence[UnifiedRecord | dict[str, Any]],
    index: int,
) -> UnifiedRecord | dict[str, Any] | None:
    """为 ``records[index]`` 这条 ``tool.result`` 找配对的 ``tool.call``。

    匹配优先级：``call_id`` 完全相同 → 同 ``group_id`` 的最近一条 → 紧邻的前序调用。
    找不到返回 ``None``（此时调用方退回「正文是否为规范独立组件输出」的保守判定）。
    """
    target = records[index]
    target_payload = _record_field(target, "payload") or {}
    if not isinstance(target_payload, dict):
        target_payload = {}
    target_call_id = target_payload.get("call_id")
    target_group = _record_field(target, "group_id")

    fallback: UnifiedRecord | dict[str, Any] | None = None
    for j in range(index - 1, -1, -1):
        cand = records[j]
        if _record_field(cand, "kind") != "tool.call":
            continue
        cand_payload = _record_field(cand, "payload") or {}
        if not isinstance(cand_payload, dict):
            cand_payload = {}
        if target_call_id and cand_payload.get("call_id") == target_call_id:
            return cand
        if fallback is None and (
            not target_group or _record_field(cand, "group_id") == target_group
        ):
            fallback = cand
    return fallback


def _tool_call_command(rec: UnifiedRecord | dict[str, Any]) -> str:
    """取出 ``tool.call`` 里的命令行原文（各家内核字段名不一，逐个兜）。"""
    payload = _record_field(rec, "payload") or {}
    if not isinstance(payload, dict):
        return ""
    args = payload.get("args")
    if isinstance(args, dict):
        for key in ("CommandLine", "command", "cmd"):
            val = args.get(key)
            if isinstance(val, str) and val.strip():
                return val
    for key in ("command", "cmd"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val
    return ""


def _tool_call_ask_verdict(rec: UnifiedRecord | dict[str, Any]) -> bool | None:
    """这条 ``tool.call`` 是不是「挂了张待人回答的卡」的调用。

    返回三态：``True`` 是、``False`` 明确不是、``None`` 判不出（交给正文形状兜底）。
    命令行原文优先——它最能区分「独立 ask 调用」与「复合脚本里的校验用例」；没有命令行时
    退回工具名（部分内核与测试夹具直接用 ``{"tool": "ask"}`` 这种写法）。
    """
    command = _tool_call_command(rec)
    if command:
        return _is_standalone_ask_command(command)
    payload = _record_field(rec, "payload") or {}
    if not isinstance(payload, dict):
        return None
    for key in ("tool_name", "tool", "name"):
        name = payload.get(key)
        if isinstance(name, str) and name.strip():
            return name.strip().lower() in {"ask", "app_ask", "frago_ask"} or name.strip().lower().endswith(
                "_ask"
            )
    return None


#: 各家内核给工具输出套的元数据行：判「正文是否就是那一个组件输出」时不算内容。
_TOOL_OUTPUT_WRAPPER_RE = re.compile(
    r"^\s*(?:Created At|Completed At|Command exited with code|Command output|"
    r"Showing lines|Tool is running as a background task)\b.*$",
    re.MULTILINE,
)


def _body_is_bare_component_output(body: str) -> bool:
    """正文是否就是**规范独立的**组件输出（剥掉内核元数据后只剩那一个卡片 JSON）。

    真卡片由 ``frago ask`` 直接产出；命令回显（``ps aux`` 行、``=== CLI VALID TEST ===``
    分段日志、多条命令串联输出）在 JSON 之前还夹着别的输出行，据此排除。
    """
    if body.count('"frago_ui_component"') != 1:
        return False
    idx = body.find('"frago_ui_component"')
    start = body.rfind("{", 0, idx)
    if start < 0:
        return False
    try:
        obj, _ = json.JSONDecoder().raw_decode(body[start:])
    except json.JSONDecodeError:
        return False
    if not isinstance(obj, dict) or obj.get("frago_ui_component") != "decision-card":
        return False
    # JSON 之前：剥掉内核元数据行后应当什么都不剩；剩了就说明这是命令回显。
    prefix = _TOOL_OUTPUT_WRAPPER_RE.sub("", body[:start])
    return not prefix.strip()


def record_has_interactive_card(
    rec: UnifiedRecord | dict[str, Any],
    records: Sequence[UnifiedRecord | dict[str, Any]] | None = None,
) -> bool:
    """判断单条主会话记录是否包含交互卡（``answer-needed-by-human`` 或 ``decision-card``）。

    判据是「这张卡是不是挂给人类、等着人点选的」。``tool.result`` 里的卡片 JSON 有两类来路：
    真卡片（``frago ask`` 独立调用产出）与**命令回显**（校验用例、演示、复合脚本打印出来的
    卡片原文）。后者不是待答卡片——把它算成卡会让会话一直被闸门挡住（2026-11-13 实测：
    一条 CLI 校验回显把两条回传压了 3 小时 55 分）。故对 ``tool.result`` 先看配对的
    ``tool.call`` 是不是独立 ``ask`` 调用；配不上时退回「正文是否为规范独立组件输出」。

    ``records`` 为所在记录序列（可选）：给了才能回看配对调用，做上面那层判别。
    """
    agent_path = _record_field(rec, "agent_path") or []
    if agent_path:
        return False
    kind = _record_field(rec, "kind")
    payload = _record_field(rec, "payload") or {}
    if not isinstance(payload, dict):
        return False
    if kind == "agent.say":
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            return False
        if card_in(text):
            return True
        # 代码围栏里贴出来的示例 JSON 不是待人回答的卡：剥掉围栏内容后再判。
        return _has_ui_decision_card(_strip_markdown_code_fences(text))
    if kind == "tool.result" and payload.get("status") != "error":
        body = payload.get("body")
        if not isinstance(body, str) or not body.strip():
            return False
        if not _has_ui_decision_card(body):
            return False
        return _tool_result_is_live_card(rec, body, records)
    return False


def _strip_markdown_code_fences(text: str) -> str:
    """剥掉 Markdown 代码围栏（```...```）内的内容，用于排除「示例 JSON」误判。

    ``answer-needed-by-human`` 围栏块是**真卡片**，必须保留——它由 ``card_in`` 单独识别，
    走到这里时已经判过了。
    """
    if "```" not in text:
        return text
    out: list[str] = []
    in_fence = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append(line)
    return "\n".join(out)


def _tool_result_is_live_card(
    rec: UnifiedRecord | dict[str, Any],
    body: str,
    records: Sequence[UnifiedRecord | dict[str, Any]] | None,
) -> bool:
    """``tool.result`` 里的卡片 JSON 是否为「真的挂给人类」的那张。

    先按配对 ``tool.call`` 判：独立 ``ask`` 调用 → 真卡片；明确配到非 ask 调用 → 回显，不算。
    配不上时（未给 ``records``、老记录缺 ``tool.call``、或跨窗口截断）退回正文形状判定。
    """
    if records is not None:
        index = next((i for i, r in enumerate(records) if r is rec), None)
        if index is not None:
            call = _paired_tool_call(records, index)
            if call is not None:
                verdict = _tool_call_ask_verdict(call)
                if verdict is not None:
                    return verdict
    return _body_is_bare_component_output(body)


def is_card_answer_record(rec: UnifiedRecord | dict[str, Any]) -> bool:
    """判断单条记录是不是人类点选交互卡发出的 ``【answer】`` 回复。"""
    agent_path = _record_field(rec, "agent_path") or []
    if agent_path:
        return False
    kind = _record_field(rec, "kind")
    payload = _record_field(rec, "payload") or {}
    if not isinstance(payload, dict):
        return False
    text: Any = None
    if kind == "user.say":
        if payload.get("command"):
            return False
        text = payload.get("text")
    elif kind == "context.inject" and payload.get("channel") == "queued_command":
        text = payload.get("body")
    return isinstance(text, str) and text.lstrip().startswith("【answer】")


def segment_main_turns(
    records: Sequence[UnifiedRecord | dict[str, Any]],
) -> list[list[UnifiedRecord | dict[str, Any]]]:
    """将主会话记录按「轮次」切分。

    切分规则：
    - 只看主会话记录（``agent_path == []``），忽略子 agent 内部记录。
    - 每一轮以一次完整的 assistant 回应（含 ``agent.say`` 或带交互卡的 ``tool.result``）为核心：
      - 当当前轮已经出现过 ``agent.say``，后续再遇到新的 ``user.say``、``context.inject``
        或属于不同 ``group_id`` 的非记账记录时，开启新一轮；
      - 当当前轮尚未出现 ``agent.say`` 但已包含工具或思考记录，若遇到新的 ``user.say`` 或
        hook 注入（``context.inject`` 且 ``source == "hook"``），也开启新一轮。
    - **静默与定时唤醒也要切轮**：若相邻两条记录之间隔了超过
      :data:`TURN_SILENCE_GAP_MS`，或当前轮里已经走过一段工具流、此刻又遇到一次定时唤醒
      （``schedule`` 族工具调用、后台任务通知），则把已攒下的那段收成一轮。没有这道切分时，
      一场「派发 Worker 后用定时器自问自答数小时」的会话会把全部内容算成一个巨型末轮，轮内
      一次误判（如把命令回显当卡片）就把队列闸门关死到最后，且无法被后续轮次冲掉。
    - 只保留至少包含一条实质回复或交互卡（非空 ``agent.say`` 或 ``record_has_interactive_card``）
      的轮次，因此末尾索引 ``-1`` 即为最后一轮实际内容会话。
    """
    turns: list[list[UnifiedRecord | dict[str, Any]]] = []
    current: list[UnifiedRecord | dict[str, Any]] = []
    current_has_say = False
    current_say_group: str | None = None
    current_has_assistant_step = False
    prev_ts: int | None = None

    def _close_current() -> None:
        nonlocal current, current_has_say, current_say_group, current_has_assistant_step
        if current:
            turns.append(current)
        current = []
        current_has_say = False
        current_say_group = None
        current_has_assistant_step = False

    for rec in records:
        agent_path = _record_field(rec, "agent_path") or []
        if agent_path:
            continue
        kind = str(_record_field(rec, "kind") or "")
        group_id = _record_field(rec, "group_id")
        payload = _record_field(rec, "payload") or {}

        if kind in _BOOKKEEPING_KINDS:
            if current:
                current.append(rec)
            continue

        # 定时唤醒是新一轮自查的起点：上一轮已经说过话之后，再出现一次定时唤醒就另起一段。
        # 这一条不能只挂在「还没说话」的分支下——事故现场那场会话的自查循环每轮都有回复，
        # 而同一次派发里所有记录的 group_id 相同，只按 group 判永远切不开。
        # 也不能无条件切：首次挂定时器是本轮内的一个动作，切了会把人的提问和它的回答剥开。
        if current_has_say and _is_async_wakeup_boundary(rec):
            _close_current()

        # 判断是否应该在此处切开新的一轮
        if current_has_say:
            same_group = bool(group_id and current_say_group and group_id == current_say_group)
            if not same_group:
                _close_current()
        elif current_has_assistant_step:
            is_new_boundary = kind == "user.say" or (
                kind == "context.inject"
                and isinstance(payload, dict)
                and payload.get("source") == "hook"
            )
            # 静默：这一轮还没说过话，却与上一段工具流隔了超过阈值的时间，说明 agent 早已
            # 停过一段（人没开口、定时器也没唤醒），不该再算同一轮。
            cur_ts = _record_ts_ms(rec)
            silent_gap = (
                prev_ts is not None
                and cur_ts is not None
                and cur_ts - prev_ts > TURN_SILENCE_GAP_MS
            )
            if is_new_boundary or silent_gap:
                _close_current()

        cur_ts = _record_ts_ms(rec)
        current.append(rec)
        if cur_ts is not None:
            prev_ts = cur_ts
        if _has_substantive_assistant_response(rec):
            current_has_say = True
            current_say_group = str(group_id) if group_id else None
            current_has_assistant_step = True
        elif kind in {"agent.say", "agent.think", "tool.call", "tool.result"}:
            current_has_assistant_step = True

    if current:
        turns.append(current)

    # 过滤出真正构成了实际会话轮次的段（含非空 assistant response 文本或含交互卡）
    valid_turns = [
        turn
        for turn in turns
        if any(
            _has_substantive_assistant_response(r) or record_has_interactive_card(r, records)
            for r in turn
        )
    ]
    return valid_turns


def has_interactive_card_in_tail_turns(
    records: Sequence[UnifiedRecord | dict[str, Any]],
    *,
    window: int = TAIL_TURN_WINDOW,
) -> bool:
    """检查最后一轮实际内容会话（默认 ``window=1``）中是否存在未作答的交互卡。"""
    turns = segment_main_turns(records)
    if not turns:
        return False
    tail_turns = turns[-window:] if window > 0 else turns
    has_unanswered_card = False
    for turn in tail_turns:
        for rec in turn:
            if record_has_interactive_card(rec, records):
                has_unanswered_card = True
            elif has_unanswered_card and is_card_answer_record(rec):
                has_unanswered_card = False
    return has_unanswered_card


def detect_stop_turn_id(
    records: Sequence[UnifiedRecord | dict[str, Any]],
) -> str | None:
    """检测会话末尾是否已经出现完成的 stop 轮次（最后一轮必须是实际内容如 assistant response 文本），返回该轮末尾实质记录的 ``id``。

    若会话还没有任何记录，或者最后一条实质记录是用户发言 / 正在执行中的工具调用（说明新一轮
    还没产完 stop 轮次的回复），返回 ``None``。
    """
    last_substantive: UnifiedRecord | dict[str, Any] | None = None
    for rec in records:
        agent_path = _record_field(rec, "agent_path") or []
        if agent_path:
            continue
        kind = str(_record_field(rec, "kind") or "")
        if kind in _BOOKKEEPING_KINDS:
            continue
        if kind == "context.inject":
            payload = _record_field(rec, "payload") or {}
            # 排队中的插话尚未执行完
            if (
                isinstance(payload, dict)
                and payload.get("channel") == "queued_command"
                and payload.get("queue_state") == "pending"
            ):
                last_substantive = rec
            continue
        last_substantive = rec

    if last_substantive is None:
        return None
    if _has_substantive_assistant_response(last_substantive) or record_has_interactive_card(
        last_substantive, records
    ):
        rec_id = _record_field(last_substantive, "id")
        return str(rec_id) if rec_id else "stop"
    return None


# ── 会话运行态判定与自动注入 ────────────────────────────────────────


def is_session_busy(session_id: str) -> bool:
    """判断这场会话此刻是否正在运行（未 stop）。

    综合三层信号：
    1. CoreAgent 常驻进程状态（``coreagent_runner.busy``）或 UI 会话池状态；
    2. tmux 窗格实时忙碌信号（spinner、``running stop hook``、``esc to interrupt`` 等）；
    3. 会话转录文件 / 存储层的轮次完成探针（``evaluate_file`` / ``latest_turn``）。
    """
    from frago.server.services import coreagent_runner
    from frago.session import (
        agy_store,
        codex_store,
        coreagent_store,
        opencode_store,
        record_reader,
        transcript_completion,
    )
    from frago.session.adapters.claude_code_records import find_session_file

    if session_id in _injecting_sessions:
        return True

    family = record_reader.detect_family(session_id)
    if family == "coreagent":
        if coreagent_runner.busy(session_id):
            return True
        try:
            path = coreagent_store.find_session_file(session_id)
            if path is not None and path.is_file():
                verdict = transcript_completion.evaluate_file(path)
                if verdict is not None and not verdict.done:
                    return True
        except Exception:  # noqa: BLE001
            logger.warning("检查转录完成态失败（session=%s）", session_id, exc_info=True)
        return False

    # 检查 UI 会话池
    try:
        from frago.server.services.ui_session_runner import get_runner

        runner = get_runner()
        pooled = runner._pool.peek(session_id)
        if pooled is not None and getattr(pooled, "status", None) == "busy":
            return True
    except Exception:  # noqa: BLE001
        pass

    # 检查 tmux 窗格是否仍在忙碌（包括正在跑 stop hook）
    try:
        from frago.server.services import tmux_sessions_service as tsvc

        link = tsvc.find_for_session(session_id)
        if link is not None and link.busy:
            return True
    except Exception:  # noqa: BLE001
        pass

    # 检查各家转录文件的完成度（verdict 为 None 表示无法仅凭转录裁决忙闲，
    # 不抛异常退化，由前序池/窗格忙探针把关真忙态，并交下游读屏信号二次确认）
    try:
        if family == "claude-code":
            path = find_session_file(session_id)
            if path is not None and path.is_file():
                verdict = transcript_completion.evaluate_file(path)
                if verdict is None:
                    logger.debug("转录完成态未确定（session=%s, family=%s）", session_id, family)
                elif not verdict.done:
                    return True
        elif family == "codex":
            path = codex_store.find_rollout(session_id)
            if path is not None and path.is_file():
                verdict = codex_store.latest_turn(session_id)
                if verdict is None:
                    logger.debug("转录完成态未确定（session=%s, family=%s）", session_id, family)
                elif not verdict.done:
                    return True
        elif family == "opencode":
            verdict = opencode_store.latest_turn(session_id)
            if verdict is None:
                logger.debug("转录完成态未确定（session=%s, family=%s）", session_id, family)
            elif not verdict.done:
                return True
        elif family == "agy":
            verdict = agy_store.latest_turn(session_id)
            if verdict is None:
                logger.debug("转录完成态未确定（session=%s, family=%s）", session_id, family)
            elif not verdict.done:
                return True
    except Exception:  # noqa: BLE001
        logger.warning("检查转录完成态失败（session=%s）", session_id, exc_info=True)

    return False


def evaluate_queue_state(
    session_id: str,
    records: Sequence[UnifiedRecord | dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """评估当前会话是否满足队列自动注入条件。

    返回字典包含：
    - ``session_stopped``: 会话进程/窗格是否已停止且出现了 stop 轮次
    - ``stop_turn_id``: 检测到的末尾 stop 轮次记录 ID（未出现时为 ``None``）
    - ``blocked_by_card``: ``[end, end-5]`` 轮内是否存在交互卡
    - ``can_inject``: 当且仅当 ``session_stopped and not blocked_by_card`` 且未在同一轮重复注入时为真
    """
    from frago.session import record_reader

    busy = is_session_busy(session_id)
    if records is None:
        try:
            records = record_reader.read_records(session_id, tail=True, limit=200)
        except Exception:  # noqa: BLE001
            records = []

    stop_turn_id = detect_stop_turn_id(records)
    directory = queue_dir(session_id)
    persisted_state = _read_queue_state(directory)
    persisted_turn = persisted_state.get("last_injected_turn")
    cross_injecting = _is_cross_process_injecting(session_id, persisted_state)
    session_stopped = (not busy) and (stop_turn_id is not None) and (not cross_injecting)
    blocked_by_card = has_interactive_card_in_tail_turns(records, window=TAIL_TURN_WINDOW)
    already_injected_this_turn = stop_turn_id is not None and (
        _last_injected_turn.get(session_id) == stop_turn_id
        or persisted_turn == stop_turn_id
    )
    can_inject = (
        session_stopped
        and not blocked_by_card
        and not already_injected_this_turn
        and not cross_injecting
    )
    return {
        "session_stopped": session_stopped,
        "stop_turn_id": stop_turn_id,
        "blocked_by_card": blocked_by_card,
        "can_inject": can_inject,
        "has_records": bool(records),
        "injecting": cross_injecting,
    }


def _sync_dispatch_job_delivering(job_id: str) -> None:
    try:
        from frago.session.async_dispatch import load_dispatch_job, record_callback_delivery_outcome

        job = load_dispatch_job(job_id)
        if job is not None and job.delivery_state == "queued":
            # 契约要求调用方注入「从持久化派发单上读到的当前态」：本体层已恢复纯函数、
            # 不自己读盘，不注入就等于判据不成立、动作被拒——而下面的宽 except 会把
            # 这次拒绝静默吞掉，派发单就永远停在 queued。
            record_callback_delivery_outcome(
                job_id,
                from_state="queued",
                to_state="delivering",
                prior_delivery_state=job.delivery_state,
            )
    except Exception:
        logger.debug("Failed to advance dispatch job %s to delivering", job_id, exc_info=True)


def _sync_dispatch_job_delivered_and_finalize(job_id: str) -> None:
    try:
        from frago.session.async_dispatch import (
            finalize_dispatch_job,
            load_dispatch_job,
            record_callback_delivery_outcome,
        )

        job = load_dispatch_job(job_id)
        if job is None:
            return
        if job.delivery_state == "queued":
            record_callback_delivery_outcome(
                job_id,
                from_state="queued",
                to_state="delivering",
                prior_delivery_state=job.delivery_state,
            )
            job = load_dispatch_job(job_id)
        if job is not None and job.delivery_state == "delivering":
            record_callback_delivery_outcome(
                job_id,
                from_state="delivering",
                to_state="delivered",
                prior_delivery_state=job.delivery_state,
            )
            job = load_dispatch_job(job_id)
        if (
            job is not None
            and job.delivery_state == "delivered"
            and getattr(job, "exit_code", None) is not None
        ):
            target_status = "completed" if job.exit_code == 0 else "failed"
            finalize_dispatch_job(
                job_id,
                exit_code=job.exit_code,
                delivery_state="delivered",
                job_status=target_status,
                prior_delivery_state=job.delivery_state,
            )
    except Exception:
        logger.debug("Failed to finalize dispatch job %s on delivery", job_id, exc_info=True)


def _sync_dispatch_job_queued_on_failure(job_id: str, reason: str) -> None:
    try:
        from frago.session.async_dispatch import load_dispatch_job, record_callback_delivery_outcome

        job = load_dispatch_job(job_id)
        if job is not None and job.delivery_state == "delivering":
            record_callback_delivery_outcome(
                job_id,
                from_state="delivering",
                to_state="queued",
                reason=reason,
                prior_delivery_state=job.delivery_state,
            )
    except Exception:
        logger.debug("Failed to rollback dispatch job %s to queued", job_id, exc_info=True)


def _send_prompt(session_id: str, prompt: str, cwd_hint: str | None) -> bool:
    """向目标会话投喂消息，并确认消息已被目标会话接收并落入会话记录；绝不等待整轮思考回答结束。

    返回 True 表示已成功落盘送达；返回 False 表示未就绪或未进入会话记录（且输入区已清空残留）。
    """
    if _sender_override is not None:
        res = _sender_override(session_id, prompt, cwd_hint)
        return bool(res is None or res)

    # 测试要替换投递行为，走上面那个显式注入点 ``_sender_override``。
    #
    # **这里从前还有一条「探测自己是不是被 mock 了」的分支**：比较 ``session_send.send``
    # 与 import 期记下的原函数是不是同一个对象，不是就走打桩路径。那是生产代码在运行时
    # 辨认自己有没有被替换过——单测残留一次 monkeypatch、某个装饰器包了一层、热重载换了
    # 个函数对象，生产行为就会静默切到另一条路上，而且没有任何地方报错。
    from frago.server.services import session_send
    from frago.session import record_reader

    # 读取投喂前的记录基线，供 landed 检测
    initial_records = record_reader.read_records(session_id, tail=True, limit=10)
    initial_count = len(initial_records)
    initial_last_id = initial_records[-1].id if initial_records else None

    def _landed() -> bool:
        new_records = record_reader.read_records(session_id, tail=True, limit=10)
        if len(new_records) > initial_count:
            return True
        if new_records and new_records[-1].id != initial_last_id:
            return True
        clean_prompt = prompt.strip()
        for rec in reversed(new_records):
            if rec.kind in ("user.say", "user_input"):
                text = (
                    (rec.payload or {}).get("text", "")
                    if isinstance(rec.payload, dict)
                    else str(rec.payload or "")
                )
                if clean_prompt and (clean_prompt in text or text in clean_prompt):
                    return True
        return False

    status = session_send.send_when_idle(session_id, prompt, landed=_landed)
    return status in ("landed", "handed")


def try_auto_inject(
    session_id: str,
    records: Sequence[UnifiedRecord | dict[str, Any]] | None = None,
    *,
    sync: bool = False,
) -> dict[str, Any]:
    """若满足自动注入条件且队列非空，弹出最早的一条消息并注入会话。

    ``sync=True`` 时在当前线程直接完成投喂（秒级返回确认，不等待整轮回答）；默认在后台线程投喂。
    """
    inject_fd: int | None = None
    with _lock_for(session_id):
        raw_items = list_raw_queue(session_id)
        if not raw_items:
            return {"injected": False, "reason": "empty", "item": None}

        state = evaluate_queue_state(session_id, records=records)
        if not state["can_inject"]:
            reason = (
                "blocked_by_card"
                if state["blocked_by_card"]
                else "already_injected_for_turn"
                if (
                    state["stop_turn_id"] is not None
                    and not state["injecting"]
                    and (
                        _last_injected_turn.get(session_id) == state["stop_turn_id"]
                        or _read_queue_state(queue_dir(session_id)).get("last_injected_turn")
                        == state["stop_turn_id"]
                    )
                )
                else "not_stopped"
            )
            return {
                "injected": False,
                "reason": reason,
                "item": None,
                **state,
            }

        inject_fd = _try_acquire_inject_lock(session_id)
        if inject_fd is None:
            return {
                "injected": False,
                "reason": "not_stopped",
                "item": None,
                **state,
                "session_stopped": False,
                "can_inject": False,
                "injecting": True,
            }

        earliest = pop_earliest(session_id)
        if earliest is None:
            _release_inject_lock(inject_fd)
            return {"injected": False, "reason": "empty", "item": None}

        # job_id 只认结构化字段：条目从盘上读回来时那条一次性迁移已经补过了，投喂这一端
        # 不再反解提示词文本——格式一变（标签改名、属性顺序变化、单引号）就会静默失配，
        # 而失配的代价是幂等去重失效、同一条回传被灌进终端两次。
        job_id = earliest.get("job_id")

        # ── 幂等去重检查（[P0-1] & [P0-2]） ─────────────────────────────
        # 若该消息包含 job_id 且目标会话近期记录中已经包含该 job_id 的回传报文，
        # 判定为历史已送达：直接消费出队，绝不向终端二次灌入相同内容！
        already_present = False
        if job_id:
            from frago.session import record_reader

            with contextlib.suppress(Exception):
                recent_recs = record_reader.read_records(session_id, tail=True, limit=500)
                for r in recent_recs:
                    if getattr(r, "kind", "") != "user.say":
                        continue
                    t = (
                        (r.payload or {}).get("text", "")
                        if isinstance(r.payload, dict)
                        else str(r.payload or "")
                    )
                    if "<frago-async-callback" in t and (f'job_id="{job_id}"' in t or job_id in t):
                        already_present = True
                        break

        directory = queue_dir(session_id)
        persisted = _read_queue_state(directory)
        now_ms = int(time.time() * 1000)

        if already_present:
            # 命中幂等去重，持久化送达回执并推进派发单终态
            deliv_items = list(persisted.get("delivered_items") or [])
            deliv_items.append(earliest["id"])
            persisted["delivered_items"] = deliv_items[-100:]
            if job_id:
                deliv_jobs = list(persisted.get("delivered_job_ids") or [])
                deliv_jobs.append(job_id)
                persisted["delivered_job_ids"] = deliv_jobs[-100:]
            persisted.pop("inflight_item_id", None)
            persisted.pop("inflight_job_id", None)
            _write_queue_state(directory, persisted)
            _release_inject_lock(inject_fd)
            if job_id:
                _sync_dispatch_job_delivered_and_finalize(job_id)
            return {
                "injected": True,
                "delivered": True,
                "deduped": True,
                "status": "delivered",
                "reason": "deduped_already_present",
                "item": _public_item(earliest),
                **state,
            }

        stop_turn_id = state["stop_turn_id"]
        if stop_turn_id:
            _last_injected_turn[session_id] = stop_turn_id
        _injecting_sessions.add(session_id)
        if stop_turn_id:
            persisted["last_injected_turn"] = stop_turn_id
        persisted["last_injected_at_ms"] = now_ms
        persisted["injecting_pid"] = os.getpid()
        persisted["injecting_started_at_ms"] = now_ms
        persisted["inflight_item_id"] = earliest["id"]
        persisted["inflight_job_id"] = job_id
        _write_queue_state(directory, persisted)

    if job_id:
        _sync_dispatch_job_delivering(job_id)

    send_ok = False
    send_error: Exception | None = None

    def _run_injection() -> None:
        nonlocal send_ok, send_error
        try:
            res = _send_prompt(session_id, earliest["prompt"], earliest.get("cwd"))
            send_ok = bool(res is None or res)
            if not send_ok:
                raise RuntimeError("终端瞬时忙碌或提交未被会话接收")
        except Exception as exc:  # noqa: BLE001
            send_error = exc
            send_ok = False
            logger.warning(
                "自动注入队列消息失败，归还队首（session=%s, item=%s）：%s",
                session_id,
                earliest.get("id"),
                exc,
            )
            with _lock_for(session_id):
                if stop_turn_id and _last_injected_turn.get(session_id) == stop_turn_id:
                    _last_injected_turn.pop(session_id, None)
                directory = queue_dir(session_id)
                st = _read_queue_state(directory)
                if stop_turn_id and st.get("last_injected_turn") == stop_turn_id:
                    st.pop("last_injected_turn", None)
                st.pop("injecting_pid", None)
                st.pop("injecting_started_at_ms", None)
                st.pop("inflight_item_id", None)
                st.pop("inflight_job_id", None)
                _write_queue_state(directory, st)
                prepend_item(session_id, earliest)
            if job_id:
                _sync_dispatch_job_queued_on_failure(job_id, str(exc))
        else:
            with _lock_for(session_id):
                directory = queue_dir(session_id)
                st = _read_queue_state(directory)
                deliv_items = list(st.get("delivered_items") or [])
                deliv_items.append(earliest["id"])
                st["delivered_items"] = deliv_items[-100:]
                if job_id:
                    deliv_jobs = list(st.get("delivered_job_ids") or [])
                    deliv_jobs.append(job_id)
                    st["delivered_job_ids"] = deliv_jobs[-100:]
                st.pop("inflight_item_id", None)
                st.pop("inflight_job_id", None)
                _write_queue_state(directory, st)
            if job_id:
                _sync_dispatch_job_delivered_and_finalize(job_id)
        finally:
            try:
                with _lock_for(session_id):
                    _injecting_sessions.discard(session_id)
                    directory = queue_dir(session_id)
                    st = _read_queue_state(directory)
                    if st.get("injecting_pid") == os.getpid():
                        st.pop("injecting_pid", None)
                        st.pop("injecting_started_at_ms", None)
                        st.pop("inflight_item_id", None)
                        st.pop("inflight_job_id", None)
                        _write_queue_state(directory, st)
            finally:
                _release_inject_lock(inject_fd)
            if not sync and send_ok:
                schedule_auto_inject_after_settle(session_id, delay_s=0.8)

    if sync:
        _run_injection()
        if not send_ok:
            return {
                "injected": False,
                "delivered": False,
                "status": "failed",
                "reason": "send_failed",
                "error": str(send_error) if send_error else "not_accepted",
                "item": None,
                **state,
            }
        return {
            "injected": True,
            "delivered": True,
            "status": "delivered",
            "reason": "ok",
            "item": _public_item(earliest),
            **state,
        }

    threading.Thread(
        target=_run_injection,
        name=f"queue-inject-{session_id[:16]}",
        daemon=True,
    ).start()

    return {
        "injected": False,
        "accepted": True,
        "delivering": True,
        "status": "delivering",
        "reason": "delivering",
        "item": _public_item(earliest),
        **state,
    }


def schedule_auto_inject_after_settle(
    session_id: str,
    *,
    delay_s: float = 0.8,
    max_retries: int | None = None,
    retry_delay_s: float | None = None,
) -> None:
    """在轮次完成信号到达后静置并检查自动注入；若 Stop hook 仍在运行（``not_stopped``），
    按退避节拍持续重试直到会话真正停稳后自动注入，无需等待前端切回该会话。
    """
    try:
        raw_items = list_raw_queue(session_id)
    except Exception:  # noqa: BLE001
        return
    if not raw_items:
        with _locks_guard:
            _queued_sessions.discard(session_id)
        _cancel_settle_timer(session_id)
        return

    with _locks_guard:
        _queued_sessions.add(session_id)
    _cancel_settle_timer(session_id)
    limit = len(SETTLE_RETRY_DELAYS) if max_retries is None else max(0, int(max_retries))

    def _schedule_step(wait_s: float, attempt: int) -> None:
        timer = threading.Timer(max(0.0, float(wait_s)), _run_step, args=(attempt,))
        timer.daemon = True
        with _locks_guard:
            old = _settle_timers.get(session_id)
            if old is not None and old is not timer:
                old.cancel()
            _settle_timers[session_id] = timer
        timer.start()

    def _run_step(attempt: int) -> None:
        with _locks_guard:
            _settle_timers.pop(session_id, None)
        try:
            remaining = list_raw_queue(session_id)
            if not remaining:
                with _locks_guard:
                    _queued_sessions.discard(session_id)
                return
            outcome = try_auto_inject(session_id)
            if outcome.get("injected"):
                return
            if outcome.get("reason") == "not_stopped" and attempt < limit:
                next_wait = (
                    float(retry_delay_s)
                    if retry_delay_s is not None
                    else SETTLE_RETRY_DELAYS[min(attempt, len(SETTLE_RETRY_DELAYS) - 1)]
                )
                _schedule_step(next_wait, attempt + 1)
        except Exception:  # noqa: BLE001
            logger.debug("延迟检查自动注入失败（session=%s）", session_id, exc_info=True)

    _schedule_step(delay_s, 0)


def scan_persisted_queued_sessions() -> set[str]:
    """扫描持久化存储中的所有非空队列会话，覆盖所有内核家族目录。"""
    found: set[str] = set()
    try:
        root = sessions_root()
        if root.is_dir():
            for qfile in root.glob(f"*/*/{QUEUE_FILENAME}"):
                sid = qfile.parent.name
                if not sid:
                    continue
                data = read_queue(qfile.parent)
                if data.get("items"):
                    found.add(sid)
    except Exception:  # noqa: BLE001
        logger.debug("扫描持久化非空队列失败", exc_info=True)
    return found


def _seed_queued_sessions_once() -> None:
    """进程首次巡检时初始化活跃队列集合。"""
    global _seeded_from_disk
    with _locks_guard:
        if _seeded_from_disk:
            return
        _seeded_from_disk = True

    root = _sessions_root()
    index_file = root / ACTIVE_QUEUES_FILENAME
    indexed, is_seeded = _read_active_queues_index_with_meta()
    if index_file.is_file() and is_seeded:
        with _locks_guard:
            _queued_sessions.update(indexed)
        return

    # 首次初始化或存量索引未标记 seeded 时，执行唯一一次存量扫描建索引
    found = scan_persisted_queued_sessions()
    with _active_queues_file_lock():
        current, _ = _read_active_queues_index_with_meta()
        merged = current | found
        _write_active_queues_index(merged, seeded=True)
    with _locks_guard:
        _queued_sessions.update(merged)


def patrol_active_queues(*, sync: bool = False) -> list[str]:
    """巡检所有当前存在待发消息的会话，一旦某场会话已处于 stop 且无未作答交互卡，自动触发队首注入。

    这一步兜住三类不走 ``SessionStream._on_turn_complete`` 的后台场景：
    1. 会话自始至终未在前端点开过 ``/records``（或服务重启后尚未点开）；
    2. ``codex`` / ``agy`` 等不经由 ``SessionStream`` 监听的家族；
    3. Stop hook 耗时极长、超出单次退避窗口后才结束的会话。
    """
    _seed_queued_sessions_once()
    # 彻底移除 scan_persisted_queued_sessions() 全盘 glob 扫描上万个历史目录！
    # 直接读取轻量索引文件（几百字节），支持跨进程写入（CLI/watcher 入队）同步
    with contextlib.suppress(Exception):
        active_from_disk = _read_active_queues_index()
        with _locks_guard:
            _queued_sessions.update(active_from_disk)

    with _locks_guard:
        candidates = list(_queued_sessions)
    injected_sids: list[str] = []
    for sid in candidates:
        try:
            raw_items = list_raw_queue(sid)
            directory = queue_dir(sid)
            st = _read_queue_state(directory)
            inflight_id = st.get("inflight_item_id")
            if not raw_items and not inflight_id:
                unregister_active_queue_session(sid)
                continue
            outcome = try_auto_inject(sid, sync=sync)
            if outcome.get("injected"):
                injected_sids.append(sid)
        except Exception:  # noqa: BLE001
            logger.debug("后台巡检队列自动注入失败（session=%s）", sid, exc_info=True)
    return injected_sids


_patrolling = False


def patrol_active_queues_async() -> None:
    """在独立守护线程中触发一次队列巡检，避免阻塞 ``GET /api/workbench/sessions`` 列表响应。"""
    global _patrolling
    _seed_queued_sessions_once()
    with _locks_guard:
        if not _queued_sessions or _patrolling:
            return
        _patrolling = True

    def _worker() -> None:
        global _patrolling
        try:
            patrol_active_queues(sync=False)
        finally:
            with _locks_guard:
                _patrolling = False

    threading.Thread(target=_worker, name="workbench-queue-patrol", daemon=True).start()


