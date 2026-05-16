"""End-to-end tests for session synchronization."""
import json
import uuid
from pathlib import Path

import pytest

from frago.session.sync import (
    decode_project_path,
    encode_project_path,
    is_main_session_file,
    parse_session_file,
)


class TestPathEncodingRoundtrip:
    """Test path encoding/decoding with real paths."""

    @pytest.mark.parametrize(
        "original_path",
        [
            "/home/alice/project",
            "/home/alice/repos/myproject",
            "/tmp/example",
        ],
        ids=["unix-home", "unix-nested", "unix-tmp"],
    )
    def test_unix_path_roundtrip(self, original_path: str):
        """Unix paths should encode and decode back to the original."""
        encoded = encode_project_path(original_path)
        decoded = decode_project_path(encoded)
        assert decoded == original_path

    @pytest.mark.parametrize(
        "original_path",
        [
            "C:/Users/alice/project",
            "D:/Development/example",
        ],
        ids=["win-c-drive", "win-d-drive"],
    )
    def test_windows_path_roundtrip(self, original_path: str):
        """Windows paths should encode and decode back to the original."""
        encoded = encode_project_path(original_path)
        decoded = decode_project_path(encoded)
        assert decoded == original_path


class TestSessionFileParsing:
    """Test parsing real session files."""

    def test_parse_valid_session_file(self, sample_session_file: tuple[Path, str]):
        """Should parse valid session file correctly."""
        file_path, expected_id = sample_session_file
        result = parse_session_file(file_path)
        assert result["session_id"] == expected_id
        assert len(result["records"]) == 3
        assert result["tool_call_count"] == 1

    def test_parse_empty_file(self, tmp_path: Path):
        """Should handle empty file gracefully."""
        empty_file = tmp_path / "empty.jsonl"
        empty_file.write_text("")
        result = parse_session_file(empty_file)
        assert result["session_id"] is None
        assert len(result["records"]) == 0

    def test_parse_file_with_invalid_json(self, tmp_path: Path):
        """Should skip invalid JSON lines."""
        file_path = tmp_path / "mixed.jsonl"
        file_path.write_text(
            '{"type": "user", "sessionId": "123"}\n'
            'not valid json\n'
            '{"type": "assistant", "sessionId": "123"}\n'
        )
        result = parse_session_file(file_path)
        assert len(result["records"]) == 2


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


class TestRealDirectoryStructure:
    """Test with realistic directory structures."""

    def test_multiple_sessions_in_project(self, claude_projects: Path):
        """Should handle multiple sessions in one project."""
        project_dir = claude_projects / "-home-user-multiproject"
        project_dir.mkdir(parents=True)
        
        sessions = []
        for i in range(3):
            session_id = str(uuid.uuid4())
            session_file = project_dir / f"{session_id}.jsonl"
            session_file.write_text(
                json.dumps({
                    "type": "user",
                    "sessionId": session_id,
                    "message": {"content": f"Session {i}"},
                }) + "\n"
            )
            sessions.append((session_file, session_id))
        
        for file_path, expected_id in sessions:
            result = parse_session_file(file_path)
            assert result["session_id"] == expected_id
