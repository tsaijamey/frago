"""End-to-end tests for session backup."""
import json
import uuid
from pathlib import Path

from frago.session import sync as sync_mod
from frago.session.sync import encode_project_path, is_main_session_file


class TestMainSessionFileDetection:
    """Test detection of main session files."""

    def test_uuid_filename_is_main(self):
        """UUID filenames should be detected as main sessions."""
        session_id = str(uuid.uuid4())
        assert is_main_session_file(f"{session_id}.jsonl") is True

    def test_agent_filename_is_not_main(self):
        """Agent sidechain files should not be main sessions."""
        assert is_main_session_file("agent-abc123.jsonl") is False

    def test_non_jsonl_is_not_main(self):
        """Non-JSONL files should not be main sessions."""
        assert is_main_session_file("session.json") is False


class TestBackupIsByteForByte:
    """A backup is only worth having if it is what the original was."""

    def _write(self, path: Path, session_id: str, count: int) -> None:
        path.write_text(
            "".join(
                json.dumps(
                    {"type": "user", "sessionId": session_id, "message": {"content": f"line {i}"}},
                    ensure_ascii=False,
                )
                + "\n"
                for i in range(count)
            ),
            encoding="utf-8",
        )

    def test_backup_matches_source_across_appends(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FRAGO_SESSION_DIR", str(tmp_path / "sessions"))
        session_id = str(uuid.uuid4())
        source = tmp_path / f"{session_id}.jsonl"

        self._write(source, session_id, 3)
        assert sync_mod.sync_session(source) == session_id
        backup = sync_mod.raw_backup_path(session_id)
        assert backup.read_bytes() == source.read_bytes()

        # Nothing new to copy: the backup already is the source.
        assert sync_mod.sync_session(source) is None

        # Appended source: only the new bytes are added, result still identical.
        with source.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "user", "sessionId": session_id}) + "\n")
        assert sync_mod.sync_session(source) == session_id
        assert backup.read_bytes() == source.read_bytes()

    def test_rewritten_source_is_copied_again_from_scratch(self, tmp_path, monkeypatch):
        """A compacted or recreated transcript must not be appended onto the old copy."""
        monkeypatch.setenv("FRAGO_SESSION_DIR", str(tmp_path / "sessions"))
        session_id = str(uuid.uuid4())
        source = tmp_path / f"{session_id}.jsonl"

        self._write(source, session_id, 5)
        sync_mod.sync_session(source)
        backup = sync_mod.raw_backup_path(session_id)

        # Same length, different content — the tail check has to catch this.
        self._write(source, session_id, 5)
        source.write_text(source.read_text(encoding="utf-8").replace("line", "LINE"), encoding="utf-8")
        assert sync_mod.sync_session(source) == session_id
        assert backup.read_bytes() == source.read_bytes()

        # Shorter source: what we hold is a version that no longer exists.
        self._write(source, session_id, 2)
        assert sync_mod.sync_session(source) == session_id
        assert backup.read_bytes() == source.read_bytes()

    def test_leftover_from_an_interrupted_copy_self_heals(self, tmp_path, monkeypatch):
        """A backup longer than its source is a half-written copy, not a longer history."""
        monkeypatch.setenv("FRAGO_SESSION_DIR", str(tmp_path / "sessions"))
        session_id = str(uuid.uuid4())
        source = tmp_path / f"{session_id}.jsonl"
        self._write(source, session_id, 4)
        sync_mod.sync_session(source)

        backup = sync_mod.raw_backup_path(session_id)
        with backup.open("a", encoding="utf-8") as fh:
            fh.write('{"junk": true}\n')

        assert sync_mod.sync_session(source) == session_id
        assert backup.read_bytes() == source.read_bytes()


class TestProjectPathEncoding:
    """Only the encode direction is used; decoding a folder name is not possible.

    Claude Code encodes both "/" and "." as "-", so a folder named
    ``-Users-me-Repos-lenovo-master-agent-lite`` could have come from either
    ``Repos/lenovo-master-agent-lite`` or ``Repos/lenovo/master/agent/lite``.
    The working directory is read from the transcript records instead.
    """

    def test_encoding_is_stable(self):
        assert encode_project_path("/home/alice/project") == "-home-alice-project"

    def test_hyphenated_directory_collides_with_a_nested_one(self):
        assert encode_project_path("/repos/master-agent") == encode_project_path("/repos/master/agent")
