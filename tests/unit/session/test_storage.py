"""Tests for frago.session.storage module.

Tests session data persistence: directory management, metadata, steps, summary.
"""
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from frago.session.models import (
    AgentType,
    MonitoredSession,
    SessionStatus,
    SessionStep,
    StepType,
)
from frago.session.storage import (
    RAW_FILENAME,
    STALE_RUNNING_SECONDS,
    append_step,
    clean_old_sessions,
    count_sessions,
    create_session_dir,
    find_session_by_prefix,
    get_session_base_dir,
    get_session_dir,
    is_managed_session,
    list_sessions,
    read_metadata,
    read_steps,
    write_metadata,
)


class TestGetSessionBaseDir:
    """Test get_session_base_dir() function."""

    def test_default_directory(self, monkeypatch):
        """Without env var, should fall back to the module's default constant.

        比的是模块常量本身，NEVER 在测试里重新拼一遍 `Path.home() / ...` ——
        真人数据防护（见 tests/conftest.py）会把这类常量改指到临时目录，
        自己拼真实家目录等于断言「防护没生效」。
        """
        from frago.session import storage

        monkeypatch.delenv("FRAGO_SESSION_DIR", raising=False)
        result = get_session_base_dir()
        assert result == storage.DEFAULT_SESSION_DIR
        assert result.parts[-2:] == (".frago", "sessions")

    def test_custom_directory_from_env(self, monkeypatch):
        """With FRAGO_SESSION_DIR set, should return custom path."""
        monkeypatch.setenv("FRAGO_SESSION_DIR", "/custom/path/sessions")
        result = get_session_base_dir()
        assert result == Path("/custom/path/sessions")

    def test_expanduser_in_env(self, monkeypatch):
        """Should expand ~ in env var path."""
        monkeypatch.setenv("FRAGO_SESSION_DIR", "~/my-sessions")
        result = get_session_base_dir()
        assert result == Path.home() / "my-sessions"


class TestGetSessionDir:
    """Test get_session_dir() function."""

    def test_default_agent_type(self, mock_home):
        """Default agent type should be CLAUDE."""
        result = get_session_dir("test-session-123")
        assert result.name == "test-session-123"
        assert result.parent.name == "claude"

    def test_explicit_agent_type(self, mock_home):
        """Explicit agent type should be reflected in path."""
        result = get_session_dir("test-session-123", AgentType.CLAUDE)
        assert "claude" in str(result)


class TestCreateSessionDir:
    """Test create_session_dir() function."""

    def test_creates_directory(self, mock_home):
        """Should create session directory."""
        session_id = "new-session-456"
        result = create_session_dir(session_id)

        assert result.exists()
        assert result.is_dir()
        assert result.name == session_id

    def test_idempotent(self, mock_home):
        """Calling multiple times should not fail."""
        session_id = "idempotent-session"
        result1 = create_session_dir(session_id)
        result2 = create_session_dir(session_id)

        assert result1 == result2
        assert result1.exists()


class TestWriteAndReadMetadata:
    """Test write_metadata() and read_metadata() functions."""

    @pytest.fixture
    def sample_session(self) -> MonitoredSession:
        """Create sample MonitoredSession."""
        return MonitoredSession(
            session_id="meta-test-session",
            agent_type=AgentType.CLAUDE,
            status=SessionStatus.RUNNING,
            project_path="/home/test/project",
            source_file="/home/test/.claude/projects/-home-test-project/session.jsonl",
            started_at=datetime.now(UTC),
            last_activity=datetime.now(UTC),
        )

    def test_write_creates_file(self, mock_home, sample_session):
        """write_metadata should create metadata.json file."""
        result_path = write_metadata(sample_session)

        assert result_path.exists()
        assert result_path.name == "metadata.json"

    def test_read_returns_session(self, mock_home, sample_session):
        """read_metadata should return MonitoredSession object."""
        write_metadata(sample_session)
        result = read_metadata(sample_session.session_id)

        assert result is not None
        assert result.session_id == sample_session.session_id
        assert result.project_path == sample_session.project_path

    def test_read_nonexistent_returns_none(self, mock_home):
        """read_metadata for non-existent session should return None."""
        result = read_metadata("nonexistent-session-id")
        assert result is None

    def test_roundtrip_preserves_data(self, mock_home, sample_session):
        """Write then read should preserve all data."""
        write_metadata(sample_session)
        result = read_metadata(sample_session.session_id)

        assert result.session_id == sample_session.session_id
        assert result.agent_type == sample_session.agent_type
        assert result.status == sample_session.status
        assert result.project_path == sample_session.project_path


class TestAppendAndReadSteps:
    """Test append_step() and read_steps() functions."""

    @pytest.fixture
    def sample_step(self) -> SessionStep:
        """Create sample SessionStep."""
        return SessionStep(
            step_id=1,
            session_id="steps-test-session",
            type=StepType.USER_MESSAGE,
            timestamp=datetime.now(UTC),
            content_summary="Test user message",
            raw_uuid="uuid-123-456",
        )

    def test_append_creates_file(self, mock_home, sample_step):
        """append_step should create steps.jsonl file."""
        result_path = append_step(sample_step)

        assert result_path.exists()
        assert result_path.name == "steps.jsonl"

    def test_append_multiple_steps(self, mock_home, sample_step):
        """Multiple appends should add lines to file."""
        append_step(sample_step)

        step2 = SessionStep(
            step_id=2,
            session_id=sample_step.session_id,
            type=StepType.ASSISTANT_MESSAGE,
            timestamp=datetime.now(UTC),
            content_summary="Test assistant response",
            raw_uuid="uuid-789-abc",
        )
        result_path = append_step(step2)

        # Read file and count lines
        lines = result_path.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_read_returns_steps(self, mock_home, sample_step):
        """read_steps should return list of SessionStep objects."""
        append_step(sample_step)
        result = read_steps(sample_step.session_id)

        assert len(result) == 1
        assert result[0].step_id == sample_step.step_id
        assert result[0].content_summary == sample_step.content_summary

    def test_read_nonexistent_returns_empty(self, mock_home):
        """read_steps for non-existent session should return empty list."""
        result = read_steps("nonexistent-session-id")
        assert result == []

    def test_read_preserves_order(self, mock_home):
        """Steps should be returned in order of appending."""
        session_id = "order-test-session"

        for i in range(5):
            step = SessionStep(
                step_id=i + 1,
                session_id=session_id,
                type=StepType.USER_MESSAGE,
                timestamp=datetime.now(UTC),
                content_summary=f"Message {i + 1}",
                raw_uuid=f"uuid-{i}",
            )
            append_step(step)

        result = read_steps(session_id)

        assert len(result) == 5
        for i, step in enumerate(result):
            assert step.step_id == i + 1
            assert step.content_summary == f"Message {i + 1}"


class TestGenerateSummaryDuration:
    """Regression: mixed naive/aware timestamps must not break the duration
    calc — was the dashboard's recurring 'Failed to compute recent tasks:
    can't subtract offset-naive and offset-aware datetimes' every poll."""

    def test_mixed_tz_timestamps_no_raise(self, mock_home):
        from datetime import timedelta

        from frago.session.storage import generate_summary

        aware = datetime.now(UTC)
        naive_later = aware.replace(tzinfo=None) + timedelta(seconds=5)
        session = MonitoredSession(
            session_id="tz-mix-session",
            agent_type=AgentType.CLAUDE,
            status=SessionStatus.RUNNING,
            project_path="/home/test/project",
            source_file="/home/test/.claude/projects/x/session.jsonl",
            started_at=aware,            # tz-aware
            ended_at=naive_later,        # tz-naive — the mismatch that crashed
            last_activity=naive_later,
        )
        write_metadata(session)

        summary = generate_summary("tz-mix-session")  # must not raise

        assert summary is not None
        assert summary.total_duration_ms == 5000


class TestSessionsOnDiskAreListed:
    """会话清单以「目录里有没有内容」为准，不以有没有 metadata.json 为准。

    背景：``metadata.json`` 只有 frago 亲自监控过的会话才有，你自己在终端或网页跑的
    会话经同步程序只落一份 ``raw.jsonl``。旧口径只认前者，于是盘上明明有几千场会话，
    清单里一场都看不到，且每用一天多缺一批。
    """

    @staticmethod
    def _mk_raw_only(base: Path, session_id: str, age_seconds: float = 0.0) -> Path:
        """造一场「只有原文副本、没有 metadata」的会话。"""
        session_dir = base / "claude" / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        raw = session_dir / RAW_FILENAME
        raw.write_text('{"type":"user","message":{"content":"hi"}}\n', encoding="utf-8")
        if age_seconds:
            stamp = time.time() - age_seconds
            os.utime(raw, (stamp, stamp))
        return session_dir

    def test_raw_only_session_appears_in_list(self, mock_home):
        base = get_session_base_dir()
        self._mk_raw_only(base, "raw-only-session")

        ids = [s.session_id for s in list_sessions(limit=100)]

        assert "raw-only-session" in ids

    def test_raw_only_session_opens_by_id(self, mock_home):
        base = get_session_base_dir()
        self._mk_raw_only(base, "raw-only-session")

        session = read_metadata("raw-only-session", AgentType.CLAUDE)

        assert session is not None
        assert session.session_id == "raw-only-session"

    def test_raw_only_session_resolves_by_prefix(self, mock_home):
        base = get_session_base_dir()
        self._mk_raw_only(base, "abcdef01-2345-6789-abcd-ef0123456789")

        session = find_session_by_prefix("abcdef01", AgentType.CLAUDE)

        assert session is not None
        assert session.session_id == "abcdef01-2345-6789-abcd-ef0123456789"

    def test_empty_directory_is_not_a_session(self, mock_home):
        base = get_session_base_dir()
        (base / "claude" / "empty-dir").mkdir(parents=True)

        assert "empty-dir" not in [s.session_id for s in list_sessions(limit=100)]

    def test_empty_raw_file_is_not_a_session(self, mock_home):
        base = get_session_base_dir()
        session_dir = base / "claude" / "zero-byte"
        session_dir.mkdir(parents=True)
        (session_dir / RAW_FILENAME).write_text("", encoding="utf-8")

        assert "zero-byte" not in [s.session_id for s in list_sessions(limit=100)]

    def test_count_agrees_with_list(self, mock_home):
        base = get_session_base_dir()
        self._mk_raw_only(base, "raw-only-session")
        write_metadata(
            MonitoredSession(
                session_id="managed-session",
                agent_type=AgentType.CLAUDE,
                project_path="/tmp/p",
                source_file="/tmp/s.jsonl",
                started_at=datetime.now(UTC),
                last_activity=datetime.now(UTC),
            )
        )

        assert count_sessions(agent_type=AgentType.CLAUDE) == len(
            list_sessions(agent_type=AgentType.CLAUDE, limit=100)
        )


class TestStaleRunningIsNotRunning:
    """烂在 ``running`` 上的状态按最后活动时刻归位。

    监控进程没走到收尾就退出了（网页会话尤其多），metadata 里的 status 便永远停在
    ``running``。写侧收不了尾，只能在读的时候判——否则清单一屏绿色 Running，实际
    没有一场在跑。
    """

    @staticmethod
    def _write(session_id: str, idle_seconds: float) -> None:
        write_metadata(
            MonitoredSession(
                session_id=session_id,
                agent_type=AgentType.CLAUDE,
                status=SessionStatus.RUNNING,
                project_path="/tmp/p",
                source_file="/tmp/s.jsonl",
                started_at=datetime.now(UTC) - timedelta(seconds=idle_seconds),
                last_activity=datetime.now(UTC) - timedelta(seconds=idle_seconds),
            )
        )

    def test_idle_past_the_window_reads_as_finished(self, mock_home):
        self._write("wedged", STALE_RUNNING_SECONDS + 60)

        session = find_session_by_prefix("wedged", AgentType.CLAUDE)

        assert session is not None
        assert session.status is SessionStatus.COMPLETED

    def test_idle_past_the_window_drops_out_of_running_filter(self, mock_home):
        self._write("wedged", STALE_RUNNING_SECONDS + 60)

        running = list_sessions(status=SessionStatus.RUNNING, limit=100)

        assert "wedged" not in [s.session_id for s in running]

    def test_recent_activity_still_reads_as_running(self, mock_home):
        # worker 一轮任务不设时间上限，几小时没动静仍可能真在跑，不能误判成已结束。
        self._write("busy", 3600)

        session = find_session_by_prefix("busy", AgentType.CLAUDE)

        assert session is not None
        assert session.status is SessionStatus.RUNNING
        assert "busy" in [
            s.session_id for s in list_sessions(status=SessionStatus.RUNNING, limit=100)
        ]

    def test_read_metadata_keeps_the_stored_status(self, mock_home):
        """``read_metadata`` 按盘上原样返回，不归位。

        它被写路径拿去判断「这场会话存不存在」——把一场久未活动、正被续接的会话读成
        已结束，会被原样写回盘上。
        """
        self._write("wedged", STALE_RUNNING_SECONDS + 60)

        assert read_metadata("wedged", AgentType.CLAUDE).status is SessionStatus.RUNNING


class TestCleanOnlyTouchesManagedSessions:
    """清理只对 frago 自己管过的会话（有 metadata）生效。

    读取侧的放宽不能让 ``session clean`` 反过来去删同步进来的原文镜像——那些目录里
    没有 metadata，删掉目录就只剩 CLI 自己那一份了。
    """

    def test_raw_only_session_is_not_managed(self, mock_home):
        base = get_session_base_dir()
        session_dir = base / "claude" / "raw-only"
        session_dir.mkdir(parents=True)
        (session_dir / RAW_FILENAME).write_text("{}\n", encoding="utf-8")

        assert is_managed_session("raw-only", AgentType.CLAUDE) is False

    def test_metadata_backed_session_is_managed(self, mock_home):
        write_metadata(
            MonitoredSession(
                session_id="managed",
                agent_type=AgentType.CLAUDE,
                project_path="/tmp/p",
                source_file="/tmp/s.jsonl",
                started_at=datetime.now(UTC),
                last_activity=datetime.now(UTC),
            )
        )

        assert is_managed_session("managed", AgentType.CLAUDE) is True

    def test_clean_leaves_raw_only_session_alone(self, mock_home):
        base = get_session_base_dir()
        session_dir = base / "claude" / "raw-only"
        session_dir.mkdir(parents=True)
        raw = session_dir / RAW_FILENAME
        raw.write_text("{}\n", encoding="utf-8")
        old = time.time() - 90 * 86400
        os.utime(raw, (old, old))

        clean_old_sessions(max_age_days=30, agent_type=AgentType.CLAUDE)

        assert session_dir.exists()
        assert raw.exists()
