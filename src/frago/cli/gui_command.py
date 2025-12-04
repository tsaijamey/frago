"""GUI dependency management commands."""

import platform
import shutil
import subprocess
import sys

import click


def _get_system_info() -> dict:
    """Get system information for dependency checking."""
    info = {
        "platform": platform.system(),
        "distro": None,
        "distro_id": None,
    }

    if info["platform"] == "Linux":
        try:
            with open("/etc/os-release") as f:
                for line in f:
                    if line.startswith("ID="):
                        info["distro_id"] = line.strip().split("=")[1].strip('"').lower()
                    elif line.startswith("NAME="):
                        info["distro"] = line.strip().split("=")[1].strip('"')
        except FileNotFoundError:
            pass

    return info


def _check_pywebview() -> tuple[bool, str]:
    """Check if pywebview is installed."""
    try:
        import webview
        version = getattr(webview, "__version__", "installed")
        return True, f"pywebview {version}"
    except ImportError:
        return False, "Not installed"


def _check_gtk_backend() -> tuple[bool, str]:
    """Check if GTK backend is available."""
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("WebKit2", "4.1")
        from gi.repository import Gtk, WebKit2
        return True, f"GTK {Gtk._version}, WebKit2 4.1"
    except (ImportError, ValueError) as e:
        return False, str(e)


def _check_qt_backend() -> tuple[bool, str]:
    """Check if QT backend is available."""
    try:
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtWebEngineWidgets import QWebEngineView
        return True, "PyQt5 with WebEngine"
    except ImportError:
        pass

    try:
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtWebEngineWidgets import QWebEngineView
        return True, "PyQt6 with WebEngine"
    except ImportError:
        pass

    return False, "Not installed"


def _check_windows_backend() -> tuple[bool, str]:
    """Check Windows WebView backend availability."""
    try:
        # Check if EdgeChromium (WebView2) is available
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
            0,
            winreg.KEY_READ
        )
        winreg.CloseKey(key)
        return True, "Edge WebView2"
    except (ImportError, OSError, FileNotFoundError):
        pass

    # Fallback: MSHTML is always available on Windows
    return True, "MSHTML (IE) - Edge WebView2 recommended"


def _get_install_commands(system_info: dict) -> list[str]:
    """Get installation commands based on system."""
    commands = []

    if system_info["platform"] == "Linux":
        distro = system_info["distro_id"] or ""

        if distro in ("ubuntu", "debian", "linuxmint", "pop"):
            commands = [
                "# Option 1: Use system packages (recommended)",
                "sudo apt install -y python3-gi python3-gi-cairo gir1.2-webkit2-4.1",
                "pip install pywebview",
                "",
                "# Option 2: Build from source",
                "sudo apt install -y libcairo2-dev libgirepository1.0-dev \\",
                "    libgirepository-2.0-dev gir1.2-webkit2-4.1 python3-dev",
                "pip install pywebview PyGObject",
            ]
        elif distro in ("fedora", "rhel", "centos", "rocky", "almalinux"):
            commands = [
                "sudo dnf install -y python3-gobject python3-gobject-base webkit2gtk4.1",
                "pip install pywebview",
            ]
        elif distro in ("arch", "manjaro", "endeavouros"):
            commands = [
                "sudo pacman -S python-gobject webkit2gtk-4.1",
                "pip install pywebview",
            ]
        elif distro in ("opensuse", "suse"):
            commands = [
                "sudo zypper install python3-gobject python3-gobject-cairo webkit2gtk3",
                "pip install pywebview",
            ]
        else:
            commands = [
                "# Install PyGObject and WebKit2GTK for your distribution",
                "# Common package names: python3-gi, python3-gobject, webkit2gtk",
                "pip install pywebview",
            ]

    elif system_info["platform"] == "Darwin":
        commands = [
            "pip install pywebview",
            "# macOS uses native WebKit, no additional dependencies needed",
        ]

    elif system_info["platform"] == "Windows":
        commands = [
            "# 安装 pywebview",
            "pip install pywebview",
            "",
            "# 推荐：安装 Edge WebView2 Runtime（更好的性能和兼容性）",
            "# 下载地址: https://developer.microsoft.com/en-us/microsoft-edge/webview2/",
            "",
            "# 或使用 winget 安装:",
            "winget install Microsoft.EdgeWebView2Runtime",
        ]

    else:
        commands = [
            "pip install pywebview",
        ]

    return commands


@click.command("gui-deps")
@click.option("--install", is_flag=True, help="Show installation commands")
@click.option("--check", is_flag=True, help="Check dependency status (default)")
def gui_deps(install: bool, check: bool):
    """Check or install GUI dependencies.

    Shows the status of GUI dependencies and provides installation instructions.

    \b
    Examples:
        frago gui-deps          # Check status
        frago gui-deps --install # Show install commands
    """
    system_info = _get_system_info()

    if install:
        # Show installation commands
        click.echo("GUI 依赖安装命令:")
        click.echo("")

        commands = _get_install_commands(system_info)
        for cmd in commands:
            click.echo(f"  {cmd}")

        click.echo("")
        click.echo("安装后请重新运行: frago gui-deps --check")
        return

    # Check mode (default)
    click.echo("Frago GUI 依赖检查")
    click.echo("=" * 40)
    click.echo("")

    # System info
    click.echo(f"系统: {system_info['platform']}")
    if system_info["distro"]:
        click.echo(f"发行版: {system_info['distro']}")
    click.echo("")

    # Check pywebview
    click.echo("依赖状态:")
    click.echo("-" * 40)

    pywebview_ok, pywebview_info = _check_pywebview()
    status = click.style("✓", fg="green") if pywebview_ok else click.style("✗", fg="red")
    click.echo(f"  {status} pywebview: {pywebview_info}")

    # Check backends
    if system_info["platform"] == "Linux":
        gtk_ok, gtk_info = _check_gtk_backend()
        qt_ok, qt_info = _check_qt_backend()

        status = click.style("✓", fg="green") if gtk_ok else click.style("✗", fg="red")
        click.echo(f"  {status} GTK Backend: {gtk_info}")

        status = click.style("✓", fg="green") if qt_ok else click.style("-", fg="yellow")
        click.echo(f"  {status} QT Backend: {qt_info}")

        backend_ok = gtk_ok or qt_ok

    elif system_info["platform"] == "Windows":
        win_ok, win_info = _check_windows_backend()
        status = click.style("✓", fg="green") if win_ok else click.style("✗", fg="red")
        click.echo(f"  {status} Windows Backend: {win_info}")
        backend_ok = win_ok

    elif system_info["platform"] == "Darwin":
        # macOS always has WebKit available
        click.echo(f"  {click.style('✓', fg='green')} macOS Backend: Native WebKit (PyObjC)")
        backend_ok = True

    else:
        backend_ok = True
        click.echo(f"  ? Native Backend: {system_info['platform']}")

    click.echo("")

    # Summary
    if pywebview_ok and backend_ok:
        click.echo(click.style("GUI 依赖已就绪!", fg="green", bold=True))
        click.echo("运行 'frago --gui' 启动 GUI 应用")
    else:
        click.echo(click.style("GUI 依赖缺失", fg="red", bold=True))
        click.echo("运行 'frago gui-deps --install' 查看安装命令")
