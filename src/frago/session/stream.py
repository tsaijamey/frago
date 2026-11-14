"""会话文件的实时流：盯住会话转录文件，只把**新长出来的**记录推出去。

通过五内核统一适配器注册表（KernelSessionAdapter）进行记录读取与探针判定，
内部维护双向确凿路径映射（Path.resolve() 规范化），杜绝任何物理路径猜解与单监听盲猜兜底；
在增量记录到达与轮次完工时合流驱动 SessionOntologyService，实现本体状态机闭环。

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

4. **水位记身份，不记位置，而且要记全场。** ``seq`` 不是地址：整份记录每次都是重新编号的，
   引擎重写一条记录（每轮的花费账本只留最后一条）就让它后面所有记录的编号往前挪一格——新
   写下来的那句话于是可能正好落在已经交出去过的编号上，被当成旧货丢掉。丢得无声无息：界面
   上看不出报错，那条消息就是不出现（实测踩过一次，人那句话再也没进过右栏）。所以每个文件
   另记一批「已经交出去的记录编号」，按身份去重，``seq`` 只当兜底。这批编号**不设上限**：
   只记最近若干条等于宣布再往前的全部没见过，文件下一次一动就把那些旧记录整批当成新内容
   推出去，纪律 1 防的那件事原样复发（实测 935 条的会话新增 3 条，推出 874 条）。

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

from frago.session.adapters import get_kernel_session_adapter
from frago.session.claude_sessions import CLAUDE_PROJECTS_DIR
from frago.session.monitor import encode_project_path
from frago.session.service import SessionOntologyService
from frago.watcher import FileEvent, WatchdogObserverService, WatchTarget

logger = logging.getLogger(__name__)

# Default debounce: wait for the file to settle before re-reading.
DEFAULT_DEBOUNCE_SECONDS = 0.3


class SessionStream:
    """Watch transcript files and stream incremental unified records."""

    def __init__(
        self,
        project_path: str,
        *,
        on_records: Callable[[str, list[dict[str, object]]], None] | None = None,
        on_turn_complete: Callable[[str, bool, str | None], None] | None = None,
        debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
        session_id_filter: str | None = None,
        watch_dir: str | Path | None = None,
        family: str | None = None,
        watch_file: str | Path | None = None,
        ontology_service: SessionOntologyService | None = None,
        origin: str = "terminal",
    ) -> None:
        """Create a stream for one project.

        Args:
            project_path: Absolute path to the project being watched.
            on_records: Called with ``(session_id, [record_dict, ...])`` when
                new records arrive.
            on_turn_complete: Called with ``(session_id, done, stop_reason)``
                when the latest turn flips to complete.
            debounce_seconds: How long to wait after the last file event before
                re-reading and classifying.
            session_id_filter: 开局就登记这一场。等价于建好之后调一次 :meth:`watch_session`。
            watch_dir: 直接指定要盯的那个目录，给了就不再由 *project_path* 推算。
            family: 内核家族类型标识（可选）。
            watch_file: 显式指定要盯的会话文件路径（可选）。
            ontology_service: 本体服务实例，用于合流推进状态机与事件账本。
            origin: 这条流是从哪个面看这些会话的（``web`` / ``terminal`` / ``schedule``
                / ``channel``）。补档时记进本体，页面上的会话因此不再一律被当成终端开的。
                账本上明记为派活的一律以 ``worker`` 为准，覆盖这个值。
        """
        self._project_path = os.path.abspath(project_path)
        self._on_records = on_records
        self._on_turn_complete = on_turn_complete
        self._debounce = debounce_seconds
        self._family = family
        self._origin = origin
        self._ontology_service = (
            ontology_service if ontology_service is not None else SessionOntologyService()
        )

        self._watch_dir: Path | None = Path(watch_dir) if watch_dir is not None else None
        self._target: WatchTarget | None = None

        # Per-file state: last-known seq (monotonically increasing).
        self._file_seqs: dict[str, int] = {}  # file_path → last seen seq
        self._file_handed: dict[str, set[str]] = {}  # file_path → 已交出去的记录编号
        self._file_done: dict[str, bool] = {}  # file_path → done

        # 确凿双向映射：标准化绝对路径 (Path.resolve()) <-> session_id
        self._path_to_session_id: dict[Path, str] = {}
        self._session_to_path: dict[str, Path] = {}

        # 开始盯的那一刻已经躺在盘上的会话文件（纪律 1）。
        self._preexisting: set[str] = set()

        # 谁在被看。空集合 = 谁都不看，事件直接丢（纪律 3）。
        self._watch_ids: set[str] = set()

        # 去抖：事件只往这里登记「这个文件最后一次动是什么时候」，等待与处理由工作线程做。
        self._pending: dict[str, float] = {}
        self._cv = threading.Condition()
        self._worker: threading.Thread | None = None
        self._running = False

        if session_id_filter:
            self.watch_session(session_id_filter, watch_file=watch_file)

    # ---- lifecycle --------------------------------------------------------

    def start(self) -> None:
        """Register with the global watcher and begin listening."""
        if self._running:
            return

        if self._watch_dir is None:
            self._watch_dir = CLAUDE_PROJECTS_DIR / encode_project_path(self._project_path)
        self._watch_dir.mkdir(parents=True, exist_ok=True)

        # 开始盯之前，先把已经在盘上的会话文件记下来（纪律 1）。
        self._preexisting = {str(p.resolve()) for p in self._watch_dir.glob("*.jsonl")}

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

    def watch_session(
        self, session_id: str, *, watch_file: str | Path | None = None
    ) -> None:
        """登记一场会话及其确凿物理文件路径。没登记的会话，其事件当场丢弃。"""
        with self._cv:
            self._watch_ids.add(session_id)
            target_path: Path | None = None
            if watch_file is not None:
                target_path = Path(watch_file).resolve()
            else:
                try:
                    if self._family:
                        adapter = get_kernel_session_adapter(self._family)
                        located = adapter.locate_transcript(session_id)
                    else:
                        from frago.session.record_reader import locate_session_file

                        located = locate_session_file(session_id)
                    if located is not None:
                        target_path = located.resolve()
                except Exception:
                    target_path = None

            if target_path is not None:
                self._path_to_session_id[target_path] = session_id
                self._session_to_path[session_id] = target_path
            else:
                # 定位不到就只登记编号、不登记路径：这场会话的事件会一直被丢掉，直到有人
                # 给出确凿路径（``watch_file``）或适配器能定位到它。
                #
                # **这里从前会按 ``<watch_dir>/<session_id>.jsonl`` 拼一条路径兜底。**
                # 那个形状只对 Claude Code / CoreAgent 成立：codex 是 rollout 形状、
                # opencode 在 SQLite 里、agy 是 ``transcript.jsonl``。对另外三家拼出来
                # 必然是个不存在的文件，而它错得无声——登记成功、事件永远不来，页面上
                # 就是「这场会话半天不动」，没有任何地方报错。宁可明说定位不到。
                logger.warning(
                    "SessionStream: could not locate transcript for session %s; "
                    "registering it without a file binding (events will be dropped until a "
                    "concrete path is supplied via watch_file).",
                    session_id,
                )

    def unwatch_session(self, session_id: str) -> None:
        """撤掉一场会话的登记与确凿映射，连同其水位一起忘掉。"""
        with self._cv:
            self._watch_ids.discard(session_id)
            bound_path = self._session_to_path.pop(session_id, None)
            if bound_path is not None:
                self._path_to_session_id.pop(bound_path, None)
                self._preexisting.add(str(bound_path))
            if self._watch_dir is not None:
                standard_p = (Path(self._watch_dir) / f"{session_id}.jsonl").resolve()
                self._path_to_session_id.pop(standard_p, None)
                self._preexisting.add(str(standard_p))
                self._preexisting.add(str(Path(self._watch_dir) / f"{session_id}.jsonl"))

            for state in (self._file_seqs, self._file_handed, self._file_done, self._pending):
                for path_str in list(state):
                    canon_p = Path(path_str).resolve()
                    if (bound_path is not None and canon_p == bound_path) or canon_p.stem == session_id:
                        state.pop(path_str, None)

    def watching_any(self) -> bool:
        """还有没有登记着的会话。一场都没有时，这条流可以整个停掉。"""
        with self._cv:
            return bool(self._watch_ids)

    def get_session_for_path(self, file_path: str | Path) -> str | None:
        """根据精确双向路径映射解析会话编号。未登记或无关路径返回 None。"""
        with self._cv:
            return self._get_session_id_for_file(file_path)

    def get_session_file(self, session_id: str) -> Path | None:
        """获取已登记会话绑定的物理文件规范路径。"""
        with self._cv:
            return self._session_to_path.get(session_id)

    # ---- internal ---------------------------------------------------------

    def _get_session_id_for_file(self, file_path: str | Path) -> str | None:
        """根据精确双向路径映射与标准化规范路径解析会话编号。严禁单监听盲猜兜底。"""
        canon = Path(file_path).resolve()
        # 1. 优先查确凿双向映射
        sid = self._path_to_session_id.get(canon)
        if sid is not None and (not self._watch_ids or sid in self._watch_ids):
            return sid

        # 2. 匹配标准 Claude Code / CoreAgent 命名模式 (<session_id>.jsonl)。
        #    这一条只在编号**已经登记在册**时才认：文件名与登记过的编号对上，才把
        #    这条路径补进映射表。登记册是唯一的事实来源，文件名只是它的一个索引。
        if canon.stem in self._watch_ids:
            self._path_to_session_id[canon] = canon.stem
            self._session_to_path[canon.stem] = canon
            return canon.stem

        # 3. **到此为止。** 从前这里还有一条「没登记任何会话时，把任意 `.jsonl` 的文件名
        #    当会话编号返回」的兜底（注释说是给纯单测用的，但代码里没有这个限定）。它让
        #    任何一份恰好躺在监听目录里的 jsonl 都能冒充一场会话，与适配器注册表那套
        #    「按编号定位」的判据并存。纯单测要直接喂文件路径，走 ``watch_session`` 显式
        #    登记即可，不需要生产代码替它猜。
        return None

    def _observed_origin(self, session_id: str) -> str:
        """这场会话是从哪个面来的。

        判据次序：账本上明记的派活最硬（**认不认得出父亲都算 worker**，与
        ``session_origin`` 那套出身判定同一个口径），其余取这条流的观测面
        （``web`` / ``terminal`` / ``schedule`` / ``channel``）。

        从前这里没有这一格，补档一律写死 ``"terminal"``：人在页面上新开的那场会话
        于是在本体里也记成终端开的，页面按出身分栏时归错地方。出身只有观测方知道，
        这里就是那个观测方。
        """
        try:
            from frago.session.session_origin import load_origin_index

            if load_origin_index().is_worker(session_id):
                return "worker"
        except Exception:  # noqa: BLE001 — 判出身失败退回观测面，NEVER 因此不补档
            logger.debug("could not read origin index for %s", session_id, exc_info=True)
        return self._origin

    @staticmethod
    def _map_record_to_step_type(kind: str) -> str:
        """将 UnifiedRecord kind 映射为 SessionStepEvent 许可的 step_type。"""
        if kind == "user.say":
            return "user"
        if kind in ("agent.say", "agent.think"):
            return "assistant"
        if kind == "tool.call":
            return "tool_call"
        if kind == "tool.result":
            return "tool_result"
        return "system"

    def _on_file_event(self, event: FileEvent) -> None:
        """watchdog 的分发线程叫进来。这里只登记时刻，不做任何重活。"""
        if event.is_directory:
            return

        file_path = event.path
        with self._cv:
            session_id = self._get_session_id_for_file(file_path)
            if session_id is None or session_id not in self._watch_ids:
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
                    soonest = min(self._pending.values())
                    self._cv.wait(timeout=max(0.0, self._debounce - (now - soonest)))
                    continue
                for path in ready:
                    self._pending.pop(path, None)

            for path in ready:
                self._process_file(path)

    def _process_file(self, file_path: str) -> None:
        """通过统一适配器重读、提取增量记录、探针判定完成状态并合流驱动本体服务。"""
        try:
            session_id = self._get_session_id_for_file(file_path)
            if session_id is None or (self._watch_ids and session_id not in self._watch_ids):
                return

            family = self._family
            if family is None:
                from frago.session.record_reader import UnknownSessionFamily, detect_family

                try:
                    family = detect_family(session_id)
                except UnknownSessionFamily:
                    # 编号不属于已知任何一家：**不处理这场会话**，而不是挑一家当默认。
                    # 从前这里吞掉一切异常并静默退回 "claude-code"——那等于把别家的编号
                    # 拿去按 Claude Code 的格式解析，翻出来是空的，看起来像「这场会话没
                    # 记录」。认不出就说不认得出。
                    logger.info(
                        "SessionStream: session %s does not belong to any known kernel "
                        "family; skipping it.",
                        session_id,
                    )
                    return

            adapter = get_kernel_session_adapter(family)
            target_path = Path(file_path)

            records = adapter.read_unified_records(session_id, path=target_path)
            verdict = adapter.probe_turn_completion(session_id, path=target_path)
            done = verdict.done
            stop_reason = verdict.stop_reason

            first_sight = file_path not in self._file_seqs
            last_seq = self._file_seqs.get(file_path, -1)
            handed = self._file_handed.get(file_path)
            if handed is None:
                new_records = [r for r in records if r.seq > last_seq]
            else:
                # 认身份不认位置：只要这条记录的编号没交出去过，它就是新的，不管它排在几号。
                new_records = [r for r in records if r.id not in handed]

            canon_str = str(target_path.resolve())
            if new_records:
                self._file_seqs[file_path] = new_records[-1].seq
                if handed is None:
                    handed = self._file_handed[file_path] = set()
                handed.update(r.id for r in new_records)

                # 第一次看见一个开始盯之前就存在的文件：只对水位，一条不发（纪律 1）。
                replaying_history = first_sight and (
                    file_path in self._preexisting or canon_str in self._preexisting
                )

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

                # 合流驱动本体服务：登记单步事实与步数自增（防护存量未纳管会话）
                if not replaying_history and self._ontology_service is not None:
                    try:
                        self._ontology_service.ensure_managed_session(
                            session_id=session_id,
                            agent_kernel_id=family or "claude",
                            origin=self._observed_origin(session_id),
                        )
                        for r in new_records:
                            step_type = self._map_record_to_step_type(r.kind)
                            payload = r.payload if isinstance(r.payload, dict) else {}
                            tool_name = (
                                payload.get("tool_name") if isinstance(payload, dict) else None
                            )
                            self._ontology_service.record_session_step(
                                session_id=session_id,
                                step_type=step_type,
                                payload_dict=payload,
                                tool_name=tool_name,
                            )
                    except Exception:
                        logger.exception(
                            "SessionStream failed to record ontology steps for session %s",
                            session_id,
                        )

            # Check turn completion (only if new records arrived or not yet known)
            prev_done = self._file_done.get(file_path, False)

            # 第一次看见就只是对齐，不当成刚刚翻面
            if file_path not in self._file_done:
                self._file_done[file_path] = done
                return

            if done and not prev_done:
                self._file_done[file_path] = True

                # 合流驱动本体服务：跃迁至 awaiting_input 状态
                if self._ontology_service is not None:
                    try:
                        self._ontology_service.ensure_managed_session(
                            session_id=session_id,
                            agent_kernel_id=family or "claude",
                            origin=self._observed_origin(session_id),
                        )
                        self._ontology_service.yield_awaiting_input(
                            session_id=session_id,
                            waiting_reason=stop_reason or "end_turn",
                        )
                    except Exception:
                        logger.exception(
                            "SessionStream failed to transition ontology awaiting_input for session %s",
                            session_id,
                        )

                if self._on_turn_complete is not None:
                    try:
                        self._on_turn_complete(
                            session_id,
                            True,
                            stop_reason,
                        )
                    except Exception:
                        logger.exception(
                            "SessionStream on_turn_complete callback failed (session=%s)",
                            session_id,
                        )
            elif not done:
                self._file_done[file_path] = False

        except Exception:
            logger.exception("SessionStream failed to process file: %s", file_path)
