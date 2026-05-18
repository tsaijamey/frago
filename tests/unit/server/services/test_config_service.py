"""Tests for frago.server.services.config_service module.

Tests user configuration management.
"""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from frago.server.services.config_service import (
    ConfigService,
    ConfigValidationError,
    UserConfig,
)


class TestUserConfig:
    """Test UserConfig dataclass."""

    def test_default_values(self):
        """Should have sensible default values."""
        config = UserConfig()
        assert config.theme == "dark"
        assert config.language == "en"
        assert config.show_system_status is True
        assert config.confirm_on_exit is True
        assert config.auto_scroll_output is True
        assert config.max_history_items == 100

    def test_default_shortcuts(self):
        """Should have default keyboard shortcuts."""
        config = UserConfig()
        assert "send" in config.shortcuts
        assert "clear" in config.shortcuts
        assert "settings" in config.shortcuts

    def test_validate_valid_config(self):
        """Should return empty list for valid config."""
        config = UserConfig()
        errors = config.validate()
        assert errors == []

    def test_validate_invalid_theme(self):
        """Should return error for invalid theme."""
        config = UserConfig(theme="invalid")
        errors = config.validate()
        assert any("theme" in e for e in errors)

    def test_validate_invalid_language(self):
        """Should return error for invalid language."""
        config = UserConfig(language="de")
        errors = config.validate()
        assert any("language" in e for e in errors)

    def test_validate_invalid_max_history(self):
        """Should return error for out-of-range max_history_items."""
        config = UserConfig(max_history_items=5)
        errors = config.validate()
        assert any("max_history_items" in e for e in errors)

        config = UserConfig(max_history_items=2000)
        errors = config.validate()
        assert any("max_history_items" in e for e in errors)

    def test_to_dict(self):
        """Should convert to dictionary."""
        config = UserConfig(theme="light")
        data = config.to_dict()
        assert data["theme"] == "light"
        assert isinstance(data, dict)


class TestConfigValidationError:
    """Test ConfigValidationError exception."""

    def test_stores_errors(self):
        """Should store error messages."""
        error = ConfigValidationError(["error1", "error2"])
        assert error.errors == ["error1", "error2"]

    def test_formats_message(self):
        """Should format error message."""
        error = ConfigValidationError(["error1", "error2"])
        assert "error1" in str(error)
        assert "error2" in str(error)


class TestConfigServiceGetConfig:
    """Test ConfigService.get_config() method."""

    def test_returns_defaults_when_no_file(self, tmp_path, monkeypatch):
        """Should return defaults when config file doesn't exist."""
        # Patch the CONFIG_FILE to a non-existent path
        config_file = tmp_path / "nonexistent" / "gui_config.json"
        monkeypatch.setattr(
            "frago.server.services.config_service.CONFIG_FILE", config_file
        )

        result = ConfigService.get_config()

        assert result["theme"] == "dark"
        assert result["language"] == "en"

    def test_loads_existing_config(self, tmp_path, monkeypatch):
        """Should load config from existing file."""
        config_dir = tmp_path / ".frago"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "gui_config.json"
        config_file.write_text(json.dumps({"theme": "light", "language": "zh"}))

        monkeypatch.setattr(
            "frago.server.services.config_service.CONFIG_FILE", config_file
        )

        result = ConfigService.get_config()

        assert result["theme"] == "light"
        assert result["language"] == "zh"

    def test_returns_defaults_on_invalid_json(self, tmp_path, monkeypatch):
        """Should return defaults when config file has invalid JSON."""
        config_dir = tmp_path / ".frago"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "gui_config.json"
        config_file.write_text("invalid json {{{")

        monkeypatch.setattr(
            "frago.server.services.config_service.CONFIG_FILE", config_file
        )

        result = ConfigService.get_config()

        # Should fall back to defaults
        assert result["theme"] == "dark"


class TestConfigServiceUpdateConfig:
    """Test ConfigService.update_config() method."""

    def test_updates_single_value(self, tmp_path, monkeypatch):
        """Should update a single config value."""
        config_dir = tmp_path / ".frago"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "gui_config.json"
        config_file.write_text(json.dumps({}))

        monkeypatch.setattr(
            "frago.server.services.config_service.CONFIG_FILE", config_file
        )
        monkeypatch.setattr(
            "frago.server.services.config_service.CONFIG_DIR", config_dir
        )

        result = ConfigService.update_config({"theme": "light"})

        assert result["theme"] == "light"
        # File should be updated
        saved = json.loads(config_file.read_text())
        assert saved["theme"] == "light"

    def test_raises_on_invalid_update(self, tmp_path, monkeypatch):
        """Should raise ConfigValidationError for invalid updates."""
        config_dir = tmp_path / ".frago"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "gui_config.json"
        config_file.write_text(json.dumps({}))

        monkeypatch.setattr(
            "frago.server.services.config_service.CONFIG_FILE", config_file
        )
        monkeypatch.setattr(
            "frago.server.services.config_service.CONFIG_DIR", config_dir
        )

        with pytest.raises(ConfigValidationError) as exc_info:
            ConfigService.update_config({"theme": "invalid_theme"})

        assert "theme" in str(exc_info.value)

    def test_ignores_unknown_keys(self, tmp_path, monkeypatch):
        """Should ignore unknown configuration keys."""
        config_dir = tmp_path / ".frago"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "gui_config.json"
        config_file.write_text(json.dumps({}))

        monkeypatch.setattr(
            "frago.server.services.config_service.CONFIG_FILE", config_file
        )
        monkeypatch.setattr(
            "frago.server.services.config_service.CONFIG_DIR", config_dir
        )

        result = ConfigService.update_config({"unknown_key": "value"})

        # Should not crash, should not include unknown key
        assert "unknown_key" not in result


class TestConfigServiceGetConfigValue:
    """Test ConfigService.get_config_value() method."""

    def test_returns_value_if_exists(self, tmp_path, monkeypatch):
        """Should return config value if it exists."""
        config_file = tmp_path / "gui_config.json"
        config_file.write_text(json.dumps({"theme": "light"}))

        monkeypatch.setattr(
            "frago.server.services.config_service.CONFIG_FILE", config_file
        )

        result = ConfigService.get_config_value("theme")

        assert result == "light"

    def test_returns_default_if_not_exists(self, tmp_path, monkeypatch):
        """Should return default when key doesn't exist."""
        config_file = tmp_path / "gui_config.json"
        config_file.write_text(json.dumps({}))

        monkeypatch.setattr(
            "frago.server.services.config_service.CONFIG_FILE", config_file
        )

        result = ConfigService.get_config_value("nonexistent", default="my_default")

        assert result == "my_default"


class TestConfigServiceGetUserLanguage:
    """Test ConfigService.get_user_language() method."""

    def test_returns_language_from_config(self, tmp_path, monkeypatch):
        """Should return language from config."""
        config_file = tmp_path / "gui_config.json"
        config_file.write_text(json.dumps({"language": "zh"}))

        monkeypatch.setattr(
            "frago.server.services.config_service.CONFIG_FILE", config_file
        )

        result = ConfigService.get_user_language()

        assert result == "zh"

    def test_defaults_to_english_on_error(self, tmp_path, monkeypatch):
        """Should default to 'en' on any error."""
        # Make config file unreadable
        config_file = tmp_path / "gui_config.json"
        monkeypatch.setattr(
            "frago.server.services.config_service.CONFIG_FILE", config_file
        )

        with patch.object(
            ConfigService, "get_config_value", side_effect=Exception("Test error")
        ):
            result = ConfigService.get_user_language()

        assert result == "en"
