"""Unit tests for InitService auto-healing and missing-settings edge case."""

from pathlib import Path
from unittest.mock import patch

from frago.init.models import DependencyCheckResult
from frago.server.services.init_service import InitService


def test_init_status_uncompleted_when_all_settings_files_missing(tmp_path: Path):
    """When config.json, profiles.json, and gui_config.json are all missing, init_completed is False."""
    cfg_path = tmp_path / "config.json"
    prof_path = tmp_path / "profiles.json"
    gui_path = tmp_path / "gui_config.json"

    with (
        patch("frago.server.services.init_service.CONFIG_PATH", cfg_path),
        patch("frago.init.config_manager.CONFIG_PATH", cfg_path),
        patch("frago.server.services.init_service.PROFILES_PATH", prof_path),
        patch("frago.server.services.init_service.GUI_CONFIG_PATH", gui_path),
        patch(
            "frago.server.services.init_service.parallel_dependency_check",
            return_value={
                "node": DependencyCheckResult(name="node", required_version="20.0.0", optional=True),
                "claude-code": DependencyCheckResult(name="claude-code", required_version="1.0.0"),
            },
        ),
    ):
        status = InitService.get_init_status()
        assert status["init_completed"] is False
        assert not cfg_path.exists()


def test_init_status_autoheals_when_profiles_json_exists(tmp_path: Path):
    """When config.json is missing on disk but profiles.json exists, get_init_status auto-heals init_completed=True."""
    cfg_path = tmp_path / "config.json"
    prof_path = tmp_path / "profiles.json"
    gui_path = tmp_path / "gui_config.json"
    prof_path.write_text('{"profiles": []}', encoding="utf-8")

    with (
        patch("frago.server.services.init_service.CONFIG_PATH", cfg_path),
        patch("frago.init.config_manager.CONFIG_PATH", cfg_path),
        patch("frago.server.services.init_service.PROFILES_PATH", prof_path),
        patch("frago.server.services.init_service.GUI_CONFIG_PATH", gui_path),
        patch(
            "frago.server.services.init_service.parallel_dependency_check",
            return_value={
                "node": DependencyCheckResult(name="node", required_version="20.0.0", optional=True),
                "claude-code": DependencyCheckResult(name="claude-code", required_version="1.0.0"),
            },
        ),
    ):
        status = InitService.get_init_status()
        assert status["init_completed"] is True
        assert status["auth_configured"] is True
        assert cfg_path.exists()
