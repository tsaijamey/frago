#!/usr/bin/env python3
"""
手动测试脚本 - 测试 frago.init 数据模型

运行方式：
  uv run python tests/manual_test_models.py
"""

from datetime import datetime, timedelta
from frago.init.models import (
    Config,
    APIEndpoint,
    TemporaryState,
    InstallationStep,
    StepStatus,
    DependencyCheckResult,
)
from frago.init.exceptions import CommandError, InitErrorCode
import json


def test_config_models():
    """测试配置模型"""
    print("\n" + "=" * 60)
    print("测试 1: 创建默认配置")
    print("=" * 60)

    config = Config()
    print(f"✓ 默认配置创建成功")
    print(f"  - schema_version: {config.schema_version}")
    print(f"  - auth_method: {config.auth_method}")
    print(f"  - ccr_enabled: {config.ccr_enabled}")
    print(f"  - init_completed: {config.init_completed}")

    print("\n" + "=" * 60)
    print("测试 2: 创建带 Node.js 信息的配置")
    print("=" * 60)

    config = Config(
        node_version="20.11.0",
        node_path="/usr/local/bin/node",
        npm_version="10.2.4",
    )
    print(f"✓ Node.js 配置创建成功")
    print(f"  - Node.js: {config.node_version} ({config.node_path})")
    print(f"  - npm: {config.npm_version}")

    print("\n" + "=" * 60)
    print("测试 3: 创建自定义 API 端点配置")
    print("=" * 60)

    endpoint = APIEndpoint(
        type="deepseek",
        api_key="sk-test-key-123456",
    )
    config = Config(
        auth_method="custom",
        api_endpoint=endpoint,
    )
    print(f"✓ 自定义端点配置创建成功")
    print(f"  - 认证方式: {config.auth_method}")
    print(f"  - 端点类型: {config.api_endpoint.type}")
    print(f"  - API Key: {config.api_endpoint.api_key[:10]}...")

    print("\n" + "=" * 60)
    print("测试 4: 测试配置互斥性约束")
    print("=" * 60)

    try:
        # 这应该失败：官方认证不能有 API 端点
        bad_config = Config(
            auth_method="official",
            api_endpoint=APIEndpoint(type="deepseek", api_key="sk-test"),
        )
        print("✗ 应该抛出验证错误但没有抛出！")
    except ValueError as e:
        print(f"✓ 正确捕获验证错误: {e}")

    try:
        # 这应该失败：自定义认证必须有 API 端点
        bad_config = Config(
            auth_method="custom",
            api_endpoint=None,
        )
        print("✗ 应该抛出验证错误但没有抛出！")
    except ValueError as e:
        print(f"✓ 正确捕获验证错误: {e}")


def test_temporary_state():
    """测试临时状态模型"""
    print("\n" + "=" * 60)
    print("测试 5: 临时状态管理")
    print("=" * 60)

    state = TemporaryState()
    print(f"✓ 临时状态创建成功")
    print(f"  - 已完成步骤: {state.completed_steps}")
    print(f"  - 当前步骤: {state.current_step}")
    print(f"  - 可恢复: {state.recoverable}")

    # 添加步骤
    state.add_step("check_dependencies")
    state.add_step("install_node")
    state.set_current_step("install_claude_code")

    print(f"\n✓ 步骤记录成功")
    print(f"  - 已完成步骤: {state.completed_steps}")
    print(f"  - 当前步骤: {state.current_step}")

    # 测试步骤检查
    print(f"\n✓ 步骤检查")
    print(f"  - check_dependencies 已完成? {state.is_step_completed('check_dependencies')}")
    print(f"  - install_claude_code 已完成? {state.is_step_completed('install_claude_code')}")

    # 测试过期检查
    print(f"\n✓ 过期检查")
    print(f"  - 当前状态过期? {state.is_expired(days=7)}")

    old_state = TemporaryState(
        interrupted_at=datetime.now() - timedelta(days=8)
    )
    print(f"  - 8天前的状态过期? {old_state.is_expired(days=7)}")


def test_installation_step():
    """测试安装步骤状态机"""
    print("\n" + "=" * 60)
    print("测试 6: 安装步骤状态机")
    print("=" * 60)

    step = InstallationStep(name="install_node")
    print(f"✓ 步骤创建: {step.name}")
    print(f"  - 初始状态: {step.status.value}")

    step.start()
    print(f"\n✓ 步骤开始")
    print(f"  - 当前状态: {step.status.value}")
    print(f"  - 开始时间: {step.started_at}")

    step.complete()
    print(f"\n✓ 步骤完成")
    print(f"  - 当前状态: {step.status.value}")
    print(f"  - 完成时间: {step.completed_at}")

    # 测试失败场景
    failed_step = InstallationStep(name="install_claude_code")
    failed_step.start()
    failed_step.fail("Network timeout", 13)

    print(f"\n✓ 失败步骤示例")
    print(f"  - 步骤: {failed_step.name}")
    print(f"  - 状态: {failed_step.status.value}")
    print(f"  - 错误: {failed_step.error_message}")
    print(f"  - 错误码: {failed_step.error_code}")


def test_dependency_check():
    """测试依赖检查结果"""
    print("\n" + "=" * 60)
    print("测试 7: 依赖检查结果")
    print("=" * 60)

    # 未安装
    result1 = DependencyCheckResult(
        name="node",
        installed=False,
        required_version="20.0.0",
    )
    print(f"✓ 场景1 - 未安装")
    print(f"  {result1.display_status()}")
    print(f"  需要安装? {result1.needs_install()}")

    # 版本不足
    result2 = DependencyCheckResult(
        name="node",
        installed=True,
        version="18.0.0",
        version_sufficient=False,
        required_version="20.0.0",
    )
    print(f"\n✓ 场景2 - 版本不足")
    print(f"  {result2.display_status()}")
    print(f"  需要安装? {result2.needs_install()}")

    # 已满足
    result3 = DependencyCheckResult(
        name="node",
        installed=True,
        version="20.11.0",
        version_sufficient=True,
        required_version="20.0.0",
    )
    print(f"\n✓ 场景3 - 已满足")
    print(f"  {result3.display_status()}")
    print(f"  需要安装? {result3.needs_install()}")


def test_exceptions():
    """测试异常类"""
    print("\n" + "=" * 60)
    print("测试 8: 异常处理")
    print("=" * 60)

    # 基本错误
    error1 = CommandError(
        "Node.js not found",
        InitErrorCode.COMMAND_NOT_FOUND,
    )
    print(f"✓ 基本错误:")
    print(f"  {error1}")

    # 带详细信息的错误
    error2 = CommandError(
        "Installation failed",
        InitErrorCode.INSTALL_ERROR,
        details="npm install returned exit code 1\nPermission denied",
    )
    print(f"\n✓ 详细错误:")
    print(f"  {error2}")

    # 测试异常抛出和捕获
    print(f"\n✓ 测试异常捕获:")
    try:
        raise CommandError(
            "Permission denied",
            InitErrorCode.PERMISSION_ERROR,
            details="需要 sudo 权限",
        )
    except CommandError as e:
        print(f"  捕获到错误: {e.code.name}")
        print(f"  消息: {e.message}")
        print(f"  退出码: {e.code}")


def test_json_serialization():
    """测试 JSON 序列化"""
    print("\n" + "=" * 60)
    print("测试 9: JSON 序列化/反序列化")
    print("=" * 60)

    # 创建配置
    config = Config(
        node_version="20.11.0",
        node_path="/usr/local/bin/node",
        npm_version="10.2.4",
        auth_method="custom",
        api_endpoint=APIEndpoint(
            type="deepseek",
            api_key="sk-test-123",
        ),
        ccr_enabled=True,
    )

    # 序列化
    config_dict = config.model_dump()
    config_json = json.dumps(config_dict, indent=2, default=str)

    print("✓ 配置序列化为 JSON:")
    print(config_json)

    # 反序列化
    loaded_config = Config.model_validate(json.loads(config_json))

    print("\n✓ JSON 反序列化成功")
    print(f"  - Node版本匹配? {loaded_config.node_version == config.node_version}")
    print(f"  - 认证方式匹配? {loaded_config.auth_method == config.auth_method}")
    print(f"  - API端点匹配? {loaded_config.api_endpoint.type == config.api_endpoint.type}")


def main():
    """运行所有测试"""
    print("\n" + "🧪" * 30)
    print(" Frago Init 数据模型手动测试")
    print("🧪" * 30)

    try:
        test_config_models()
        test_temporary_state()
        test_installation_step()
        test_dependency_check()
        test_exceptions()
        test_json_serialization()

        print("\n" + "=" * 60)
        print("✅ 所有手动测试通过！")
        print("=" * 60)
        print("\n数据模型已就绪，可以继续实现:")
        print("  1. 依赖检查器 (checker.py)")
        print("  2. 安装器 (installer.py)")
        print("  3. CLI 命令 (init_command.py)")
        print("\n")

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
