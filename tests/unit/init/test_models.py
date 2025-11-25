"""Unit tests for frago.init.models"""

import pytest
from datetime import datetime, timedelta
from pydantic import ValidationError

from frago.init.models import (
    Config,
    APIEndpoint,
    TemporaryState,
    InstallationStep,
    StepStatus,
    DependencyCheckResult,
)


class TestAPIEndpoint:
    """Tests for APIEndpoint model"""

    def test_deepseek_endpoint_valid(self):
        """Test creating Deepseek endpoint"""
        endpoint = APIEndpoint(
            type="deepseek",
            api_key="sk-test123",
        )
        assert endpoint.type == "deepseek"
        assert endpoint.url is None
        assert endpoint.api_key == "sk-test123"

    def test_custom_endpoint_requires_url(self):
        """Test that custom endpoint requires URL"""
        with pytest.raises(ValidationError, match="Custom endpoint requires URL"):
            APIEndpoint(
                type="custom",
                api_key="sk-test123",
            )

    def test_custom_endpoint_with_url_valid(self):
        """Test custom endpoint with URL"""
        endpoint = APIEndpoint(
            type="custom",
            url="https://custom.api.com/v1",
            api_key="sk-test123",
        )
        assert endpoint.type == "custom"
        assert endpoint.url == "https://custom.api.com/v1"


class TestConfig:
    """Tests for Config model"""

    def test_default_config(self):
        """Test creating config with defaults"""
        config = Config()
        assert config.schema_version == "1.0"
        assert config.auth_method == "official"
        assert config.api_endpoint is None
        assert config.ccr_enabled is False
        assert config.init_completed is False

    def test_config_with_node_info(self):
        """Test config with Node.js information"""
        config = Config(
            node_version="20.11.0",
            node_path="/usr/local/bin/node",
            npm_version="10.2.4",
        )
        assert config.node_version == "20.11.0"
        assert config.node_path == "/usr/local/bin/node"
        assert config.npm_version == "10.2.4"

    def test_official_auth_cannot_have_endpoint(self):
        """Test that official auth cannot have api_endpoint"""
        with pytest.raises(ValidationError, match="Official auth cannot have api_endpoint"):
            Config(
                auth_method="official",
                api_endpoint=APIEndpoint(type="deepseek", api_key="sk-test"),
            )

    def test_custom_auth_requires_endpoint(self):
        """Test that custom auth requires api_endpoint"""
        with pytest.raises(ValidationError, match="Custom auth requires api_endpoint"):
            Config(
                auth_method="custom",
                api_endpoint=None,
            )

    def test_custom_auth_with_endpoint_valid(self):
        """Test valid custom auth configuration"""
        config = Config(
            auth_method="custom",
            api_endpoint=APIEndpoint(
                type="deepseek",
                api_key="sk-test123",
            ),
        )
        assert config.auth_method == "custom"
        assert config.api_endpoint is not None
        assert config.api_endpoint.type == "deepseek"


class TestTemporaryState:
    """Tests for TemporaryState model"""

    def test_default_temp_state(self):
        """Test creating temporary state with defaults"""
        state = TemporaryState()
        assert state.completed_steps == []
        assert state.current_step is None
        assert state.recoverable is True
        assert isinstance(state.interrupted_at, datetime)

    def test_add_step(self):
        """Test adding completed steps"""
        state = TemporaryState()
        state.add_step("check_dependencies")
        state.add_step("install_node")

        assert state.completed_steps == ["check_dependencies", "install_node"]

    def test_add_step_no_duplicates(self):
        """Test that add_step prevents duplicates"""
        state = TemporaryState()
        state.add_step("check_dependencies")
        state.add_step("check_dependencies")

        assert state.completed_steps == ["check_dependencies"]

    def test_set_current_step(self):
        """Test setting current step"""
        state = TemporaryState()
        state.set_current_step("install_node")

        assert state.current_step == "install_node"

    def test_is_step_completed(self):
        """Test checking if step is completed"""
        state = TemporaryState()
        state.add_step("check_dependencies")

        assert state.is_step_completed("check_dependencies")
        assert not state.is_step_completed("install_node")

    def test_is_expired_false(self):
        """Test that fresh state is not expired"""
        state = TemporaryState()
        assert not state.is_expired(days=7)

    def test_is_expired_true(self):
        """Test that old state is expired"""
        state = TemporaryState(
            interrupted_at=datetime.now() - timedelta(days=8)
        )
        assert state.is_expired(days=7)


class TestInstallationStep:
    """Tests for InstallationStep model"""

    def test_default_step(self):
        """Test creating step with defaults"""
        step = InstallationStep(name="install_node")
        assert step.name == "install_node"
        assert step.status == StepStatus.PENDING
        assert step.started_at is None
        assert step.completed_at is None

    def test_start_step(self):
        """Test starting a step"""
        step = InstallationStep(name="install_node")
        step.start()

        assert step.status == StepStatus.IN_PROGRESS
        assert isinstance(step.started_at, datetime)

    def test_complete_step(self):
        """Test completing a step"""
        step = InstallationStep(name="install_node")
        step.start()
        step.complete()

        assert step.status == StepStatus.COMPLETED
        assert isinstance(step.completed_at, datetime)

    def test_fail_step(self):
        """Test failing a step"""
        step = InstallationStep(name="install_node")
        step.start()
        step.fail("Installation failed", 1)

        assert step.status == StepStatus.FAILED
        assert step.error_message == "Installation failed"
        assert step.error_code == 1
        assert isinstance(step.completed_at, datetime)

    def test_skip_step(self):
        """Test skipping a step"""
        step = InstallationStep(name="install_node")
        step.skip()

        assert step.status == StepStatus.SKIPPED
        assert isinstance(step.completed_at, datetime)


class TestDependencyCheckResult:
    """Tests for DependencyCheckResult model"""

    def test_dependency_not_installed(self):
        """Test dependency not installed"""
        result = DependencyCheckResult(
            name="node",
            installed=False,
            required_version="20.0.0",
        )

        assert result.needs_install()
        assert result.display_status() == "❌ node: 未安装"

    def test_dependency_version_insufficient(self):
        """Test dependency with insufficient version"""
        result = DependencyCheckResult(
            name="node",
            installed=True,
            version="18.0.0",
            version_sufficient=False,
            required_version="20.0.0",
        )

        assert result.needs_install()
        assert "版本不足" in result.display_status()
        assert "18.0.0" in result.display_status()

    def test_dependency_satisfied(self):
        """Test dependency fully satisfied"""
        result = DependencyCheckResult(
            name="node",
            installed=True,
            version="20.11.0",
            version_sufficient=True,
            required_version="20.0.0",
        )

        assert not result.needs_install()
        assert "✅" in result.display_status()
        assert "20.11.0" in result.display_status()
