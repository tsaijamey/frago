"""Tests for frago.session.sync module.

Tests pure functions that handle path encoding/decoding and session file identification.
"""
import pytest

from frago.session.sync import (
    decode_project_path,
    encode_project_path,
    is_main_session_file,
)


class TestEncodeProjectPath:
    """Test encode_project_path() function."""

    @pytest.mark.parametrize(
        "path,expected",
        [
            # Unix paths
            ("/home/alice/project", "-home-alice-project"),
            ("/home/alice/.frago", "-home-alice--frago"),
            ("/Users/alice/Documents", "-Users-alice-Documents"),
            ("/", "-"),
            # Windows paths
            ("C:/Users/alice", "C--Users-alice"),
            ("D:/Projects/myproject", "D--Projects-myproject"),
            ("C:/Users/alice/.frago", "C--Users-alice--frago"),
            # Windows paths with backslashes (should be normalized)
            ("C:\\Users\\alice", "C--Users-alice"),
            ("D:\\Projects\\myproject", "D--Projects-myproject"),
        ],
        ids=[
            "unix-home",
            "unix-hidden-dir",
            "unix-users",
            "unix-root",
            "win-c-drive",
            "win-d-drive",
            "win-hidden-dir",
            "win-backslash-c",
            "win-backslash-d",
        ],
    )
    def test_encode_various_paths(self, path: str, expected: str):
        """Test encoding of various path formats."""
        assert encode_project_path(path) == expected

    def test_encode_path_with_dots(self):
        """Test that dots in paths are also converted to hyphens."""
        # .frago becomes -frago (dot replaced with hyphen)
        assert encode_project_path("/home/user/.config") == "-home-user--config"

    def test_encode_empty_path(self):
        """Test encoding empty path."""
        assert encode_project_path("") == ""


class TestDecodeProjectPath:
    """Test decode_project_path() function."""

    @pytest.mark.parametrize(
        "encoded,expected",
        [
            # Unix paths
            ("-home-alice-project", "/home/alice/project"),
            ("-Users-alice-Documents", "/Users/alice/Documents"),
            ("-", "/"),
            # Windows paths (C-- prefix indicates Windows)
            ("C--Users-alice", "C:/Users/alice"),
            ("D--Projects-myproject", "D:/Projects/myproject"),
        ],
        ids=[
            "unix-home",
            "unix-users",
            "unix-root",
            "win-c-drive",
            "win-d-drive",
        ],
    )
    def test_decode_various_paths(self, encoded: str, expected: str):
        """Test decoding of various encoded path formats."""
        assert decode_project_path(encoded) == expected

    def test_decode_empty_string(self):
        """Test decoding empty string."""
        assert decode_project_path("") == ""


class TestPathEncodingRoundTrip:
    """Test that encoding and decoding are reversible for common cases."""

    @pytest.mark.parametrize(
        "original",
        [
            "/home/alice/project",
            "/Users/alice/Documents",
            "C:/Users/alice",
            "D:/Projects/myproject",
        ],
        ids=["unix-home", "unix-users", "win-c-drive", "win-d-drive"],
    )
    def test_roundtrip(self, original: str):
        """Test that decode(encode(path)) returns original path."""
        encoded = encode_project_path(original)
        decoded = decode_project_path(encoded)
        assert decoded == original

    def test_dot_paths_not_reversible(self):
        """Note: Paths with dots are not fully reversible.

        /home/user/.config encodes to -home-user--config
        which decodes to /home/user//config (double slash)

        This is a known limitation documented here for awareness.
        """
        path = "/home/user/.config"
        encoded = encode_project_path(path)
        decoded = decode_project_path(encoded)
        # The dot becomes a hyphen, and hyphen becomes slash
        # So .config -> -config -> /config
        assert decoded == "/home/user//config"


class TestIsMainSessionFile:
    """Test is_main_session_file() function."""

    def test_valid_uuid_jsonl(self):
        """Test that valid UUID.jsonl files are identified as main sessions."""
        assert is_main_session_file("550e8400-e29b-41d4-a716-446655440000.jsonl")
        assert is_main_session_file("a1b2c3d4-e5f6-7890-abcd-ef1234567890.jsonl")

    def test_sidechain_files_rejected(self):
        """Test that agent-*.jsonl sidechain files are rejected."""
        assert not is_main_session_file("agent-abc123.jsonl")
        assert not is_main_session_file("agent-xyz789.jsonl")

    def test_non_jsonl_files_rejected(self):
        """Test that non-.jsonl files are rejected."""
        assert not is_main_session_file("550e8400-e29b-41d4-a716-446655440000.json")
        assert not is_main_session_file("550e8400-e29b-41d4-a716-446655440000.txt")
        assert not is_main_session_file("session.log")

    def test_non_uuid_jsonl_rejected(self):
        """Test that .jsonl files without valid UUID names are rejected."""
        assert not is_main_session_file("random-name.jsonl")
        assert not is_main_session_file("not-a-uuid.jsonl")
        assert not is_main_session_file("12345.jsonl")

    def test_empty_filename(self):
        """Test that empty filename is rejected."""
        assert not is_main_session_file("")

    def test_just_extension(self):
        """Test that just extension is rejected."""
        assert not is_main_session_file(".jsonl")
