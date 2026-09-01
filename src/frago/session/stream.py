"""会话文件的实时流：盯住 Claude Code 的会话 JSONL，只把**新长出来的**记录推出去。

从 :mod:`frago.session.monitor` 里搬出来的，Observer 的生死归 :mod:`frago.watcher` 管，
这里只做会话这一侧的事：把项目路径编码成会话目录、文件一动就重读重翻、按 ``seq`` 差出
新记录、顺带判这一轮说完了没有。

三条纪律，少一条这条流就会从"实时"退化成"卡顿"：

1. **第一次看见一个已经在盘上的文件，只对水位不出货。** ``seq`` 水位的初值若按 -1 起
   算，那么开着页面时任何一个老会话被碰一下，整场几千条记录会被当成"新的"一次性推给
   全部浏览器——本机最大那场是 3694 条、序列化出来 3.2 MB。界面那边照单收下、接在流的
   尾巴上，于是最老的内容排在最新内容后面，人看到的是一坨乱序的旧货。所以已经存在的
   文件第一次被处理时只记水位、一条不发；开始盯之后才新建的文件（页面新开的那场会话）
   照常全发——那种文件本来就只有几行。

2. **去抖必须在自己的线程上做。** 从前是在 watchdog 的分发线程里直接 ``sleep``，而
   watchdog 的事件分发是**单线程串行**的：睡着的时候后续事件根本进不来，"睡醒了看看有
   没有更新的事件"这个判据于是永远不成立，去抖一次都没生效过。结果是一轮对话里几十次
   落盘，每一次都各睡 0.3 秒再整文件翻一遍，全排在同一条线程上——积压随会话长度线性
   拉长，界面上就是"发完话半天没动静"。现在事件只负责登记时刻，真正的等待与处理交给
   本流自己的工作线程，同一文件在安静期内的多次改动合并成一次。

3. **只处理有人正在看的那几场。** 一个项目目录下躺着上千个会话文件（本机单个项目 921
   个、2.6 GB），谁被碰一下都去整文件翻一遍是白烧。:meth:`watch_session` 登记过的会话
   才进处理，其余的事件当场丢掉。

分层：
- ``SessionStream`` 只向 ``WatchdogObserverService`` 登记，NEVER 自己持有 Observer
- 回调跑在本流的工作线程上，消费方自己负责跨线程
- 本模块 NEVER import ``server/`` 或 ``cli/``
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

from frago.session.claude_sessions import CLAUDE_PROJECTS_DIR
from frago.session.monitor import encode_project_path
from frago.watcher import FileEvent, WatchdogObserverService, WatchTarget

logger = logging.getLogger(__name__)

# Default debounce: wait for the file to settle before re-reading.
DEFAULT_DEBOUNCE_SECONDS = 0.3


class SessionStream:
    """Watch all ``*.jsonl`` files in one Claude Code project directory.

    Usage::

        stream = SessionStream(
            project_path="/Users/jamey/Repos/frago",
            on_records=my_handler,         # called with new UnifiedRecords
            on_turn_complete=my_handler,   # called when a turn finishes
        )
        stream.start()
        ...
        stream.stop()
    """

    def __init__(
        self,
        project_path: str,
        *,
        on_records: Callable[[str, list[dict[str, object]]], None] | None = None,
        on_turn_complete: Callable[[str, bool, str | None], None] | None = None,
        debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
        session_id_filter: str | None = None,
        watch_dir: str | Path | None = None,
    ) -> None:
        """Create a stream for one project.

        Args:
            project_path: Absolute path to the project being watched.
            on_records: Called with ``(session_id, [record_dict, ...])`` when
                new records arrive.  Each dict is a ``UnifiedRecord`` serialised
                via ``dataclasses.asdict``.
            on_turn_complete: Called with ``(session_id, done, stop_reason)``
                when the latest turn flips to complete.
            debounce_seconds: How long to wait after the last file event before
                re-reading and classifying.
            session_id_filter: 开局就登记这一场。等价于建好之后调一次
                :meth:`watch_session`。**没有「不填就全都盯」这一档**——一个项目目录下
                躺着上千个会话文件，全盯等于每次无关改动都整文件翻一遍。
            watch_dir: 直接指定要盯的那个目录，给了就不再由 *project_path* 推算。
                调用方手上已经握着会话文件时**应该给**：那个文件所在的目录就是答案，
                比"读出工作目录再编码回去"这条路可靠得多——编码是有损的，而且要先能
                读到工作目录才行（见 :class:`~frago.server.services.workbench_stream_bridge.WorkbenchStreamBridge`）。
        """
        self._project_path = os.path.abspath(project_path)
        self._on_records = on_records
        self._on_turn_complete = on_turn_complete
        self._debounce = debounce_seconds

        self._watch_dir: Path | None = Path(watch_dir) if watch_dir is not None else None
        self._target: WatchTarget | None = None

        # Per-file state: last-known seq (monotonically increasing).
        self._file_seqs: dict[str, int] = {}  # file_path → last seen seq
        # Per-file state: last known turn-completion verdict.
        self._file_done: dict[str, bool] = {}  # file_path → done

        # 开始盯的那一刻已经躺在盘上的会话文件。这些文件第一次被处理时只对水位、不出货，
        # 免得一次无关的改动把整场历史当成新内容推出去（纪律 1）。
        self._preexisting: set[str] = set()

        # 谁在被看。空集合 = 谁都不看，事件直接丢（纪律 3）。
        self._watch_ids: set[str] = set()
        if session_id_filter:
            self._watch_ids.add(session_id_filter)

        # 去抖：事件只往这里登记「这个文件最后一次动是什么时候」，等待与处理由工作线程做。
        self._pending: dict[str, float] = {}
        self._cv = threading.Condition()
        self._worker: threading.Thread | None = None
        # Running flag
        self._running = False

    # ---- lifecycle --------------------------------------------------------

    def start(self) -> None:
        """Register with the global watcher and begin listening."""
        if self._running:
            return

        if self._watch_dir is None:
            self._watch_dir = CLAUDE_PROJECTS_DIR / encode_project_path(self._project_path)
        self._watch_dir.mkdir(parents=True, exist_ok=True)

        # 开始盯之前，先把已经在盘上的会话文件记下来（纪律 1）。只列目录不读内容——
        # 本机单个项目 921 个文件、2.6 GB，读一遍是分钟量级，列一遍是毫秒量级。
        self._preexisting = {str(p) for p in self._watch_dir.glob("*.jsonl")}

        self._target = WatchTarget(
            path=str(self._watch_dir),
            patterns=["*.jsonl"],
            on_modified=self._on_file_event,
            on_created=self._on_file_event,
        )

        svc = WatchdogObserverService.get_instance()
        svc.add(self._target)
        svc.start()

        self._running = True
        self._worker = threading.Thread(
            target=self._drain_loop, daemon=True, name=f"session-stream-{self._watch_dir.name[:24]}"
        )
        self._worker.start()
        logger.debug("SessionStream started: %s", self._watch_dir)

    def stop(self) -> None:
        """Unregister from the watcher."""
        if not self._running:
            return

        svc = WatchdogObserverService.get_instance()
        if self._target is not None:
            svc.remove(self._target)
            self._target = None

        with self._cv:
            self._running = False
            self._cv.notify_all()
        if self._worker is not None:
            self._worker.join(timeout=3)
            self._worker = None
        logger.debug("SessionStream stopped: %s", self._project_path)

    # ---- 谁在被看 ---------------------------------------------------------

    def watch_session(self, session_id: str) -> None:
        """登记一场会话。没登记的会话，它的文件事件当场丢掉（纪律 3）。

        重复调用无副作用——页面每取一次记录都会调一次。
        """
        with self._cv:
            self._watch_ids.add(session_id)

    def unwatch_session(self, session_id: str) -> None:
        """撤掉一场会话的登记，连同它的水位一起忘掉。"""
        with self._cv:
            self._watch_ids.discard(session_id)

    # ---- internal ---------------------------------------------------------

    def _on_file_event(self, event: FileEvent) -> None:
        """watchdog 的分发线程叫进来。**这里只登记时刻，不做任何重活。**

        分发是单线程串行的：在这里睡一下或翻一遍文件，整个 Observer 就跟着停一下，
        后面排队的事件全被拖住（纪律 2）。
        """
        if event.is_directory:
            return

        file_path = event.path
        stem = os.path.splitext(os.path.basename(file_path))[0]

        with self._cv:
            if stem not in self._watch_ids:
                return
            self._pending[file_path] = time.monotonic()
            self._cv.notify()

    def _drain_loop(self) -> None:
        """工作线程：同一文件安静满 ``_debounce`` 秒才处理一次，多次改动合并成一次。"""
        while True:
            with self._cv:
                while self._running and not self._pending:
                    self._cv.wait()
                if not self._running:
                    return
                now = time.monotonic()
                ready = [p for p, at in self._pending.items() if now - at >= self._debounce]
                if not ready:
                    # 还没安静下来。睡到最早那个文件到点为止，中途来了新事件会被唤醒。
                    soonest = min(self._pending.values())
                    self._cv.wait(timeout=max(0.0, self._debounce - (now - soonest)))
                    continue
                for path in ready:
                    self._pending.pop(path, None)

            for path in ready:
                self._process_file(path)

    def _process_file(self, file_path: str) -> None:
        """Re-read and classify *file_path*, emit new records."""
        try:
            from frago.session.adapters.claude_code_records import to_unified
            from frago.session.transcript_completion import evaluate_file

            records = to_unified(file_path)

            session_id = Path(file_path).stem
            first_sight = file_path not in self._file_seqs
            last_seq = self._file_seqs.get(file_path, -1)
            new_records = [r for r in records if r.seq > last_seq]

            if new_records:
                # Update last known seq
                self._file_seqs[file_path] = new_records[-1].seq

                # 第一次看见一个开始盯之前就存在的文件：只对水位，一条不发（纪律 1）。
                # 页面那一侧打开会话时已经自己取过尾部，这中间的空档由它的兜底轮询补上。
                replaying_history = first_sight and file_path in self._preexisting

                if self._on_records is not None and not replaying_history:
                    from dataclasses import asdict

                    try:
                        self._on_records(
                            session_id,
                            [asdict(r) for r in new_records],
                        )
                    except Exception:
                        logger.exception(
                            "SessionStream on_records callback failed (session=%s)",
                            session_id,
                        )

            # Check turn completion (only if new records arrived or not yet known)
            verdict = evaluate_file(Path(file_path))
            done = bool(verdict.done) if verdict is not None else False
            prev_done = self._file_done.get(file_path, False)

            # 第一次看见就只是对齐，不当成刚刚翻面：页面刚打开一场早就答完的老会话，
            # 不该收到一条"刚刚答完"的通知——那会让它白白热十五分钟、照常五秒一趟地轮询。
            if file_path not in self._file_done:
                self._file_done[file_path] = done
                return

            if done and not prev_done:
                # Turn just completed — only fire once per flip
                self._file_done[file_path] = True
                if self._on_turn_complete is not None:
                    try:
                        self._on_turn_complete(
                            session_id,
                            True,
                            verdict.stop_reason if verdict is not None else None,
                        )
                    except Exception:
                        logger.exception(
                            "SessionStream on_turn_complete callback failed (session=%s)",
                            session_id,
                        )
            elif not done:
                self._file_done[file_path] = False

        except Exception:
            logger.exception(
                "SessionStream failed to process file: %s", file_path
            )
