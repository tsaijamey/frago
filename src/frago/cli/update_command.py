"""update 命令 - 自我更新 frago"""

import json
import subprocess
import sys
import urllib.request
from typing import Optional

import click


PACKAGE_NAME = "frago-cli"  # PyPI 包名
TOOL_NAME = "frago"  # CLI 命令名 / entry point
PYPI_URL = f"https://pypi.org/pypi/{PACKAGE_NAME}/json"


def is_tool_installed() -> bool:
    """检查 frago 是否通过 uv tool 安装"""
    try:
        result = subprocess.run(
            ["uv", "tool", "list"],
            capture_output=True,
            text=True,
            check=True,
        )
        # uv tool list 显示的是 entry point 名称，不是包名
        return TOOL_NAME in result.stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def get_current_version() -> str:
    """获取当前版本"""
    try:
        from frago import __version__
        return __version__
    except ImportError:
        return "unknown"


def get_latest_version() -> Optional[str]:
    """从 PyPI 获取最新版本"""
    try:
        with urllib.request.urlopen(PYPI_URL, timeout=10) as response:
            data = json.loads(response.read().decode())
            return data.get("info", {}).get("version")
    except Exception:
        return None


@click.command(name="update")
@click.option(
    "--check",
    "check_only",
    is_flag=True,
    help="仅检查是否有更新，不执行更新",
)
@click.option(
    "--reinstall",
    is_flag=True,
    help="强制重新安装",
)
def update(check_only: bool, reinstall: bool):
    """
    更新 frago 到最新版本

    通过 uv tool upgrade 执行更新。需要 frago 已通过 uv tool install 安装。

    \b
    示例:
      frago update              # 更新到最新版本
      frago update --check      # 检查是否有更新
      frago update --reinstall  # 强制重新安装
    """
    current_version = get_current_version()

    click.echo(f"当前版本: {TOOL_NAME} v{current_version}")

    # 检查是否通过 uv tool 安装
    if not is_tool_installed():
        click.echo()
        click.echo(f"注意: {TOOL_NAME} 未通过 uv tool 安装", err=True)
        click.echo("如果在开发环境中，请使用 git pull 更新", err=True)
        click.echo()
        click.echo(f"安装为工具: uv tool install {PACKAGE_NAME}", err=True)
        sys.exit(1)

    if check_only:
        # 从 PyPI 检查最新版本
        click.echo("检查更新中...")
        latest = get_latest_version()
        if latest:
            if latest == current_version:
                click.echo(f"已是最新版本 (v{current_version})")
            else:
                click.echo(f"最新版本: v{latest}")
                click.echo(f"运行 'frago update' 更新")
        else:
            click.echo("无法检查更新（网络问题或包未发布）")
        return

    # 执行更新
    click.echo("更新中...")
    click.echo()

    try:
        cmd = ["uv", "tool", "upgrade", PACKAGE_NAME]
        if reinstall:
            cmd.append("--reinstall")

        # 直接执行，让输出显示给用户
        result = subprocess.run(cmd)

        if result.returncode == 0:
            click.echo()
            click.echo(f"✓ {TOOL_NAME} 更新完成")
        else:
            click.echo()
            click.echo(f"更新失败，退出码: {result.returncode}", err=True)
            sys.exit(result.returncode)

    except FileNotFoundError:
        click.echo("错误: 未找到 uv 命令", err=True)
        click.echo("请确保 uv 已安装: https://docs.astral.sh/uv/", err=True)
        sys.exit(1)
    except KeyboardInterrupt:
        click.echo("\n操作已取消")
        sys.exit(1)
