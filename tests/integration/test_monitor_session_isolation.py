"""Test that SessionMonitor does not mix records from different JSONL files.

Reproduces the bug where frago agent's monitor, after matching session A,
would also ingest records from session B's JSONL file (e.g. an interactive
Claude Code session running in parallel), because _on_new_records did not
filter by file_path after the initial match.
"""
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from frago.session.monitor import SessionMonitor
from frago.session.parser import ParsedRecord


def _make_record(session_id: str, text: str, ts: datetime) -> ParsedRecord:
    """Create a minimal ParsedRecord for testing."""
    return ParsedRecord(
        uuid=str(uuid.uuid4()),
        session_id=session_id,
        timestamp=ts,
        record_type="assistant",
        role="assistant",
        content_text=text,
    )


class TestSessionIsolation:
    """Verify that monitor only processes records from the matched file."""

    def test_records_from_other_file_are_ignored_after_match(self, tmp_path: Path):
        """After matching session A from file_a.jsonl, records arriving
        from file_b.jsonl must be silently discarded."""
        now = datetime.now()
        session_a = str(uuid.uuid4())
        session_b = str(uuid.uuid4())

        # Create watch directory
        watch_dir = tmp_path / "watch"
        watch_dir.mkdir()

        file_a = str(watch_dir / f"{session_a}.jsonl")
        file_b = str(watch_dir / f"{session_b}.jsonl")

        # Create monitor with persist=False to avoid writing to ~/.frago
        monitor = SessionMonitor(
            project_path="/tmp/test-project",
            start_time=now,
            persist=False,
            quiet=True,
        )

        # Step 1: Feed a record from file_a — should match and create session
        record_a1 = _make_record(session_a, "hello from A", now)
        monitor._on_new_records(file_a, [record_a1])

        assert monitor._session is not None
        assert monitor._session.session_id == session_a
        assert monitor._matched_file == file_a
        assert monitor._step_id == 1

        # Step 2: Feed a record from file_b — should be IGNORED
        record_b1 = _make_record(session_b, "hello from B", now)
        monitor._on_new_records(file_b, [record_b1])

        # step_id should still be 1 (record from B was not processed)
        assert monitor._step_id == 1

        # Step 3: Feed another record from file_a — should be processed
        record_a2 = _make_record(session_a, "second from A", now)
        monitor._on_new_records(file_a, [record_a2])

        assert monitor._step_id == 2

    def test_records_from_matched_file_continue_to_be_processed(self, tmp_path: Path):
        """Ensure the fix doesn't break normal single-file operation."""
        now = datetime.now()
        session_id = str(uuid.uuid4())

        watch_dir = tmp_path / "watch"
        watch_dir.mkdir()
        file_path = str(watch_dir / f"{session_id}.jsonl")

        monitor = SessionMonitor(
            project_path="/tmp/test-project",
            start_time=now,
            persist=False,
            quiet=True,
        )

        records = [
            _make_record(session_id, f"message {i}", now)
            for i in range(5)
        ]

        # Feed all records from same file
        for r in records:
            monitor._on_new_records(file_path, [r])

        assert monitor._step_id == 5
        assert monitor._session.session_id == session_id

    def test_time_window_rejection_still_works(self, tmp_path: Path):
        """Records outside the time window should not match, even before
        any session is associated."""
        from frago.session.monitor import SESSION_MATCH_WINDOW_SECONDS

        now = datetime.now()
        session_id = str(uuid.uuid4())

        watch_dir = tmp_path / "watch"
        watch_dir.mkdir()
        file_path = str(watch_dir / f"{session_id}.jsonl")

        monitor = SessionMonitor(
            project_path="/tmp/test-project",
            start_time=now,
            persist=False,
            quiet=True,
        )

        # Create record with timestamp far outside the window
        from datetime import timedelta
        old_ts = now - timedelta(seconds=SESSION_MATCH_WINDOW_SECONDS + 60)
        old_record = _make_record(session_id, "old message", old_ts)

        monitor._on_new_records(file_path, [old_record])

        # Should not have matched
        assert monitor._session is None
        assert monitor._step_id == 0


class TestConcurrentFileWrites:
    """End-to-end test with actual file writes and watchdog events."""

    def test_watchdog_concurrent_sessions(self, tmp_path: Path):
        """Simulate two JSONL files being written concurrently in the same
        watch directory. The monitor should only pick up records from the
        first-matched file."""
        now = datetime.now()
        session_a = str(uuid.uuid4())
        session_b = str(uuid.uuid4())

        # Set up a fake Claude projects dir
        watch_dir = tmp_path / ".claude" / "projects" / "-tmp-test-project"
        watch_dir.mkdir(parents=True)

        file_a = watch_dir / f"{session_a}.jsonl"
        file_b = watch_dir / f"{session_b}.jsonl"

        now_iso = now.astimezone(timezone.utc).isoformat()

        # Write initial records to both files
        with open(file_a, "w") as f:
            f.write(json.dumps({
                "type": "user",
                "uuid": str(uuid.uuid4()),
                "sessionId": session_a,
                "timestamp": now_iso,
                "message": {"role": "user", "content": "agent task"},
            }) + "\n")

        with open(file_b, "w") as f:
            f.write(json.dumps({
                "type": "user",
                "uuid": str(uuid.uuid4()),
                "sessionId": session_b,
                "timestamp": now_iso,
                "message": {"role": "user", "content": "interactive chat"},
            }) + "\n")

        # Patch get_claude_dir and encode_project_path to use our temp dir
        with patch("frago.session.monitor.get_claude_dir", return_value=tmp_path / ".claude" / "projects"), \
             patch("frago.session.monitor.encode_project_path", return_value="-tmp-test-project"):

            monitor = SessionMonitor(
                project_path="/tmp/test-project",
                start_time=now,
                persist=False,
                quiet=True,
            )
            monitor.start()

            try:
                # Give watchdog time to pick up initial file
                time.sleep(1.5)

                # Append more records to file_a (the agent session)
                with open(file_a, "a") as f:
                    f.write(json.dumps({
                        "type": "assistant",
                        "uuid": str(uuid.uuid4()),
                        "sessionId": session_a,
                        "timestamp": now_iso,
                        "message": {"role": "assistant", "content": [
                            {"type": "text", "text": "I'll help with that."}
                        ]},
                    }) + "\n")

                time.sleep(0.5)

                # Append records to file_b (the interactive session)
                with open(file_b, "a") as f:
                    f.write(json.dumps({
                        "type": "assistant",
                        "uuid": str(uuid.uuid4()),
                        "sessionId": session_b,
                        "timestamp": now_iso,
                        "message": {"role": "assistant", "content": [
                            {"type": "text", "text": "This should NOT appear."}
                        ]},
                    }) + "\n")

                time.sleep(0.5)

                # Verify: monitor should have matched exactly one session
                if monitor._session:
                    matched_id = monitor._session.session_id
                    # Whichever file watchdog picked up first is fine,
                    # but the matched file must be consistent
                    if matched_id == session_a:
                        assert monitor._matched_file == str(file_a)
                    else:
                        assert monitor._matched_file == str(file_b)

                    # The other session's records must NOT have been processed
                    # (step_id should be low, not accumulating from both files)
                    # With the fix, max 2 records from one file
                    assert monitor._step_id <= 2, (
                        f"step_id={monitor._step_id}, expected <=2. "
                        "Records from the other session file leaked in!"
                    )

            finally:
                monitor.stop()
