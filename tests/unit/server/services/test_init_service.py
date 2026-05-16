"""Tests for frago.server.services.init_service module.

Tests initialization wizard functionality.
"""
from unittest.mock import MagicMock, patch

import pytest

from frago.server.services.init_service import InitService, _dependency_to_dict


class TestDependencyToDict:
    """Test _dependency_to_dict() helper function."""

    def test_converts_node_dependency(self):
        """Should convert node dependency result."""
        mock_result = MagicMock()
        mock_result.name = "node"
        mock_result.installed = True
        mock_result.version = "20.0.0"
        mock_result.path = "/usr/bin/node"
        mock_result.version_sufficient = True
        mock_result.required_version = "18.0.0"
        mock_result.error = None

        with patch(
            "frago.server.services.init_service.get_platform_node_install_guide",
            return_value="Install via nvm",
        ):
            result = _dependency_to_dict(mock_result)

        assert result["name"] == "node"
        assert result["installed"] is True
        assert result["version"] == "20.0.0"
        assert result["install_guide"] == "Install via nvm"

    def test_converts_claude_code_dependency(self):
        """Should convert claude-code dependency result."""
        mock_result = MagicMock()
        mock_result.name = "claude-code"
        mock_result.installed = False
        mock_result.version = None
        mock_result.path = None
        mock_result.version_sufficient = False
        mock_result.required_version = "1.0.0"
        mock_result.error = "Not found"

        result = _dependency_to_dict(mock_result)

        assert result["name"] == "claude-code"
        assert result["installed"] is False
        assert "npm install" in result["install_guide"]


class TestInitServiceGetInitStatus:
    """Test InitService.get_init_status() method."""

    def test_returns_complete_status(self):
        """Should return comprehensive status dictionary."""
        mock_config = MagicMock()
        mock_config.init_completed = True
        mock_config.resources_installed = True
        mock_config.resources_version = "1.0.0"
        mock_config.auth_method = "anthropic"
        mock_config.api_endpoint = None

        mock_node = MagicMock()
        mock_node.name = "node"
        mock_node.installed = True
        mock_node.version = "20.0.0"
        mock_node.version_sufficient = True

        mock_claude = MagicMock()
        mock_claude.name = "claude-code"
        mock_claude.installed = True
        mock_claude.version = "1.0.0"
        mock_claude.version_sufficient = True

        with (
            patch(
                "frago.server.services.init_service.load_config",
                return_value=mock_config,
            ),
            patch(
                "frago.server.services.init_service.parallel_dependency_check",
                return_value={"node": mock_node, "claude-code": mock_claude},
            ),
            patch(
                "frago.server.services.init_service.get_resources_status",
                return_value={},
            ),
        ):
            result = InitService.get_init_status()

        assert "init_completed" in result
        assert "node" in result
        assert "claude_code" in result
        assert "resources_installed" in result
        assert "auth_configured" in result


class TestInitServiceCheckDependencies:
    """Test InitService.check_dependencies() method."""

    def test_returns_all_satisfied_when_deps_met(self):
        """Should return all_satisfied=True when all dependencies met."""
        mock_node = MagicMock()
        mock_node.name = "node"
        mock_node.installed = True
        mock_node.version_sufficient = True

        mock_claude = MagicMock()
        mock_claude.name = "claude-code"
        mock_claude.installed = True
        mock_claude.version_sufficient = True

        with patch(
            "frago.server.services.init_service.parallel_dependency_check",
            return_value={"node": mock_node, "claude-code": mock_claude},
        ):
            result = InitService.check_dependencies()

        assert result["all_satisfied"] is True

    def test_returns_all_satisfied_false_when_claude_code_missing(self):
        """Should return all_satisfied=False when claude-code is not installed."""
        mock_node = MagicMock()
        mock_node.name = "node"
        mock_node.installed = True
        mock_node.version_sufficient = True

        mock_claude = MagicMock()
        mock_claude.name = "claude-code"
        mock_claude.installed = False
        mock_claude.version_sufficient = False

        with patch(
            "frago.server.services.init_service.parallel_dependency_check",
            return_value={"node": mock_node, "claude-code": mock_claude},
        ):
            result = InitService.check_dependencies()

        assert result["all_satisfied"] is False


class TestInitServiceInstallDependency:
    """Test InitService.install_dependency() method."""

    def test_rejects_unknown_dependency(self):
        """Should reject unknown dependency names."""
        result = InitService.install_dependency("unknown")

        assert result["status"] == "error"
        assert "Unknown" in result["message"]

    def test_rejects_node_on_windows(self):
        """Should reject automatic Node.js install on Windows."""
        with patch("platform.system", return_value="Windows"):
            result = InitService.install_dependency("node")

        assert result["status"] == "error"
        assert "Windows" in result["message"]

    def test_installs_node_successfully(self):
        """Should install Node.js on supported platforms."""
        with (
            patch("platform.system", return_value="Linux"),
            patch(
                "frago.server.services.init_service.install_node",
                return_value=(True, False),
            ),
        ):
            result = InitService.install_dependency("node")

        assert result["status"] == "ok"
        assert "successfully" in result["message"]

    def test_installs_claude_code_successfully(self):
        """Should install Claude Code."""
        with (
            patch("platform.system", return_value="Linux"),
            patch(
                "frago.server.services.init_service.install_claude_code",
                return_value=(True, None),
            ),
        ):
            result = InitService.install_dependency("claude-code")

        assert result["status"] == "ok"
        assert "successfully" in result["message"]

    def test_handles_installation_failure(self):
        """Should handle installation failure gracefully."""
        with (
            patch("platform.system", return_value="Linux"),
            patch(
                "frago.server.services.init_service.install_node",
                return_value=(False, False),
            ),
        ):
            result = InitService.install_dependency("node")

        assert result["status"] == "error"


class TestInitServiceInstallResources:
    """Test InitService.install_resources() method."""

    def test_successful_installation(self):
        """Should return success on successful installation."""
        mock_result = MagicMock()
        mock_result.commands = MagicMock(installed=["cmd1"], skipped=[], errors=[])
        mock_result.skills = MagicMock(installed=["skill1"], skipped=[], errors=[])
        mock_result.recipes = MagicMock(installed=["recipe1"], skipped=[], errors=[])
        mock_result.frago_version = "1.0.0"

        with (
            patch(
                "frago.server.services.init_service.install_all_resources",
                return_value=mock_result,
            ),
            patch("frago.server.services.init_service.update_config"),
        ):
            result = InitService.install_resources()

        assert result["status"] == "ok"
        assert result["total_installed"] == 3

    def test_partial_installation(self):
        """Should return partial status when some errors occur."""
        mock_result = MagicMock()
        mock_result.commands = MagicMock(
            installed=["cmd1"], skipped=[], errors=["error1"]
        )
        mock_result.skills = MagicMock(installed=[], skipped=[], errors=[])
        mock_result.recipes = MagicMock(installed=[], skipped=[], errors=[])
        mock_result.frago_version = "1.0.0"

        with (
            patch(
                "frago.server.services.init_service.install_all_resources",
                return_value=mock_result,
            ),
            patch("frago.server.services.init_service.update_config"),
        ):
            result = InitService.install_resources()

        assert result["status"] == "partial"

    def test_handles_exception(self):
        """Should handle exceptions gracefully."""
        with patch(
            "frago.server.services.init_service.install_all_resources",
            side_effect=Exception("Install failed"),
        ):
            result = InitService.install_resources()

        assert result["status"] == "error"
        assert "Install failed" in result["message"]


class TestInitServiceMarkInitComplete:
    """Test InitService.mark_init_complete() method."""

    def test_marks_complete(self):
        """Should mark initialization as complete."""
        mock_config = MagicMock()
        mock_config.init_completed = True

        with patch(
            "frago.server.services.init_service.update_config",
            return_value=mock_config,
        ):
            result = InitService.mark_init_complete()

        assert result["status"] == "ok"
        assert result["init_completed"] is True

    def test_handles_error(self):
        """Should handle errors gracefully."""
        with patch(
            "frago.server.services.init_service.update_config",
            side_effect=Exception("Config error"),
        ):
            result = InitService.mark_init_complete()

        assert result["status"] == "error"


class TestInitServiceResetInitStatus:
    """Test InitService.reset_init_status() method."""

    def test_resets_status(self):
        """Should reset initialization status."""
        with patch("frago.server.services.init_service.update_config"):
            result = InitService.reset_init_status()

        assert result["status"] == "ok"

    def test_handles_error(self):
        """Should handle errors gracefully."""
        with patch(
            "frago.server.services.init_service.update_config",
            side_effect=Exception("Config error"),
        ):
            result = InitService.reset_init_status()

        assert result["status"] == "error"
