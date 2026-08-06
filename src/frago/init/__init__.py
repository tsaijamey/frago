"""
Frago Environment Initialization Module

This module provides complete functionality for the `frago init` command, including:
- Parallel dependency checking (Node.js, Claude Code)
- Smart installation of missing components
- Authentication configuration (official login vs custom API endpoint)
- Optional Claude Code Router integration
- Configuration persistence and state recovery
"""

from frago.init.app_control import (
    smart_app_control_state,
    smart_app_control_warning,
)
from frago.init.checker import (
    check_claude_code,
    check_node,
    compare_versions,
    parallel_dependency_check,
)
from frago.init.config_manager import load_config, save_config
from frago.init.configurator import (
    # Phase 6: Custom endpoint configuration
    PRESET_ENDPOINTS,
    # claude.json management
    check_claude_json_exists,
    config_exists,
    configure_custom_endpoint,
    configure_official_auth,
    display_config_summary,
    display_next_steps,
    ensure_claude_json_for_custom_auth,
    # Phase 8: Configuration summary
    format_final_summary,
    get_config_path,
    prompt_api_key,
    prompt_auth_method,
    prompt_custom_endpoint_url,
    prompt_endpoint_type,
    run_auth_configuration,
    suggest_next_steps,
    validate_endpoint_url,
)
from frago.init.exceptions import CommandError, InitErrorCode
from frago.init.installer import (
    get_installation_order,
    install_claude_code,
    install_node,
    run_external_command,
)
from frago.init.models import (
    APIEndpoint,
    Config,
    DependencyCheckResult,
    InstallationStep,
    StepStatus,
    TemporaryState,
)

__all__ = [
    # Data models
    "Config",
    "APIEndpoint",
    "TemporaryState",
    "InstallationStep",
    "StepStatus",
    "DependencyCheckResult",
    # Exceptions
    "CommandError",
    "InitErrorCode",
    # Platform gates
    "smart_app_control_state",
    "smart_app_control_warning",
    # Checkers
    "check_node",
    "check_claude_code",
    "parallel_dependency_check",
    "compare_versions",
    # Installers
    "run_external_command",
    "install_node",
    "install_claude_code",
    "get_installation_order",
    # Configurators
    "load_config",
    "save_config",
    "config_exists",
    "get_config_path",
    "display_config_summary",
    "prompt_auth_method",
    "configure_official_auth",
    "configure_custom_endpoint",
    "run_auth_configuration",
    # Phase 6: Custom endpoint configuration
    "PRESET_ENDPOINTS",
    "validate_endpoint_url",
    "prompt_endpoint_type",
    "prompt_api_key",
    "prompt_custom_endpoint_url",
    # Phase 8: Configuration summary
    "format_final_summary",
    "suggest_next_steps",
    "display_next_steps",
    # claude.json management
    "check_claude_json_exists",
    "ensure_claude_json_for_custom_auth",
]
