"""
会话监控器

使用 watchdog 监听 Claude Code 会话文件变化，提供：
- 会话关联逻辑（启动时间戳 + 项目路径匹配）
- 增量解析回调
- 并发会话隔离
- 会话结束检测
"""

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from watchdog.events import FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from frago.session.formatter import JsonFormatter, TerminalFormatter, create_formatter
from frago.session.models import (
    AgentType,
    MonitoredSession,
    SessionStatus,
    SessionStep,
    SessionSummary,
    ToolCallRecord,
)
from frago.session.parser import (
    IncrementalParser,
    ParsedRecord,
    record_to_step,
    update_tool_call_status,
)
from frago.session.storage import (
    append_step,
    generate_summary,
    update_metadata,
    write_metadata,
    write_summary,
)

logger = logging.getLogger(__name__)

# 默认 Claude Code 会话目录
DEFAULT_CLAUDE_DIR = Path.home() / ".claude" / "projects"

# 会话关联时间窗口（秒）
SESSION_MATCH_WINDOW_SECONDS = 10

# 无活动超时时间（秒）
INACTIVITY_TIMEOUT_SECONDS = 300


def get_claude_dir() -> Path:
    """获取 Claude Code 会话目录

    支持通过环境变量 FRAGO_CLAUDE_DIR 自定义。

    Returns:
        Claude Code 会话目录路径
    """
    custom_dir = os.environ.get("FRAGO_CLAUDE_DIR")
    if custom_dir:
        return Path(custom_dir).expanduser()
    return DEFAULT_CLAUDE_DIR


def encode_project_path(project_path: str) -> str:
    """将项目路径编码为 Claude Code 目录名

    Args:
        project_path: 项目绝对路径

    Returns:
        编码后的目录名
    """
    # Claude Code 使用连字符编码路径
    # /home/yammi/repos/Frago -> -home-yammi-repos-Frago
    return project_path.replace("/", "-")


# ============================================================
# 文件系统事件处理器
# ============================================================


class SessionFileHandler(FileSystemEventHandler):
    """会话文件变化处理器"""

    def __init__(
        self,
        on_new_records: Callable[[str, List[ParsedRecord]], None],
        target_file: Optional[str] = None,
    ):
        """初始化处理器

        Args:
            on_new_records: 新记录到达时的回调函数
            target_file: 只监控特定文件（可选）
        """
        super().__init__()
        self.on_new_records = on_new_records
        self.target_file = target_file
        self._parsers: Dict[str, IncrementalParser] = {}
        self._lock = threading.Lock()

    def on_modified(self, event: FileModifiedEvent) -> None:
        """处理文件修改事件"""
        if event.is_directory:
            return

        file_path = str(event.src_path)

        # 只处理 .jsonl 文件
        if not file_path.endswith(".jsonl"):
            return

        # 如果指定了目标文件，只处理该文件
        if self.target_file and file_path != self.target_file:
            return

        self._process_file(file_path)

    def _process_file(self, file_path: str) -> None:
        """处理文件更新

        Args:
            file_path: 文件路径
        """
        with self._lock:
            # 获取或创建解析器
            if file_path not in self._parsers:
                self._parsers[file_path] = IncrementalParser(file_path)

            parser = self._parsers[file_path]

        # 解析新记录
        records = parser.parse_new_records()
        if records:
            self.on_new_records(file_path, records)


# ============================================================
# 会话监控器
# ============================================================


class SessionMonitor:
    """会话监控器

    监控 Claude Code 会话文件，提供实时状态展示和持久化存储。
    """

    def __init__(
        self,
        project_path: str,
        start_time: Optional[datetime] = None,
        agent_type: AgentType = AgentType.CLAUDE,
        json_mode: bool = False,
        persist: bool = True,
        quiet: bool = False,
        target_session_id: Optional[str] = None,
    ):
        """初始化监控器

        Args:
            project_path: 项目路径
            start_time: 监控开始时间（用于关联会话）
            agent_type: Agent 类型
            json_mode: 是否使用 JSON 格式输出
            persist: 是否持久化存储
            quiet: 是否静默模式（不输出状态）
            target_session_id: 指定要监控的会话 ID（用于 resume 场景）
        """
        self.project_path = os.path.abspath(project_path)
        # 使用 UTC 时区，确保与 JSONL 中解析的时间戳类型一致
        self.start_time = start_time or datetime.now(timezone.utc)
        self.agent_type = agent_type
        self.json_mode = json_mode
        self.persist = persist
        self.quiet = quiet
        self.target_session_id = target_session_id

        # 会话状态
        self._session: Optional[MonitoredSession] = None
        self._step_id = 0
        self._pending_tool_calls: Dict[str, ToolCallRecord] = {}
        self._completed_tool_calls: List[ToolCallRecord] = []
        self._matched_file: Optional[str] = None

        # 监控状态
        self._observer: Optional[Observer] = None
        self._running = False
        self._lock = threading.Lock()

        # 格式化器
        if not quiet:
            self._formatter: Optional[
                Union[TerminalFormatter, JsonFormatter]
            ] = create_formatter(json_mode=json_mode)
        else:
            self._formatter = None

    @property
    def session(self) -> Optional[MonitoredSession]:
        """获取当前会话"""
        return self._session

    @property
    def session_id(self) -> Optional[str]:
        """获取当前会话 ID"""
        return self._session.session_id if self._session else None

    def start(self) -> None:
        """启动监控

        Raises:
            PermissionError: 没有权限访问目录
            OSError: 磁盘空间不足或其他 I/O 错误
        """
        if self._running:
            return

        claude_dir = get_claude_dir()
        encoded_path = encode_project_path(self.project_path)
        watch_dir = claude_dir / encoded_path

        # 检查并创建目录
        try:
            if not watch_dir.exists():
                logger.warning(f"Claude 会话目录不存在: {watch_dir}")
                watch_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            logger.error(f"没有权限创建目录 {watch_dir}: {e}")
            raise
        except OSError as e:
            # 可能是磁盘空间不足
            logger.error(f"无法创建目录 {watch_dir}: {e}")
            raise

        # 检查目录可读性
        try:
            list(watch_dir.iterdir())
        except PermissionError as e:
            logger.error(f"没有权限读取目录 {watch_dir}: {e}")
            raise

        # 如果指定了 target_session_id，直接定位目标文件
        if self.target_session_id:
            target_file = watch_dir / f"{self.target_session_id}.jsonl"
            if target_file.exists():
                self._matched_file = str(target_file)
                logger.info(f"直接监控指定会话: {self.target_session_id}")
            else:
                logger.warning(f"指定的会话文件不存在: {target_file}")

        # 创建文件监控
        handler = SessionFileHandler(
            on_new_records=self._on_new_records,
            target_file=self._matched_file,
        )

        try:
            self._observer = Observer()
            self._observer.schedule(handler, str(watch_dir), recursive=False)
            self._observer.start()
        except Exception as e:
            logger.error(f"启动文件监控失败: {e}")
            raise

        self._running = True
        logger.debug(f"开始监控目录: {watch_dir}")

    def stop(self) -> None:
        """停止监控"""
        if not self._running:
            return

        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=2)
            self._observer = None

        self._running = False

        # 结束会话
        if self._session:
            self._finalize_session()

    def wait_for_session(self, timeout: float = 30.0) -> bool:
        """等待会话关联

        Args:
            timeout: 超时时间（秒）

        Returns:
            是否成功关联会话
        """
        start = time.time()
        while time.time() - start < timeout:
            if self._session:
                return True
            time.sleep(0.1)
        return False

    def wait_for_completion(
        self,
        timeout: Optional[float] = None,
        inactivity_timeout: float = INACTIVITY_TIMEOUT_SECONDS,
    ) -> bool:
        """等待会话完成

        Args:
            timeout: 总超时时间（秒），None 表示无限等待
            inactivity_timeout: 无活动超时时间（秒）

        Returns:
            是否正常完成
        """
        start = time.time()
        last_activity = time.time()

        while True:
            # 检查总超时
            if timeout and (time.time() - start) > timeout:
                logger.warning("等待超时")
                return False

            # 检查无活动超时
            if self._session:
                session_last = self._session.last_activity.timestamp()
                if session_last > last_activity:
                    last_activity = session_last

            if (time.time() - last_activity) > inactivity_timeout:
                logger.info("无活动超时，结束监控")
                self._finalize_session(SessionStatus.COMPLETED)
                return True

            # 检查会话状态
            if self._session and self._session.status != SessionStatus.RUNNING:
                return self._session.status == SessionStatus.COMPLETED

            time.sleep(0.5)

    def _on_new_records(self, file_path: str, records: List[ParsedRecord]) -> None:
        """处理新记录到达

        Args:
            file_path: 文件路径
            records: 新记录列表
        """
        with self._lock:
            for record in records:
                # 尝试关联会话
                if not self._session:
                    if self._try_match_session(file_path, record):
                        self._matched_file = file_path
                    else:
                        continue

                # 处理记录
                self._process_record(record)

    def _try_match_session(self, file_path: str, record: ParsedRecord) -> bool:
        """尝试关联会话

        Args:
            file_path: 文件路径
            record: 解析后的记录

        Returns:
            是否成功关联
        """
        session_id = record.session_id
        if not session_id:
            return False

        # 如果指定了 target_session_id，只匹配该会话
        if self.target_session_id:
            if session_id != self.target_session_id:
                return False
            # 指定会话时跳过时间窗口检查
        else:
            # 未指定时，检查时间窗口
            record_time = record.timestamp
            delta = abs((record_time - self.start_time).total_seconds())

            if delta > SESSION_MATCH_WINDOW_SECONDS:
                # 时间差过大，跳过
                return False

        self._session = MonitoredSession(
            session_id=session_id,
            agent_type=self.agent_type,
            project_path=self.project_path,
            source_file=file_path,
            started_at=self.start_time,
            last_activity=datetime.now(),
        )

        # 持久化
        if self.persist:
            write_metadata(self._session)

        # 输出会话开始
        if self._formatter:
            if isinstance(self._formatter, TerminalFormatter):
                self._formatter.print_session_start(self._session)
            else:
                self._formatter.emit_session_start(self._session)

        logger.info(f"关联会话: {session_id}")
        return True

    def _process_record(self, record: ParsedRecord) -> None:
        """处理单条记录

        Args:
            record: 解析后的记录
        """
        # 更新最后活动时间
        self._session.last_activity = datetime.now()

        # 转换为步骤
        self._step_id += 1
        step, tool_calls = record_to_step(record, self._step_id)

        if step:
            # 确保 step 使用监控器关联的 session_id（防止 agent 文件的 session_id 指向父会话）
            step.session_id = self._session.session_id

            # 更新计数
            self._session.step_count = self._step_id

            # 持久化步骤
            if self.persist:
                append_step(step, self.agent_type)

            # 输出步骤
            if self._formatter:
                if isinstance(self._formatter, TerminalFormatter):
                    self._formatter.print_step(step)
                else:
                    self._formatter.emit_step(step)

        # 处理工具调用
        for tc in tool_calls:
            # 同样确保 tool_call 使用正确的 session_id
            tc.session_id = self._session.session_id
            self._pending_tool_calls[tc.tool_call_id] = tc
            self._session.tool_call_count += 1

        # 处理工具结果
        if record.tool_results:
            completed = update_tool_call_status(self._pending_tool_calls, record)
            for tc in completed:
                self._completed_tool_calls.append(tc)

                # 输出工具完成
                if self._formatter:
                    if isinstance(self._formatter, TerminalFormatter):
                        self._formatter.print_tool_complete(tc)
                    else:
                        self._formatter.emit_tool_complete(tc)

        # 更新元数据
        if self.persist and self._session:
            update_metadata(
                self._session.session_id,
                self.agent_type,
                step_count=self._session.step_count,
                tool_call_count=self._session.tool_call_count,
                last_activity=self._session.last_activity,
            )

    def _finalize_session(
        self, status: SessionStatus = SessionStatus.COMPLETED
    ) -> None:
        """结束会话

        Args:
            status: 最终状态
        """
        if not self._session:
            return

        self._session.status = status
        self._session.ended_at = datetime.now()

        # 生成并保存摘要
        summary = None
        if self.persist:
            update_metadata(
                self._session.session_id,
                self.agent_type,
                status=status,
                ended_at=self._session.ended_at,
            )
            write_summary(
                self._session.session_id,
                self.agent_type,
                self._completed_tool_calls,
            )
            summary = generate_summary(
                self._session.session_id,
                self.agent_type,
                self._completed_tool_calls,
            )

        # 输出会话结束
        if self._formatter:
            if isinstance(self._formatter, TerminalFormatter):
                self._formatter.print_session_end(self._session, summary)
            else:
                self._formatter.emit_session_end(self._session, summary)


# ============================================================
# 独立监控函数
# ============================================================


def watch_session(
    session_id: str,
    agent_type: AgentType = AgentType.CLAUDE,
    json_mode: bool = False,
) -> None:
    """监控指定会话

    用于在另一个终端实时查看正在进行的会话。

    Args:
        session_id: 会话 ID
        agent_type: Agent 类型
        json_mode: 是否使用 JSON 格式输出
    """
    from frago.session.storage import get_session_dir, read_metadata

    # 获取会话信息
    session = read_metadata(session_id, agent_type)
    if not session:
        logger.error(f"会话不存在: {session_id}")
        return

    if session.status != SessionStatus.RUNNING:
        logger.info(f"会话已结束: {session.status.value}")
        return

    # 创建监控器
    monitor = SessionMonitor(
        project_path=session.project_path,
        start_time=session.started_at,
        agent_type=agent_type,
        json_mode=json_mode,
        persist=False,  # 不重复持久化
        quiet=False,
    )

    # 设置已关联的会话
    monitor._session = session
    monitor._matched_file = session.source_file

    try:
        monitor.start()
        monitor.wait_for_completion()
    except KeyboardInterrupt:
        pass
    finally:
        monitor.stop()


def watch_latest_session(
    agent_type: AgentType = AgentType.CLAUDE,
    json_mode: bool = False,
) -> None:
    """监控最新的活跃会话

    Args:
        agent_type: Agent 类型
        json_mode: 是否使用 JSON 格式输出
    """
    from frago.session.storage import list_sessions

    sessions = list_sessions(agent_type=agent_type, status=SessionStatus.RUNNING)
    if not sessions:
        logger.info("没有正在进行的会话")
        return

    latest = sessions[0]
    logger.info(f"监控会话: {latest.session_id[:8]}...")
    watch_session(latest.session_id, agent_type, json_mode)


# ============================================================
# Agent 适配器接口（为未来扩展预留）
# ============================================================


class AgentAdapter:
    """Agent 适配器抽象基类

    为不同的 Agent 工具（Claude Code, Cursor, Cline 等）提供统一的
    会话文件定位和解析接口。

    子类需要实现以下方法：
    - get_session_dir(): 获取会话文件所在目录
    - encode_project_path(): 编码项目路径
    - parse_record(): 解析原始记录
    """

    def __init__(self, agent_type: AgentType):
        """初始化适配器

        Args:
            agent_type: Agent 类型
        """
        self.agent_type = agent_type

    def get_session_dir(self, project_path: str) -> Path:
        """获取项目对应的会话文件目录

        Args:
            project_path: 项目绝对路径

        Returns:
            会话文件所在目录
        """
        raise NotImplementedError

    def encode_project_path(self, project_path: str) -> str:
        """将项目路径编码为目录名

        Args:
            project_path: 项目绝对路径

        Returns:
            编码后的目录名
        """
        raise NotImplementedError

    def parse_record(self, data: Dict) -> Optional[ParsedRecord]:
        """解析原始记录

        Args:
            data: 原始 JSON 数据

        Returns:
            解析后的记录
        """
        raise NotImplementedError


class ClaudeCodeAdapter(AgentAdapter):
    """Claude Code 适配器

    支持 Claude Code 的会话文件格式和目录结构。
    """

    def __init__(self):
        super().__init__(AgentType.CLAUDE)

    def get_session_dir(self, project_path: str) -> Path:
        """获取 Claude Code 项目的会话目录"""
        claude_dir = get_claude_dir()
        encoded = self.encode_project_path(project_path)
        return claude_dir / encoded

    def encode_project_path(self, project_path: str) -> str:
        """Claude Code 使用连字符编码路径"""
        return project_path.replace("/", "-")

    def parse_record(self, data: Dict) -> Optional[ParsedRecord]:
        """使用 parser 模块解析 Claude Code 记录"""
        from frago.session.parser import IncrementalParser

        parser = IncrementalParser("")
        return parser._parse_record(data)


# 适配器注册表
_adapters: Dict[AgentType, AgentAdapter] = {
    AgentType.CLAUDE: ClaudeCodeAdapter(),
}


def get_adapter(agent_type: AgentType) -> Optional[AgentAdapter]:
    """获取指定 Agent 类型的适配器

    Args:
        agent_type: Agent 类型

    Returns:
        适配器实例，不支持的类型返回 None
    """
    return _adapters.get(agent_type)


def register_adapter(adapter: AgentAdapter) -> None:
    """注册自定义适配器

    Args:
        adapter: 适配器实例
    """
    _adapters[adapter.agent_type] = adapter
