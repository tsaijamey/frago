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

from frago.server.websocket import create_message, manager
from frago.session.adapters.claude_code_records import find_session_file
from frago.session.opencode_stream import OpencodeStream
from frago.session.stream import SessionStream

logger = logging.getLogger(__name__)


# WebSocket event types (extend MessageType or keep local)
WS_SESSION_RECORDS_APPEND = "session_records_append"
WS_SESSION_TURN_DONE = "session_turn_done"


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
            return

        # Claude Code session → SessionStream per project
        file_path = find_session_file(session_id)
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
                return

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

    def stop_all(self) -> None:
        """Stop all active streams."""
        with self._lock:
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

    # ---- callbacks (called on watcher thread) -----------------------------

    def _on_new_records(self, session_id: str, records: list[dict]) -> None:
        """Called by SessionStream when new records arrive."""
        if not records:
            return
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
