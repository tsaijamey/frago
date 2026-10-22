"""会话工作台的消息队列（per-session message queue）。

作用与边界：
1. **不在 agent 执行过程中把消息塞进其原生运行队列**（Claude Code 的 tmux 实时插话队列或
   CoreAgent 的 stdin 中途插话），因为实践证明中途插话会打断 agent 正在执行的流程。
2. 当会话正在执行（或队列中已有待发消息、或用户把消息加入队列）时，消息堆积到 frago 会话自有的
   持久化队列（``~/.frago/sessions/<family>/<sid>/workbench-queue.json``）中。
3. **自动注入条件**：当且仅当会话已停止（``stop``）且检测到 stop 轮次出现后，其 ``[end, end-5]``
   轮会话（即末尾最近 6 轮会话）都没有未作答的交互卡（避免因为 hook 导致含交互卡的那一轮被后续
   补充会话遮挡），才自动从队列头部取出最早的那一条消息注入会话，并从队列中删除该消息。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from frago.server.services.schedule_pending import _extract_ui_component_dict, card_in
from frago.session.unified_record import UnifiedRecord

logger = logging.getLogger(__name__)

QUEUE_FILENAME = "workbench-queue.json"
QUEUE_VERSION = 1

MAX_QUEUE_ITEMS = 100
MAX_TEXT = 100_000
MAX_ID = 64

#: 检测 ``[end, end-5]`` 轮会话是否存在交互卡（含 ``end`` 到 ``end-5`` 共 6 轮）。
TAIL_TURN_WINDOW = 6

#: 放送给前端的 WebSocket 消息类型。
WS_SESSION_QUEUE_UPDATE = "session_queue_update"

#: 引擎记账类记录：不单独构成对话轮次，也不代表用户或 agent 的实质发言。
_BOOKKEEPING_KINDS = frozenset(
    {"call.envelope", "session.state", "todo.snapshot", "usage.tick"}
)

_locks_guard = threading.Lock()
_session_locks: dict[str, threading.RLock] = {}

#: 正在执行自动注入的会话集合（防止同一时刻并发触发两次 pop）。
_injecting_sessions: set[str] = set()

#: 记录每场会话上一次触发自动注入时的末尾 stop 轮次记录 ID，防止同一轮 stop 连续弹出多条消息。
_last_injected_turn: dict[str, str] = {}

#: 测试或自定义注入器可替换此回调；默认使用 ``session_send.send``。
_sender_override: Callable[[str, str, str | None], Any] | None = None


class QueueError(ValueError):
    """队列请求不合规矩，路由据此返回 400。"""


def _lock_for(session_id: str) -> threading.RLock:
    with _locks_guard:
        lock = _session_locks.get(session_id)
        if lock is None:
            lock = threading.RLock()
            _session_locks[session_id] = lock
        return lock


def reset_runtime_state() -> None:
    """清理内存态锁与注入游标（供单元测试隔离使用）。"""
    with _locks_guard:
        _session_locks.clear()
        _injecting_sessions.clear()
        _last_injected_turn.clear()


def queue_dir(session_id: str) -> Path:
    """该会话的持久化边车目录（与 ``workbench-marks.json`` 同目录）。"""
    from frago.server.services.session_observer import session_dir
    from frago.session.record_reader import detect_family

    family = detect_family(session_id)
    return session_dir(session_id, family)


def empty_queue() -> dict[str, Any]:
    return {"version": QUEUE_VERSION, "items": []}


def _normalize_item(raw: Any) -> dict[str, Any]:
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
    return {
        "id": item_id,
        "text": text,
        "skills": list(skills_raw),
        "image_paths": image_paths,
        "doc_paths": doc_paths,
        "attachments": max(0, attachments),
        "prompt": prompt,
        "cwd": cwd,
        "created_at": created_at,
    }


def _public_item(item: dict[str, Any]) -> dict[str, Any]:
    """返回给前端展示的字段。"""
    return {
        "id": item["id"],
        "text": item["text"],
        "skills": item.get("skills") or [],
        "attachments": item.get("attachments", 0),
        "created_at": item.get("created_at", 0),
    }


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
            items.append(_normalize_item(raw))
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
) -> dict[str, Any]:
    """把一条消息追加到会话自有队列末尾（FIFO）。"""
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
    _broadcast_queue_update(session_id, items)
    return _public_item(item)


def remove_item(session_id: str, item_id: str) -> list[dict[str, Any]]:
    """从队列中删除指定 ``item_id`` 的消息，返回删除后的公开列表。"""
    with _lock_for(session_id):
        directory = queue_dir(session_id)
        data = read_queue(directory)
        before = len(data["items"])
        data["items"] = [it for it in data["items"] if it["id"] != item_id]
        if len(data["items"]) != before:
            write_queue(directory, data)
        items = list(data["items"])
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
        data["items"] = next_items
        write_queue(directory, data)
        items = list(data["items"])
    _broadcast_queue_update(session_id, items)
    return [_public_item(it) for it in items]


def pop_earliest(session_id: str) -> dict[str, Any] | None:
    """弹出队列里最早的那一条消息（队首），并从持久化队列里删除。"""
    with _lock_for(session_id):
        directory = queue_dir(session_id)
        data = read_queue(directory)
        if not data["items"]:
            return None
        earliest = data["items"].pop(0)
        write_queue(directory, data)
        items = list(data["items"])
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
    _broadcast_queue_update(session_id, items)


# ── 轮次切分与 [end, end-5] 交互卡检测 ──────────────────────────────


def _record_field(rec: UnifiedRecord | dict[str, Any], name: str, default: Any = None) -> Any:
    if isinstance(rec, dict):
        return rec.get(name, default)
    return getattr(rec, name, default)


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


def record_has_interactive_card(rec: UnifiedRecord | dict[str, Any]) -> bool:
    """判断单条主会话记录是否包含交互卡（``answer-needed-by-human`` 或 ``decision-card``）。"""
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
        return bool(card_in(text)) or _has_ui_decision_card(text)
    if kind == "tool.result" and payload.get("status") != "error":
        body = payload.get("body")
        return isinstance(body, str) and bool(body.strip()) and _has_ui_decision_card(body)
    return False


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
    - 只保留至少包含一条实质回复或交互卡（``agent.say`` 或 ``record_has_interactive_card``）
      的轮次，因此末尾索引 ``-1`` 即为 ``end`` 轮，``-6`` 即为 ``end-5`` 轮。
    """
    turns: list[list[UnifiedRecord | dict[str, Any]]] = []
    current: list[UnifiedRecord | dict[str, Any]] = []
    current_has_say = False
    current_say_group: str | None = None
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

        # 判断是否应该在此处切开新的一轮
        if current_has_say:
            same_group = bool(group_id and current_say_group and group_id == current_say_group)
            if not same_group:
                turns.append(current)
                current = []
                current_has_say = False
                current_say_group = None
                current_has_assistant_step = False
        elif current_has_assistant_step:
            is_new_boundary = kind == "user.say" or (
                kind == "context.inject"
                and isinstance(payload, dict)
                and payload.get("source") == "hook"
            )
            if is_new_boundary:
                turns.append(current)
                current = []
                current_has_say = False
                current_say_group = None
                current_has_assistant_step = False

        current.append(rec)
        if kind == "agent.say":
            current_has_say = True
            current_say_group = str(group_id) if group_id else None
            current_has_assistant_step = True
        elif kind in {"agent.think", "tool.call", "tool.result"}:
            current_has_assistant_step = True

    if current:
        turns.append(current)

    # 过滤出真正构成了会话轮次的段（含 agent.say 或含交互卡）
    valid_turns = [
        turn
        for turn in turns
        if any(
            _record_field(r, "kind") == "agent.say" or record_has_interactive_card(r)
            for r in turn
        )
    ]
    return valid_turns


def has_interactive_card_in_tail_turns(
    records: Sequence[UnifiedRecord | dict[str, Any]],
    *,
    window: int = TAIL_TURN_WINDOW,
) -> bool:
    """检查末尾 ``[end, end-5]``（共 ``window=6``）轮会话中是否存在未作答的交互卡。

    为什么检查 ``[end, end-5]`` 而不只看 ``end``：
    当 agent 在某一轮输出了交互卡（``frago ask`` 或 ``answer-needed-by-human``）后，
    Stop hook 或 PostToolUse hook 可能阻塞停止并触发 1～5 轮补充回复，把交互卡所在的那一轮
    遮挡在 ``end-1`` 乃至 ``end-5``。只要 ``[end, end-5]`` 轮内存在尚未被人类通过
    ``【answer】`` 作答的交互卡，就视为存在交互卡，禁止自动注入队列消息。
    """
    turns = segment_main_turns(records)
    if not turns:
        return False
    tail_turns = turns[-window:] if window > 0 else turns
    has_unanswered_card = False
    for turn in tail_turns:
        for rec in turn:
            if record_has_interactive_card(rec):
                has_unanswered_card = True
            elif has_unanswered_card and is_card_answer_record(rec):
                has_unanswered_card = False
    return has_unanswered_card


def detect_stop_turn_id(
    records: Sequence[UnifiedRecord | dict[str, Any]],
) -> str | None:
    """检测会话末尾是否已经出现完成的 stop 轮次，返回该轮末尾实质记录的 ``id``。

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
            if isinstance(payload, dict) and payload.get("channel") == "queued_command":
                if payload.get("queue_state") == "pending":
                    last_substantive = rec
            continue
        last_substantive = rec

    if last_substantive is None:
        return None
    last_kind = str(_record_field(last_substantive, "kind") or "")
    if last_kind == "agent.say" or record_has_interactive_card(last_substantive):
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
        opencode_store,
        record_reader,
        transcript_completion,
    )
    from frago.session.adapters.claude_code_records import find_session_file
    from frago.session import coreagent_store

    if session_id in _injecting_sessions:
        return True

    family = record_reader.detect_family(session_id)
    if family == "coreagent":
        if coreagent_runner.busy(session_id):
            return True
        path = coreagent_store.find_session_file(session_id)
        if path is not None and path.is_file():
            verdict = transcript_completion.evaluate_file(path)
            if not verdict.done:
                return True
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

    # 检查各家转录文件的完成度
    try:
        if family == "claude-code":
            path = find_session_file(session_id)
            if path is not None and path.is_file():
                verdict = transcript_completion.evaluate_file(path)
                if not verdict.done:
                    return True
        elif family == "codex":
            path = codex_store.find_rollout(session_id)
            if path is not None and path.is_file():
                verdict = codex_store.latest_turn(path)
                if not verdict.done:
                    return True
        elif family == "opencode":
            verdict = opencode_store.latest_turn(session_id)
            if not verdict.done:
                return True
        elif family == "agy":
            verdict = agy_store.latest_turn(session_id)
            if not verdict.done:
                return True
    except Exception:  # noqa: BLE001
        logger.debug("检查转录完成态失败（session=%s）", session_id, exc_info=True)

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
    session_stopped = (not busy) and (stop_turn_id is not None)
    blocked_by_card = has_interactive_card_in_tail_turns(records, window=TAIL_TURN_WINDOW)
    already_injected_this_turn = (
        stop_turn_id is not None and _last_injected_turn.get(session_id) == stop_turn_id
    )
    can_inject = (
        session_stopped
        and not blocked_by_card
        and not already_injected_this_turn
        and session_id not in _injecting_sessions
    )
    return {
        "session_stopped": session_stopped,
        "stop_turn_id": stop_turn_id,
        "blocked_by_card": blocked_by_card,
        "can_inject": can_inject,
    }


def _send_prompt(session_id: str, prompt: str, cwd_hint: str | None) -> None:
    from frago.server.services import session_send

    if _sender_override is not None:
        _sender_override(session_id, prompt, cwd_hint)
        return
    session_send.send(session_id, prompt, cwd_hint=cwd_hint)


def try_auto_inject(
    session_id: str,
    records: Sequence[UnifiedRecord | dict[str, Any]] | None = None,
    *,
    sync: bool = False,
) -> dict[str, Any]:
    """若满足自动注入条件且队列非空，弹出最早的一条消息并注入会话。

    ``sync=True`` 时在当前线程直接完成投喂（方便单元测试确定性断言）；默认在后台线程投喂，
    避免阻塞文件监听回调或 HTTP 响应。
    """
    with _lock_for(session_id):
        raw_items = list_raw_queue(session_id)
        if not raw_items:
            return {"injected": False, "reason": "empty", "item": None}

        state = evaluate_queue_state(session_id, records=records)
        if not state["can_inject"]:
            reason = (
                "blocked_by_card"
                if state["blocked_by_card"]
                else "not_stopped"
                if not state["session_stopped"]
                else "already_injected_for_turn"
            )
            return {
                "injected": False,
                "reason": reason,
                "item": None,
                **state,
            }

        earliest = pop_earliest(session_id)
        if earliest is None:
            return {"injected": False, "reason": "empty", "item": None}

        stop_turn_id = state["stop_turn_id"]
        if stop_turn_id:
            _last_injected_turn[session_id] = stop_turn_id
        _injecting_sessions.add(session_id)

    def _run_injection() -> None:
        try:
            _send_prompt(session_id, earliest["prompt"], earliest.get("cwd"))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "自动注入队列消息失败，归还队首（session=%s, item=%s）：%s",
                session_id,
                earliest.get("id"),
                exc,
            )
            # 若因为瞬时未就绪/忙碌投喂失败，放回队首并清除本轮已注入标记
            if stop_turn_id and _last_injected_turn.get(session_id) == stop_turn_id:
                _last_injected_turn.pop(session_id, None)
            prepend_item(session_id, earliest)
        finally:
            with _lock_for(session_id):
                _injecting_sessions.discard(session_id)
            # 这一轮投喂跑完后，若又产生了新的 stop 轮次且队列还有后续消息，继续检查下一条
            if not sync:
                schedule_auto_inject_after_settle(session_id, delay_s=0.8)

    if sync:
        _run_injection()
    else:
        threading.Thread(
            target=_run_injection,
            name=f"queue-inject-{session_id[:16]}",
            daemon=True,
        ).start()

    return {
        "injected": True,
        "reason": "ok",
        "item": _public_item(earliest),
        **state,
    }


def schedule_auto_inject_after_settle(session_id: str, *, delay_s: float = 0.8) -> None:
    """在轮次完成信号到达后稍作静置再检查自动注入，给 Stop hook 留出启动窗口。"""
    try:
        raw_items = list_raw_queue(session_id)
    except Exception:  # noqa: BLE001
        return
    if not raw_items:
        return

    def _delayed() -> None:
        if delay_s > 0:
            time.sleep(delay_s)
        try:
            try_auto_inject(session_id)
        except Exception:  # noqa: BLE001
            logger.debug("延迟检查自动注入失败（session=%s）", session_id, exc_info=True)

    threading.Thread(
        target=_delayed,
        name=f"queue-settle-{session_id[:16]}",
        daemon=True,
    ).start()
