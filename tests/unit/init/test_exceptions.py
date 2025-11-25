"""Unit tests for frago.init.exceptions"""

import pytest
from frago.init.exceptions import CommandError, InitErrorCode


class TestInitErrorCode:
    """Tests for InitErrorCode enum"""

    def test_all_error_codes_exist(self):
        """Test that all defined error codes exist"""
        assert InitErrorCode.SUCCESS == 0
        assert InitErrorCode.INSTALL_FAILED == 1
        assert InitErrorCode.USER_CANCELLED == 2
        assert InitErrorCode.CONFIG_ERROR == 3
        assert InitErrorCode.COMMAND_NOT_FOUND == 10
        assert InitErrorCode.VERSION_INSUFFICIENT == 11
        assert InitErrorCode.PERMISSION_ERROR == 12
        assert InitErrorCode.NETWORK_ERROR == 13
        assert InitErrorCode.INSTALL_ERROR == 14

    def test_error_code_names(self):
        """Test error code names are correct"""
        assert InitErrorCode.SUCCESS.name == "SUCCESS"
        assert InitErrorCode.INSTALL_FAILED.name == "INSTALL_FAILED"
        assert InitErrorCode.PERMISSION_ERROR.name == "PERMISSION_ERROR"


class TestCommandError:
    """Tests for CommandError exception"""

    def test_command_error_basic(self):
        """Test creating basic CommandError"""
        error = CommandError(
            "Node.js not found",
            InitErrorCode.COMMAND_NOT_FOUND,
        )

        assert error.message == "Node.js not found"
        assert error.code == InitErrorCode.COMMAND_NOT_FOUND
        assert error.details is None

    def test_command_error_with_details(self):
        """Test CommandError with details"""
        error = CommandError(
            "Installation failed",
            InitErrorCode.INSTALL_ERROR,
            details="npm install returned exit code 1",
        )

        assert error.message == "Installation failed"
        assert error.code == InitErrorCode.INSTALL_ERROR
        assert error.details == "npm install returned exit code 1"

    def test_command_error_str_without_details(self):
        """Test string representation without details"""
        error = CommandError(
            "Node.js not found",
            InitErrorCode.COMMAND_NOT_FOUND,
        )

        error_str = str(error)
        assert "[COMMAND_NOT_FOUND]" in error_str
        assert "Node.js not found" in error_str

    def test_command_error_str_with_details(self):
        """Test string representation with details"""
        error = CommandError(
            "Installation failed",
            InitErrorCode.INSTALL_ERROR,
            details="npm install returned exit code 1",
        )

        error_str = str(error)
        assert "[INSTALL_ERROR]" in error_str
        assert "Installation failed" in error_str
        assert "详细信息" in error_str
        assert "npm install returned exit code 1" in error_str

    def test_command_error_is_exception(self):
        """Test that CommandError is an Exception"""
        error = CommandError("Test error", InitErrorCode.INSTALL_ERROR)
        assert isinstance(error, Exception)

    def test_command_error_can_be_raised(self):
        """Test that CommandError can be raised and caught"""
        with pytest.raises(CommandError) as exc_info:
            raise CommandError(
                "Test error",
                InitErrorCode.PERMISSION_ERROR,
                details="Permission denied",
            )

        assert exc_info.value.message == "Test error"
        assert exc_info.value.code == InitErrorCode.PERMISSION_ERROR
        assert exc_info.value.details == "Permission denied"
