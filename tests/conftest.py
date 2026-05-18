"""Global test fixtures for frago."""
import asyncio
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest


# ============================================================
# Fixture: Isolated Temp Directory Structure
# ============================================================


@pytest.fixture
def temp_frago_home(tmp_path: Path) -> Generator[Path, None, None]:
    """Create isolated ~/.frago directory structure.

    Creates:
        tmp_path/.frago/
            sessions/claude/
            recipes/atomic/, recipes/workflows/
            config.json
        tmp_path/.claude/
            projects/
            skills/
            commands/
    """
    frago_dir = tmp_path / ".frago"
    claude_dir = tmp_path / ".claude"

    # Create directory structure
    (frago_dir / "sessions" / "claude").mkdir(parents=True)
    (frago_dir / "recipes" / "atomic").mkdir(parents=True)
    (frago_dir / "recipes" / "workflows").mkdir(parents=True)
    (claude_dir / "projects").mkdir(parents=True)
    (claude_dir / "skills").mkdir(parents=True)
    (claude_dir / "commands").mkdir(parents=True)

    # Create empty config
    (frago_dir / "config.json").write_text("{}")

    yield tmp_path


@pytest.fixture
def mock_home(temp_frago_home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Mock Path.home() to return isolated temp directory."""
    monkeypatch.setattr(Path, "home", lambda: temp_frago_home)
    # Also set FRAGO_SESSION_DIR for session storage
    monkeypatch.setenv(
        "FRAGO_SESSION_DIR", str(temp_frago_home / ".frago" / "sessions")
    )
    return temp_frago_home


# ============================================================
# Fixture: Singleton Cleanup
# ============================================================


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset all singleton instances between tests.

    This runs automatically after each test to ensure clean state.
    """
    yield

    # Reset RecipeRegistry singleton
    try:
        import frago.recipes.registry as recipe_reg

        recipe_reg._registry_instance = None
    except ImportError:
        pass

    # Reset SyncService singleton
    try:
        from frago.server.services.sync_service import SyncService

        SyncService._instance = None
    except ImportError:
        pass

    # Reset StateManager singleton
    try:
        from frago.server.state import StateManager

        StateManager.reset_instance()
    except ImportError:
        pass

    # Reset RecipeService cache
    try:
        from frago.server.services.recipe_service import RecipeService

        RecipeService._cache = None
    except ImportError:
        pass


# ============================================================
# Fixture: Subprocess Mocking
# ============================================================


@pytest.fixture
def mock_subprocess():
    """Mock subprocess.run and subprocess.Popen for all tests."""
    with patch("subprocess.run") as mock_run, patch("subprocess.Popen") as mock_popen:
        # Default successful response
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        yield {"run": mock_run, "popen": mock_popen}


@pytest.fixture
def mock_frago_subprocess():
    """Mock frago-specific subprocess calls via base.py."""
    with patch("frago.server.services.base.run_subprocess") as mock_run, patch(
        "frago.server.services.base.run_subprocess_background"
    ) as mock_bg:
        mock_run.return_value = MagicMock(returncode=0, stdout="{}", stderr="")

        yield {"run_subprocess": mock_run, "run_subprocess_background": mock_bg}


# ============================================================
# Fixture: Async Event Loop
# ============================================================


@pytest.fixture
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ============================================================
# Fixture: Sample Test Data
# ============================================================


@pytest.fixture
def sample_session_data() -> dict:
    """Return sample session JSONL record data."""
    return {
        "type": "user",
        "sessionId": "test-session-123",
        "timestamp": "2025-01-15T10:00:00Z",
        "message": {"content": "Test message"},
    }


@pytest.fixture
def sample_recipe_metadata() -> dict:
    """Return sample recipe metadata.yaml content."""
    return {
        "name": "test_recipe",
        "description": "A test recipe",
        "type": "atomic",
        "runtime": "python",
        "tags": ["test"],
    }


@pytest.fixture
def sample_skill_frontmatter() -> str:
    """Return sample SKILL.md content."""
    return """---
name: test-skill
description: A test skill for unit testing
---

# Test Skill

This is a test skill.
"""
