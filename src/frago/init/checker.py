"""
依赖检查模块

提供并行检查 Node.js 和 Claude Code 安装状态的功能。
"""

import platform
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Optional

from frago.init.models import DependencyCheckResult


# 默认版本要求
DEFAULT_NODE_MIN_VERSION = "20.0.0"
DEFAULT_CLAUDE_CODE_MIN_VERSION = "1.0.0"


def compare_versions(current: str, required: str) -> int:
    """
    比较版本号

    Args:
        current: 当前版本（如 "20.10.0" 或 "v20.10.0"）
        required: 要求版本（如 "20.0.0"）

    Returns:
        > 0 如果 current > required
        = 0 如果 current == required
        < 0 如果 current < required
    """
    # 去除 v 前缀
    current = current.lstrip("v")
    required = required.lstrip("v")

    # 分割版本号
    current_parts = [int(x) for x in current.split(".")]
    required_parts = [int(x) for x in required.split(".")]

    # 补齐长度
    max_len = max(len(current_parts), len(required_parts))
    current_parts.extend([0] * (max_len - len(current_parts)))
    required_parts.extend([0] * (max_len - len(required_parts)))

    # 逐位比较
    for c, r in zip(current_parts, required_parts):
        if c > r:
            return 1
        elif c < r:
            return -1
    return 0


def check_node(min_version: str = DEFAULT_NODE_MIN_VERSION) -> DependencyCheckResult:
    """
    检查 Node.js 安装状态

    Args:
        min_version: 最低版本要求（默认 20.0.0）

    Returns:
        DependencyCheckResult 包含检查结果
    """
    result = DependencyCheckResult(
        name="node",
        required_version=min_version,
    )

    # 检查 node 命令是否存在
    node_path = shutil.which("node")
    if not node_path:
        result.installed = False
        if platform.system() == "Windows":
            result.error = (
                "Node.js 未安装\n\n"
                "推荐安装方式:\n"
                "  winget install OpenJS.NodeJS.LTS\n"
                "  或访问: https://nodejs.org/"
            )
        else:
            result.error = "Node.js 未安装"
        return result

    result.path = node_path

    try:
        # 获取版本
        version_output = subprocess.run(
            ["node", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if version_output.returncode == 0:
            version = version_output.stdout.strip().lstrip("v")
            result.installed = True
            result.version = version
            result.version_sufficient = compare_versions(version, min_version) >= 0
        else:
            result.installed = False
            result.error = f"检测版本失败: {version_output.stderr}"

    except subprocess.TimeoutExpired:
        result.installed = False
        result.error = "检测超时"
    except Exception as e:
        result.installed = False
        result.error = str(e)

    return result


def check_claude_code(
    min_version: str = DEFAULT_CLAUDE_CODE_MIN_VERSION,
) -> DependencyCheckResult:
    """
    检查 Claude Code 安装状态

    Args:
        min_version: 最低版本要求（默认 1.0.0）

    Returns:
        DependencyCheckResult 包含检查结果
    """
    result = DependencyCheckResult(
        name="claude-code",
        required_version=min_version,
    )

    # 检查 claude 命令是否存在
    claude_path = shutil.which("claude")
    if not claude_path:
        result.installed = False
        result.error = "Claude Code 未安装"
        return result

    result.path = claude_path

    try:
        # 获取版本
        version_output = subprocess.run(
            ["claude", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if version_output.returncode == 0:
            # Claude Code 版本输出格式: "2.0.53 (Claude Code)" 或 "1.0.0"
            output = version_output.stdout.strip()
            # 提取版本号（取第一个空格前的部分，去除 v 前缀）
            version = output.split()[0].lstrip("v") if output else ""

            result.installed = True
            result.version = version
            result.version_sufficient = compare_versions(version, min_version) >= 0
        else:
            result.installed = False
            result.error = f"检测版本失败: {version_output.stderr}"

    except subprocess.TimeoutExpired:
        result.installed = False
        result.error = "检测超时"
    except FileNotFoundError:
        result.installed = False
        result.error = "Claude Code 命令不存在"
    except Exception as e:
        result.installed = False
        result.error = str(e)

    return result


def parallel_dependency_check() -> Dict[str, DependencyCheckResult]:
    """
    并行检查所有依赖

    使用 ThreadPoolExecutor 并行执行 Node.js 和 Claude Code 检查，
    以减少总检查时间。

    Returns:
        Dict[str, DependencyCheckResult]: 依赖名到检查结果的映射
    """
    results: Dict[str, DependencyCheckResult] = {}

    with ThreadPoolExecutor(max_workers=2) as executor:
        # 提交检查任务
        future_to_name = {
            executor.submit(check_node): "node",
            executor.submit(check_claude_code): "claude-code",
        }

        # 收集结果
        for future in as_completed(future_to_name):
            name = future_to_name[future]
            try:
                results[name] = future.result()
            except Exception as e:
                # 捕获任何未预期的异常
                results[name] = DependencyCheckResult(
                    name=name,
                    installed=False,
                    error=f"检查失败: {str(e)}",
                    required_version=(
                        DEFAULT_NODE_MIN_VERSION
                        if name == "node"
                        else DEFAULT_CLAUDE_CODE_MIN_VERSION
                    ),
                )

    return results


def get_missing_dependencies(
    results: Dict[str, DependencyCheckResult],
) -> list[str]:
    """
    获取需要安装的依赖列表

    Args:
        results: parallel_dependency_check() 的返回结果

    Returns:
        需要安装的依赖名称列表
    """
    return [name for name, result in results.items() if result.needs_install()]


def format_check_results(results: Dict[str, DependencyCheckResult]) -> str:
    """
    格式化检查结果用于显示

    Args:
        results: parallel_dependency_check() 的返回结果

    Returns:
        格式化的字符串
    """
    lines = ["依赖检查结果:", ""]
    for name in ["node", "claude-code"]:
        if name in results:
            lines.append(f"  {results[name].display_status()}")
    return "\n".join(lines)
