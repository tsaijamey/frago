"""
Session Monitor

Uses watchdog to monitor Claude Code session file changes, providing:
- Session association logic (startup timestamp + project path matching)
- Incremental parsing callbacks
- Concurrent session isolation
- Session end detection
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
    SessionSource,
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

# Default Claude Code session directory
DEFAULT_CLAUDE_DIR = Path.home() / ".claude" / "projects"

# Session association time window (seconds)
SESSION_MATCH_WINDOW_SECONDS = 10

# Inactivity timeout (seconds)
INACTIVITY_TIMEOUT_SECONDS = 300


def get_claude_dir() -> Path:
    """Get Claude Code session directory

    Supports customization via environment variable FRAGO_CLAUDE_DIR.

    Returns:
        Claude Code session directory path
    """
    custom_dir = os.environ.get("FRAGO_CLAUDE_DIR")
    if custom_dir:
        return Path(custom_dir).expanduser()
    return DEFAULT_CLAUDE_DIR


def encode_project_path(project_path: str) -> str:
    """Encode project path as Claude Code directory name

    Args:
        project_path: Project absolute path

    Returns:
        Encoded directory name
    """
    # 1. Normalize path separators (Windows \ -> /)
    normalized = project_path.replace("\\", "/")

    # 2. Handle Windows drive letter (C: -> C-)
    # Claude replaces : with -, so C:/Users -> C-/Users
    if len(normalized) >= 2 and normalized[1] == ":":
        normalized = normalized[0] + "-" + normalized[2:]

    # 3. Claude Code uses hyphens to encode paths
    # /home/yammi/repos/Frago -> -home-yammi-repos-Frago
    # C-/Users/yammi -> C--Users-yammi
    return normalized.replace("/", "-")


# ============================================================
# File System Event Handler
# ============================================================


class SessionFileHandler(FileSystemEventHandler):
    """Session file change handler"""

    def __init__(
        self,
        on_new_records: Callable[[str, List[ParsedRecord]], None],
        target_file: Optional[str] = None,
    ):
        """Initialize handler

        Args:
            on_new_records: Callback function when new records arrive
            target_file: Only monitor specific file (optional)
        """
        super().__init__()
        self.on_new_records = on_new_records
        self.target_file = target_file
        self._parsers: Dict[str, IncrementalParser] = {}
        self._lock = threading.Lock()

    def on_modified(self, event: FileModifiedEvent) -> None:
        """Handle file modification event"""
        if event.is_directory:
            return

        file_path = str(event.src_path)

        # Only process .jsonl files
        if not file_path.endswith(".jsonl"):
            return

        # If target file specified, only process that file
        if self.target_file and file_path != self.target_file:
            return

        self._process_file(file_path)

    def _process_file(self, file_path: str) -> None:
        """Process file update

        Args:
            file_path: File path
        """
        with self._lock:
            # Get or create parser
            if file_path not in self._parsers:
                self._parsers[file_path] = IncrementalParser(file_path)

            parser = self._parsers[file_path]

        # Parse new records
        records = parser.parse_new_records()
        if records:
            self.on_new_records(file_path, records)


# ============================================================
# Session Monitor
# ============================================================


class SessionMonitor:
    """Session Monitor

    Monitors Claude Code session files, provides real-time status display and persistent storage.
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
        source: SessionSource = SessionSource.TERMINAL,
    ):
        """Initialize monitor

        Args:
            project_path: Project path
            start_time: Monitor start time (for session association)
            agent_type: Agent type
            json_mode: Whether to use JSON format output
            persist: Whether to persist storage
            quiet: Whether to use quiet mode (no status output)
            target_session_id: Specified session ID to monitor (for resume scenario)
            source: Session source (terminal/web) for tracking origin
        """
        self.project_path = os.path.abspath(project_path)
        # Use UTC timezone to ensure consistency with timestamps parsed from JSONL
        self.start_time = start_time or datetime.now(timezone.utc)
        self.agent_type = agent_type
        self.json_mode = json_mode
        self.persist = persist
        self.quiet = quiet
        self.target_session_id = target_session_id
        self.source = source

        # Session state
        self._session: Optional[MonitoredSession] = None
        self._step_id = 0
        self._pending_tool_calls: Dict[str, ToolCallRecord] = {}
        self._completed_tool_calls: List[ToolCallRecord] = []
        self._matched_file: Optional[str] = None

        # Monitor state
        self._observer: Optional[Observer] = None
        self._running = False
        self._lock = threading.Lock()

        # Formatter
        if not quiet:
            self._formatter: Optional[
                Union[TerminalFormatter, JsonFormatter]
            ] = create_formatter(json_mode=json_mode)
        else:
            self._formatter = None

    @property
    def session(self) -> Optional[MonitoredSession]:
        """Get current session"""
        return self._session

    @property
    def session_id(self) -> Optional[str]:
        """Get current session ID"""
        return self._session.session_id if self._session else None

    def start(self) -> None:
        """Start monitoring

        Raises:
            PermissionError: No permission to access directory
            OSError: Insufficient disk space or other I/O errors
        """
        if self._running:
            return

        claude_dir = get_claude_dir()
        encoded_path = encode_project_path(self.project_path)
        watch_dir = claude_dir / encoded_path

        # Check and create directory (it's normal for directory not to exist on first use)
        try:
            if not watch_dir.exists():
                logger.debug(f"Claude session directory does not exist, creating: {watch_dir}")
                watch_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            logger.error(f"No permission to create directory {watch_dir}: {e}")
            raise
        except OSError as e:
            # Possibly insufficient disk space
            logger.error(f"Cannot create directory {watch_dir}: {e}")
            raise

        # Check directory readability
        try:
            list(watch_dir.iterdir())
        except PermissionError as e:
            logger.error(f"No permission to read directory {watch_dir}: {e}")
            raise

        # If target_session_id is specified, directly locate target file
        if self.target_session_id:
            target_file = watch_dir / f"{self.target_session_id}.jsonl"
            if target_file.exists():
                self._matched_file = str(target_file)
                logger.info(f"Directly monitoring specified session: {self.target_session_id}")
            else:
                logger.warning(f"Specified session file does not exist: {target_file}")

        # Create file monitoring
        handler = SessionFileHandler(
            on_new_records=self._on_new_records,
            target_file=self._matched_file,
        )

        try:
            self._observer = Observer()
            self._observer.schedule(handler, str(watch_dir), recursive=False)
            self._observer.start()
        except Exception as e:
            logger.error(f"Failed to start file monitoring: {e}")
            raise

        self._running = True
        logger.debug(f"Started monitoring directory: {watch_dir}")

    def stop(self) -> None:
        """Stop monitoring"""
        if not self._running:
            return

        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=2)
            self._observer = None

        self._running = False

        # Finalize session
        if self._session:
            self._finalize_session()

    def wait_for_session(self, timeout: float = 30.0) -> bool:
        """Wait for session association

        Args:
            timeout: Timeout (seconds)

        Returns:
            Whether session association was successful
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
        """Wait for session completion

        Args:
            timeout: Total timeout (seconds), None for infinite wait
            inactivity_timeout: Inactivity timeout (seconds)

        Returns:
            Whether completed normally
        """
        start = time.time()
        last_activity = time.time()

        while True:
            # Check total timeout
            if timeout and (time.time() - start) > timeout:
                logger.warning("Wait timeout")
                return False

            # Check inactivity timeout
            if self._session:
                session_last = self._session.last_activity.timestamp()
                if session_last > last_activity:
                    last_activity = session_last

            if (time.time() - last_activity) > inactivity_timeout:
                logger.info("Inactivity timeout, ending monitoring")
                self._finalize_session(SessionStatus.COMPLETED)
                return True

            # Check session status
            if self._session and self._session.status != SessionStatus.RUNNING:
                return self._session.status == SessionStatus.COMPLETED

            time.sleep(0.5)

    def _on_new_records(self, file_path: str, records: List[ParsedRecord]) -> None:
        """Handle new record arrival

        Args:
            file_path: File path
            records: New record list
        """
        with self._lock:
            for record in records:
                # Try to associate session
                if not self._session:
                    if self._try_match_session(file_path, record):
                        self._matched_file = file_path
                    else:
                        continue

                # Process record
                self._process_record(record)

    def _try_match_session(self, file_path: str, record: ParsedRecord) -> bool:
        """Try to associate session

        Args:
            file_path: File path
            record: Parsed record

        Returns:
            Whether association was successful
        """
        session_id = record.session_id
        if not session_id:
            return False

        # If target_session_id is specified, only match that session
        if self.target_session_id:
            if session_id != self.target_session_id:
                return False
            # Skip time window check for specified session
        else:
            # When not specified, check time window
            record_time = record.timestamp
            delta = abs((record_time - self.start_time).total_seconds())

            if delta > SESSION_MATCH_WINDOW_SECONDS:
                # Time difference too large, skip
                return False

        self._session = MonitoredSession(
            session_id=session_id,
            agent_type=self.agent_type,
            project_path=self.project_path,
            source_file=file_path,
            started_at=self.start_time,
            last_activity=datetime.now(timezone.utc),
            source=self.source,
        )

        # Persist
        if self.persist:
            write_metadata(self._session)

        # Output session start
        if self._formatter:
            if isinstance(self._formatter, TerminalFormatter):
                self._formatter.print_session_start(self._session)
            else:
                self._formatter.emit_session_start(self._session)

        logger.info(f"Associated session: {session_id}")
        return True

    def _process_record(self, record: ParsedRecord) -> None:
        """Process single record

        Args:
            record: Parsed record
        """
        # Update last activity time (use UTC to ensure consistency with other timestamps)
        self._session.last_activity = datetime.now(timezone.utc)

        # Convert to step
        self._step_id += 1
        step, tool_calls = record_to_step(record, self._step_id)

        if step:
            # Ensure step uses monitor's associated session_id (prevent agent file's session_id from pointing to parent session)
            step.session_id = self._session.session_id

            # Update count
            self._session.step_count = self._step_id

            # Persist step
            if self.persist:
                append_step(step, self.agent_type)

            # Output step
            if self._formatter:
                if isinstance(self._formatter, TerminalFormatter):
                    self._formatter.print_step(step)
                else:
                    self._formatter.emit_step(step)

        # Process tool calls
        for tc in tool_calls:
            # Also ensure tool_call uses correct session_id
            tc.session_id = self._session.session_id
            self._pending_tool_calls[tc.tool_call_id] = tc
            self._session.tool_call_count += 1

        # Process tool results
        if record.tool_results:
            completed = update_tool_call_status(self._pending_tool_calls, record)
            for tc in completed:
                self._completed_tool_calls.append(tc)

                # Output tool completion
                if self._formatter:
                    if isinstance(self._formatter, TerminalFormatter):
                        self._formatter.print_tool_complete(tc)
                    else:
                        self._formatter.emit_tool_complete(tc)

        # Update metadata
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
        """Finalize session

        Args:
            status: Final status
        """
        if not self._session:
            return

        self._session.status = status
        self._session.ended_at = datetime.now(timezone.utc)

        # Generate and save summary
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

        # Output session end
        if self._formatter:
            if isinstance(self._formatter, TerminalFormatter):
                self._formatter.print_session_end(self._session, summary)
            else:
                self._formatter.emit_session_end(self._session, summary)


# ============================================================
# Standalone Monitor Functions
# ============================================================


def watch_session(
    session_id: str,
    agent_type: AgentType = AgentType.CLAUDE,
    json_mode: bool = False,
) -> None:
    """Monitor specified session

    Used to view ongoing session in real-time from another terminal.

    Args:
        session_id: Session ID
        agent_type: Agent type
        json_mode: Whether to use JSON format output
    """
    from frago.session.storage import get_session_dir, read_metadata

    # Get session info
    session = read_metadata(session_id, agent_type)
    if not session:
        logger.error(f"Session does not exist: {session_id}")
        return

    if session.status != SessionStatus.RUNNING:
        logger.info(f"Session has ended: {session.status.value}")
        return

    # Create monitor
    monitor = SessionMonitor(
        project_path=session.project_path,
        start_time=session.started_at,
        agent_type=agent_type,
        json_mode=json_mode,
        persist=False,  # Don't duplicate persistence
        quiet=False,
    )

    # Set associated session
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
    """Monitor latest active session

    Args:
        agent_type: Agent type
        json_mode: Whether to use JSON format output
    """
    from frago.session.storage import list_sessions

    sessions = list_sessions(agent_type=agent_type, status=SessionStatus.RUNNING)
    if not sessions:
        logger.info("No active sessions")
        return

    latest = sessions[0]
    logger.info(f"Monitoring session: {latest.session_id[:8]}...")
    watch_session(latest.session_id, agent_type, json_mode)


# ============================================================
# Agent Adapter Interface (Reserved for Future Extension)
# ============================================================


class AgentAdapter:
    """Agent adapter abstract base class

    Provides unified session file location and parsing interface for different
    Agent tools (Claude Code, Cursor, Cline, etc.).

    Subclasses need to implement:
    - get_session_dir(): Get session file directory
    - encode_project_path(): Encode project path
    - parse_record(): Parse raw record
    """

    def __init__(self, agent_type: AgentType):
        """Initialize adapter

        Args:
            agent_type: Agent type
        """
        self.agent_type = agent_type

    def get_session_dir(self, project_path: str) -> Path:
        """Get session file directory for project

        Args:
            project_path: Project absolute path

        Returns:
            Session file directory
        """
        raise NotImplementedError

    def encode_project_path(self, project_path: str) -> str:
        """Encode project path as directory name

        Args:
            project_path: Project absolute path

        Returns:
            Encoded directory name
        """
        raise NotImplementedError

    def parse_record(self, data: Dict) -> Optional[ParsedRecord]:
        """Parse raw record

        Args:
            data: Raw JSON data

        Returns:
            Parsed record
        """
        raise NotImplementedError


class ClaudeCodeAdapter(AgentAdapter):
    """Claude Code adapter

    Supports Claude Code's session file format and directory structure.
    """

    def __init__(self):
        super().__init__(AgentType.CLAUDE)

    def get_session_dir(self, project_path: str) -> Path:
        """Get Claude Code project's session directory"""
        claude_dir = get_claude_dir()
        encoded = self.encode_project_path(project_path)
        return claude_dir / encoded

    def encode_project_path(self, project_path: str) -> str:
        """Claude Code uses hyphens to encode paths"""
        return project_path.replace("/", "-")

    def parse_record(self, data: Dict) -> Optional[ParsedRecord]:
        """Parse Claude Code record using parser module"""
        from frago.session.parser import IncrementalParser

        parser = IncrementalParser("")
        return parser._parse_record(data)


# Adapter registry
_adapters: Dict[AgentType, AgentAdapter] = {
    AgentType.CLAUDE: ClaudeCodeAdapter(),
}


def get_adapter(agent_type: AgentType) -> Optional[AgentAdapter]:
    """Get adapter for specified Agent type

    Args:
        agent_type: Agent type

    Returns:
        Adapter instance, None if type not supported
    """
    return _adapters.get(agent_type)


def register_adapter(adapter: AgentAdapter) -> None:
    """Register custom adapter

    Args:
        adapter: Adapter instance
    """
    _adapters[adapter.agent_type] = adapter
