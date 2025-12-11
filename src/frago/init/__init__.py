"""
Frago 环境初始化模块

该模块提供 `frago init` 命令的完整功能，包括：
- 并行依赖检查（Node.js, Claude Code）
- 智能安装缺失组件
- 认证方式配置（官方登录 vs 自定义 API 端点）
- 可选 Claude Code Router 集成
- 配置持久化和状态恢复
"""

from frago.init.models import (
    Config,
    APIEndpoint,
    TemporaryState,
    InstallationStep,
    StepStatus,
    DependencyCheckResult,
)
from frago.init.exceptions import CommandError, InitErrorCode
from frago.init.checker import (
    check_node,
    check_claude_code,
    parallel_dependency_check,
    compare_versions,
)
from frago.init.installer import (
    run_external_command,
    install_node,
    install_claude_code,
    get_installation_order,
)
from frago.init.configurator import (
    load_config,
    save_config,
    config_exists,
    get_config_path,
    display_config_summary,
    prompt_auth_method,
    configure_official_auth,
    configure_custom_endpoint,
    run_auth_configuration,
    # Phase 6: 自定义端点配置
    PRESET_ENDPOINTS,
    validate_endpoint_url,
    prompt_endpoint_type,
    prompt_api_key,
    prompt_custom_endpoint_url,
    # Phase 8: 配置摘要
    format_final_summary,
    suggest_next_steps,
    display_next_steps,
    # claude.json 管理
    check_claude_json_exists,
    ensure_claude_json_for_custom_auth,
)

__all__ = [
    # 数据模型
    "Config",
    "APIEndpoint",
    "TemporaryState",
    "InstallationStep",
    "StepStatus",
    "DependencyCheckResult",
    # 异常
    "CommandError",
    "InitErrorCode",
    # 检查器
    "check_node",
    "check_claude_code",
    "parallel_dependency_check",
    "compare_versions",
    # 安装器
    "run_external_command",
    "install_node",
    "install_claude_code",
    "get_installation_order",
    # 配置器
    "load_config",
    "save_config",
    "config_exists",
    "get_config_path",
    "display_config_summary",
    "prompt_auth_method",
    "configure_official_auth",
    "configure_custom_endpoint",
    "run_auth_configuration",
    # Phase 6: 自定义端点配置
    "PRESET_ENDPOINTS",
    "validate_endpoint_url",
    "prompt_endpoint_type",
    "prompt_api_key",
    "prompt_custom_endpoint_url",
    # Phase 8: 配置摘要
    "format_final_summary",
    "suggest_next_steps",
    "display_next_steps",
    # claude.json 管理
    "check_claude_json_exists",
    "ensure_claude_json_for_custom_auth",
]
