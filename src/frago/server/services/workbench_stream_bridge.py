"""Bridge that connects SessionStream file-watch events to the WebSocket
broadcast channel, so the workbench frontend receives record deltas in
real time instead of 5-second polling.

Design:
- Lazily starts a ``SessionStream`` per project when a session from that
  project is first viewed in the workbench.
- On receipt of new records, broadcasts ``session_records_append`` via the
  shared WebSocket manager.
- On turn completion, broadcasts ``session_turn_done``.
- Callbacks fire on the watcher's thread; the bridge uses
  ``asyncio.run_coroutine_threadsafe`` to cross into the event loop.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path

from frago.server.websocket import create_message, manager
from frago.session.adapters.claude_code_records import find_session_file
from frago.session.opencode_stream import OpencodeStream
from frago.session.stream import SessionStream

logger = logging.getLogger(__name__)


# WebSocket event types (extend MessageType or keep local)
WS_SESSION_RECORDS_APPEND = "session_records_append"
WS_SESSION_TURN_DONE = "session_turn_done"

#: 这几类记录落盘，说明 agent 正在干活，右栏的「此刻」该跟一跟。
_AGENT_AT_WORK = frozenset({"agent.say", "tool.call", "subagent.dispatch"})


def locate_stream_file(session_id: str) -> Path | None:
    """这场会话的记录文件在哪，找不到返回 None。

    **按家找，不是只在 Claude Code 的目录里找。** CoreAgent 的记录形状与 Claude Code
    一样、读法共用，只是躺在 ``~/.frago/coreagent/sessions/`` 下。从前这里写死走 Claude
    Code 那一份查找，CoreAgent 的会话于是每次都找不到文件，实时推送**一次都没启动过**，
    右栏连被叫醒的机会都没有（2026-09-29 实测）。

    只有记录形状是 Claude Code 形状的那两家走这条路：opencode 的记录在 SQLite 里（由
    :class:`OpencodeStream` 单独盯），codex 是另一种 rollout 形状，各有各的路——NEVER
    拿它们的文件来喂这条按 Claude Code 记录解析的流。
    """
    from frago.session import coreagent_store, record_reader

    try:
        family = record_reader.detect_family(session_id)
    except record_reader.UnknownSessionFamily:
        return None
    if family == "coreagent":
        return coreagent_store.find_session_file(session_id)
    if family == "claude-code":
        return find_session_file(session_id)
    return None


class WorkbenchStreamBridge:
    """Singleton that lazily starts ``SessionStream`` instances per project.

    Usage::

        bridge = WorkbenchStreamBridge.get_instance()
        bridge.ensure_watching(session_id)
    """

    _instance: WorkbenchStreamBridge | None = None
    _class_lock = threading.Lock()

    def __init__(self, loop: asyncio.AbstractEventLoop | None) -> None:
        self._streams: dict[str, SessionStream] = {}  # project_path → stream
        self._opencode_stream: OpencodeStream | None = None
        self._lock = threading.Lock()
        self._loop = loop
        # 已经登记过的会话。页面每取一次记录就调一次 ensure_watching，一秒一趟的快节拍
        # 下就是一秒一次——不记住的话每一趟都要 glob 一遍 ~/.claude/projects 再开一次
        # 文件读 cwd，全是白做的。
        self._registered: set[str] = set()
        # 这次服务运行里被打开过的会话。旁路观察的「打开」只投一次，与监听的登记分开记：
        # 监听会随 tmux 开关撤了又登记，「打开」不该跟着重投。
        self._opened: set[str] = set()
        # 游标后已发生、尚未触发成组总结的对话块计数（session_id → count）。
        self._pending_blocks: dict[str, int] = {}
        # 凑不够成组数量但会话已停下时的时间维度兜底定时器（session_id → Timer）。
        self._settle_timers: dict[str, threading.Timer] = {}
        self._settle_timeout_s: float = 10.0

    # ---- singleton --------------------------------------------------------

    @classmethod
    def get_instance(cls, loop: asyncio.AbstractEventLoop | None = None) -> WorkbenchStreamBridge:
        """Return the process-wide singleton (thread-safe)."""
        if cls._instance is None:
            with cls._class_lock:
                if cls._instance is None:
                    cls._instance = cls(loop)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Discard the singleton (test isolation)."""
        with cls._class_lock:
            if cls._instance is not None:
                cls._instance.stop_all()
                cls._instance = None

    # ---- lifecycle --------------------------------------------------------

    def ensure_watching(self, session_id: str) -> None:
        """Start watching the project for *session_id* if not already.

        Claude Code sessions (UUID-shaped) → ``SessionStream`` per project.
        CoreAgent sessions (``core_`` prefix) → 同样一条流，只是记录文件另有根目录。
        Opencode sessions (``ses_`` prefix) → shared ``OpencodeStream``.

        Safe to call multiple times — duplicate calls are no-ops.
        """
        with self._lock:
            if session_id in self._registered:
                return

        # Opencode session → shared OpencodeStream
        if session_id.startswith("ses_"):
            with self._lock:
                if self._opencode_stream is None:
                    self._opencode_stream = OpencodeStream(
                        on_records=self._on_new_records,
                        on_turn_complete=self._on_turn_complete,
                    )
                    self._opencode_stream.start()
                self._opencode_stream.watch_session(session_id)
                self._registered.add(session_id)
            self.note_opened(session_id)
            return

        # Claude Code / CoreAgent session → SessionStream per project. 两家记录形状一样，
        # 只是根目录不同，由 :func:`locate_stream_file` 按家找到那个文件。
        file_path = locate_stream_file(session_id)
        if file_path is None:
            logger.warning("WorkbenchStreamBridge: session file not found for %s", session_id)
            return

        # **要盯的目录就是这个文件所在的目录，不必再去猜。**
        #
        # 从前这里是另一条路：读出会话记的工作目录，再把它编码回目录名。那条路有两个
        # 坑，第二个是致命的——它只读文件开头几行，而会话开头躺的常常是模式、权限之类
        # 不带工作目录的旁挂记录。实测抽样 300 场里有 60 场（20%）这样读不出来，于是
        # 这些会话的实时推送**一次都没启动过**：页面只能靠五秒一趟的轮询兜底，浏览器
        # 被切到后台时连轮询都被节流，人看到的就是"这场会话半天不动"。
        #
        # 而这个文件本来就躺在它该被监听的那个目录里。用它，既不用读内容，也不经过
        # 一次有损的编码往返。
        watch_dir = file_path.parent
        project_path = str(watch_dir)

        with self._lock:
            existing = self._streams.get(project_path)
            if existing is not None:
                # 同一个项目共用一条流，但**每一场会话都要单独登记**：没登记的会话被碰
                # 一下时事件当场丢掉，不去整文件翻一遍。一个项目目录下能躺一千个会话文件。
                existing.watch_session(session_id)
                self._registered.add(session_id)
            else:
                logger.info("WorkbenchStreamBridge: starting stream for %s", watch_dir)
                stream = SessionStream(
                    project_path=project_path,
                    watch_dir=watch_dir,
                    on_records=self._on_new_records,
                    on_turn_complete=self._on_turn_complete,
                    session_id_filter=session_id,
                )
                stream.start()
                self._streams[project_path] = stream
                self._registered.add(session_id)
        self.note_opened(session_id)

    def note_opened(self, session_id: str) -> None:
        """这场会话在这次服务运行里第一次被打开：让旁路 AI 从槽位文件记着的位置补读一次。

        打开一场早就答完的会话不会有「一轮结束」，不在这里补，右栏就一直是旧的。不开在
        tmux 里的会话不登记监听，但打开它时照样要补这一次。
        """
        with self._lock:
            if session_id in self._opened:
                return
            self._opened.add(session_id)
        self._observe(session_id, "open")

    def release(self, session_id: str) -> None:
        """撤掉这一场的监听。所在项目的流一场都不盯了，整条流停掉。没登记过就什么都不做。"""
        self._cancel_settle_timer(session_id)
        stopped: list[SessionStream] = []
        with self._lock:
            self._pending_blocks.pop(session_id, None)
            if session_id not in self._registered:
                return
            self._registered.discard(session_id)
            if session_id.startswith("ses_"):
                if self._opencode_stream is not None:
                    self._opencode_stream.unwatch_session(session_id)
                return
            for path, stream in list(self._streams.items()):
                stream.unwatch_session(session_id)
                if not stream.watching_any():
                    stopped.append(self._streams.pop(path))
        # 停流要等它的工作线程收尾，放在锁外做，别让别的会话的登记跟着等。
        for stream in stopped:
            try:
                stream.stop()
            except Exception:
                logger.exception("WorkbenchStreamBridge: error stopping idle stream")

    def keep_only(self, keep: set[str]) -> None:
        """只留 *keep* 里那几场的监听，其余登记过的一律撤掉。

        会话清单每 15 秒取一次，取的时候顺带用它收一道：**不活着的**会话，就算点开过也
        不再盯它的文件（主人 09-30 定），点开那一刻页面自己取一次最新内容。

        "活着"这一条由调用方判（见 ``routes/workbench.py`` 的 ``_still_alive``）：开在
        tmux 里，或者它是 CoreAgent 那一场、常驻进程还在。**从前这里只认 tmux**，而
        CoreAgent NEVER 开在 tmux 里，于是它这一场每 15 秒被收一次、跑着的一轮一条推送都
        没有（2026-10-08 修）。
        """
        with self._lock:
            stale = [sid for sid in self._registered if sid not in keep]
        for sid in stale:
            self.release(sid)

    def stop_all(self) -> None:
        """Stop all active streams."""
        with self._lock:
            timers = list(self._settle_timers.values())
            self._settle_timers.clear()
            self._pending_blocks.clear()
            for path, stream in list(self._streams.items()):
                try:
                    stream.stop()
                except Exception:
                    logger.exception("WorkbenchStreamBridge: error stopping stream %s", path)
            self._streams.clear()
            self._registered.clear()
            if self._opencode_stream is not None:
                try:
                    self._opencode_stream.stop()
                except Exception:
                    logger.exception("WorkbenchStreamBridge: error stopping opencode stream")
                self._opencode_stream = None
        for timer in timers:
            timer.cancel()

    # ---- side observer ----------------------------------------------------

    def _observe(self, session_id: str, trigger: str) -> None:
        """把这场会话的旁路观察投进它自己的队列。投完就走，不在监听线上等模型。

        监听只留给还活着的会话（见 :meth:`keep_only`），**撤不撤只看活不活，NEVER 看页面切
        没切走**：右栏的旁路观察要求切换会话打断不了它，还活着的那场一撤，再交还多少轮都没
        人投任务，切回来看到的是旧的。
        """
        try:
            from frago.server.services.session_observer import get_observer

            get_observer().notify(session_id, trigger)
        except Exception:
            logger.exception("WorkbenchStreamBridge: observer notify failed (session=%s)", session_id)

    def _cancel_settle_timer(self, session_id: str) -> None:
        with self._lock:
            timer = self._settle_timers.pop(session_id, None)
        if timer is not None:
            timer.cancel()

    def _schedule_settle(self, session_id: str) -> None:
        """当已发生对话块还凑不够一组、但会话已停下或暂歇时，启动时间维度兜底定时器。"""
        self._cancel_settle_timer(session_id)
        if self._settle_timeout_s <= 0:
            self._on_settle_timeout(session_id)
            return
        timer = threading.Timer(
            self._settle_timeout_s,
            self._on_settle_timeout,
            args=(session_id,),
        )
        timer.daemon = True
        with self._lock:
            self._settle_timers[session_id] = timer
        timer.start()

    def _on_settle_timeout(self, session_id: str) -> None:
        from frago.server.services.session_observer import SETTLE_TRIGGER

        with self._lock:
            self._settle_timers.pop(session_id, None)
            self._pending_blocks.pop(session_id, None)
        self._observe(session_id, SETTLE_TRIGGER)

    # ---- callbacks (called on watcher thread) -----------------------------

    def _trigger_the_observer(self, session_id: str, records: list[dict]) -> None:
        """这批新记录里有没有「该叫一次旁路观察」的事。

        只总结已经发生的会话，不预设槽位等待未发生的回复：
        * 人刚发来一句话（``user.say``）时绝不抢跑触发观察，只记入已发生对话块计数并取消
          上一轮遗留的停顿兜底定时器，等 agent 真正产出回复后再一起成组总结。
        * 每当有 agent 回复落地且累计已发生对话块达到 ``BATCH_BLOCK_COUNT``（默认 3 个）时，
          立即成组触发一次 ``batch`` 观察并清零计数；若未满 3 个则启动时间兜底定时器。
        * 人按了打断——不会有正常轮次结束信号，立即取消定时器并触发 ``interrupt``。
        """
        try:
            from frago.server.services.session_observer import (
                BATCH_BLOCK_COUNT,
                BATCH_TRIGGER,
                agent_acted,
                occurred_block_count,
                person_spoke,
            )
        except Exception:
            logger.exception("WorkbenchStreamBridge: observer import failed")
            return
        if any(isinstance(r, dict) and r.get("kind") == "interrupt" for r in records):
            self._cancel_settle_timer(session_id)
            with self._lock:
                self._pending_blocks.pop(session_id, None)
            self._observe(session_id, "interrupt")
            return

        added_blocks = occurred_block_count(records)
        has_person = person_spoke(records)
        has_agent_action = agent_acted(records)

        if added_blocks > 0:
            self._cancel_settle_timer(session_id)
            with self._lock:
                total_blocks = self._pending_blocks.get(session_id, 0) + added_blocks
                self._pending_blocks[session_id] = total_blocks
        else:
            with self._lock:
                total_blocks = self._pending_blocks.get(session_id, 0)

        # 只有人刚开口、尚无任何 agent 实质动作（thinking / tool use / response）时，绝不抢跑触发
        if has_person and not has_agent_action:
            return

        if has_agent_action:
            if total_blocks >= BATCH_BLOCK_COUNT:
                with self._lock:
                    self._pending_blocks[session_id] = 0
                self._observe(session_id, BATCH_TRIGGER)
            else:
                self._schedule_settle(session_id)

    def _on_new_records(self, session_id: str, records: list[dict]) -> None:
        """Called by SessionStream when new records arrive."""
        if not records:
            return
        self._trigger_the_observer(session_id, records)
        try:
            loop = self._loop or asyncio.get_event_loop()
        except RuntimeError:
            return

        data = {"session_id": session_id, "records": records}
        msg = create_message(WS_SESSION_RECORDS_APPEND, data)
        asyncio.run_coroutine_threadsafe(manager.broadcast(msg), loop)

    def _on_turn_complete(self, session_id: str, done: bool,
                          stop_reason: str | None) -> None:
        """Called by SessionStream when a turn flips to complete."""
        if done:
            from frago.server.services.session_observer import BATCH_BLOCK_COUNT

            with self._lock:
                pending = self._pending_blocks.get(session_id, 0)
            if pending >= BATCH_BLOCK_COUNT:
                self._cancel_settle_timer(session_id)
                with self._lock:
                    self._pending_blocks[session_id] = 0
                self._observe(session_id, "turn")
            elif pending > 0:
                # 凑不齐 BATCH_BLOCK_COUNT 个已发生块，但会话已经停下了：启动时间维度兜底
                self._schedule_settle(session_id)
            try:
                from frago.server.services import workbench_queue

                workbench_queue.schedule_auto_inject_after_settle(session_id)
            except Exception:
                logger.debug(
                    "WorkbenchStreamBridge: queue auto-inject schedule failed (session=%s)",
                    session_id,
                    exc_info=True,
                )
        try:
            loop = self._loop or asyncio.get_event_loop()
        except RuntimeError:
            return

        data = {
            "session_id": session_id,
            "done": done,
            "stop_reason": stop_reason,
        }
        msg = create_message(WS_SESSION_TURN_DONE, data)
        asyncio.run_coroutine_threadsafe(manager.broadcast(msg), loop)
