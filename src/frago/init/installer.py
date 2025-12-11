"""
安装模块

提供安装 Node.js 和 Claude Code 的功能。
"""

import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from frago.init.exceptions import CommandError, InitErrorCode


# ============================================================
# Windows 兼容性辅助函数
# ============================================================


def check_npm_global_in_path() -> bool:
    """
    检查 npm 全局目录是否在 PATH 中

    Returns:
        True 如果在 PATH 中或非 Windows 平台
    """
    if platform.system() != "Windows":
        return True

    npm_global = os.path.join(os.environ.get("APPDATA", ""), "npm")
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    return any(npm_global.lower() == p.lower() for p in path_dirs)


def get_windows_path_hint() -> str:
    """
    获取 Windows PATH 修复提示

    Returns:
        包含修复建议的字符串
    """
    return (
        "\n⚠️  npm 全局目录不在 PATH 中，claude 命令可能无法直接使用\n\n"
        "请执行以下操作之一：\n\n"
        "  1. 重新打开 PowerShell 窗口（推荐）\n\n"
        "  2. 临时使用 npx 启动：\n"
        "     npx @anthropic-ai/claude-code\n\n"
        "  3. 手动添加 PATH（当前会话）：\n"
        "     $env:PATH += \";$env:APPDATA\\npm\"\n\n"
        "  4. 永久添加 PATH：\n"
        "     [Environment]::SetEnvironmentVariable(\n"
        "       'PATH', $env:PATH + ';' + $env:APPDATA + '\\npm', 'User')\n"
    )


def get_platform_node_install_guide() -> str:
    """
    根据平台返回 Node.js 安装指南

    Returns:
        平台特定的安装指南字符串
    """
    if platform.system() == "Windows":
        return (
            "请使用以下方式之一安装 Node.js:\n\n"
            "  1. winget (推荐):\n"
            "     winget install OpenJS.NodeJS.LTS\n\n"
            "  2. 官方安装程序:\n"
            "     https://nodejs.org/\n\n"
            "  3. Chocolatey:\n"
            "     choco install nodejs-lts"
        )
    return (
        "请先安装 nvm:\n"
        "  curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash\n"
        "或访问: https://github.com/nvm-sh/nvm"
    )


# ============================================================
# 命令执行辅助函数
# ============================================================


def run_external_command(
    cmd: List[str],
    timeout: int = 120,
    check: bool = True,
    cwd: Optional[str] = None,
) -> subprocess.CompletedProcess:
    """
    执行外部命令并处理错误

    Args:
        cmd: 命令和参数列表
        timeout: 超时时间（秒），默认 120 秒
        check: 是否检查返回码，默认 True
        cwd: 工作目录

    Returns:
        subprocess.CompletedProcess 结果

    Raises:
        CommandError: 命令执行失败时
    """
    # 检查命令是否存在
    if not shutil.which(cmd[0]):
        raise CommandError(
            f"命令未找到: {cmd[0]}",
            InitErrorCode.COMMAND_NOT_FOUND,
            f"请确保 {cmd[0]} 已安装并在 PATH 中",
        )

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            check=False,
        )

        if check and result.returncode != 0:
            stderr_lower = result.stderr.lower()

            # 分析错误类型
            if "permission denied" in stderr_lower or "eacces" in stderr_lower:
                raise CommandError(
                    f"权限不足: {' '.join(cmd)}",
                    InitErrorCode.PERMISSION_ERROR,
                    "尝试使用 sudo 或配置 npm prefix:\n"
                    "  npm config set prefix ~/.npm-global\n"
                    "  export PATH=~/.npm-global/bin:$PATH",
                )
            elif "timeout" in stderr_lower or "etimedout" in stderr_lower:
                raise CommandError(
                    f"网络超时: {' '.join(cmd)}",
                    InitErrorCode.NETWORK_ERROR,
                    "请检查网络连接或配置代理:\n"
                    "  export HTTP_PROXY=http://proxy:port\n"
                    "  export HTTPS_PROXY=http://proxy:port",
                )
            else:
                raise CommandError(
                    f"命令执行失败: {' '.join(cmd)}",
                    InitErrorCode.INSTALL_ERROR,
                    f"返回码: {result.returncode}\n错误输出:\n{result.stderr}",
                )

        return result

    except subprocess.TimeoutExpired as e:
        raise CommandError(
            f"命令执行超时 ({timeout}s): {' '.join(cmd)}",
            InitErrorCode.NETWORK_ERROR,
            "请检查网络连接或增加超时时间",
        ) from e


def _find_nvm() -> Optional[str]:
    """
    查找 nvm 安装位置

    Returns:
        nvm.sh 路径或 None
    """
    # 常见 nvm 安装位置
    possible_paths = [
        Path.home() / ".nvm" / "nvm.sh",
        Path("/usr/local/opt/nvm/nvm.sh"),
        Path("/opt/homebrew/opt/nvm/nvm.sh"),
    ]

    for path in possible_paths:
        if path.exists():
            return str(path)

    # 检查环境变量
    nvm_dir = os.environ.get("NVM_DIR")
    if nvm_dir:
        nvm_sh = Path(nvm_dir) / "nvm.sh"
        if nvm_sh.exists():
            return str(nvm_sh)

    return None


def install_node(version: str = "20") -> bool:
    """
    安装 Node.js（通过 nvm，仅支持 macOS/Linux）

    Args:
        version: Node.js 版本（默认 20）

    Returns:
        True 安装成功

    Raises:
        CommandError: 安装失败时或 Windows 平台不支持自动安装
    """
    # Windows 不支持通过 nvm 自动安装
    if platform.system() == "Windows":
        raise CommandError(
            "Windows 不支持自动安装 Node.js",
            InitErrorCode.COMMAND_NOT_FOUND,
            get_platform_node_install_guide(),
        )

    nvm_path = _find_nvm()

    if not nvm_path:
        raise CommandError(
            "nvm 未安装",
            InitErrorCode.COMMAND_NOT_FOUND,
            get_platform_node_install_guide(),
        )

    # 通过 bash 调用 nvm
    install_cmd = f'source "{nvm_path}" && nvm install {version} && nvm use {version}'

    try:
        result = subprocess.run(
            ["bash", "-c", install_cmd],
            capture_output=True,
            text=True,
            timeout=300,  # 安装可能需要较长时间
        )

        if result.returncode != 0:
            raise CommandError(
                f"Node.js {version} 安装失败",
                InitErrorCode.INSTALL_ERROR,
                f"错误输出:\n{result.stderr}",
            )

        return True

    except subprocess.TimeoutExpired:
        raise CommandError(
            "Node.js 安装超时",
            InitErrorCode.NETWORK_ERROR,
            "请检查网络连接",
        )


def install_claude_code() -> Tuple[bool, Optional[str]]:
    """
    安装 Claude Code（通过 npm）

    Returns:
        (True, warning) 安装成功，warning 为 PATH 警告（如有）或 None

    Raises:
        CommandError: 安装失败时
    """
    # 检查 npm 是否存在
    if not shutil.which("npm"):
        raise CommandError(
            "npm 未安装",
            InitErrorCode.COMMAND_NOT_FOUND,
            "请先安装 Node.js（包含 npm）",
        )

    # 安装 Claude Code
    cmd = ["npm", "install", "-g", "@anthropic-ai/claude-code"]

    run_external_command(cmd, timeout=300)

    # Windows 平台检查 PATH
    warning = None
    if platform.system() == "Windows" and not check_npm_global_in_path():
        warning = get_windows_path_hint()

    return True, warning


def get_installation_order(
    node_needed: bool,
    claude_code_needed: bool,
) -> List[str]:
    """
    获取安装顺序

    Node.js 必须在 Claude Code 之前安装（因为 Claude Code 依赖 npm）。

    Args:
        node_needed: 是否需要安装 Node.js
        claude_code_needed: 是否需要安装 Claude Code

    Returns:
        按依赖顺序排列的安装列表
    """
    order = []

    if node_needed:
        order.append("node")

    if claude_code_needed:
        order.append("claude-code")

    return order


def install_dependency(name: str) -> Tuple[bool, Optional[str]]:
    """
    安装指定依赖

    Args:
        name: 依赖名称 ("node" 或 "claude-code")

    Returns:
        (True, warning) 安装成功，warning 为警告信息（如有）或 None

    Raises:
        CommandError: 安装失败时
        ValueError: 未知依赖名称
    """
    if name == "node":
        install_node()
        return True, None
    elif name == "claude-code":
        return install_claude_code()
    else:
        raise ValueError(f"未知依赖: {name}")
