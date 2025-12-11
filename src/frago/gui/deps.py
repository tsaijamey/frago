"""Linux GUI 依赖检测与自动安装.

提供 Linux 发行版检测、WebKit/GTK 依赖检查和自动安装功能。
"""

import logging
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class DistroInfo:
    """Linux 发行版信息."""

    id: str  # 如 'ubuntu', 'fedora', 'arch'
    name: str  # 如 'Ubuntu 24.04 LTS'
    version_id: str  # 如 '24.04'
    id_like: list[str]  # 父发行版列表
    supported: bool  # 是否支持自动安装
    packages: list[str]  # 需要安装的包列表
    install_cmd: str  # 安装命令


# 发行版包映射
DISTRO_PACKAGES = {
    # Ubuntu/Debian 系
    "ubuntu": {
        "pkg_manager": "apt",
        "packages": ["python3-gi", "python3-gi-cairo", "gir1.2-webkit2-4.1"],
        "install_prefix": "apt install -y",
    },
    "debian": {
        "pkg_manager": "apt",
        "packages": ["python3-gi", "python3-gi-cairo", "gir1.2-webkit2-4.1"],
        "install_prefix": "apt install -y",
    },
    # Fedora/RHEL 系
    "fedora": {
        "pkg_manager": "dnf",
        "packages": ["python3-gobject", "python3-gobject-base", "webkit2gtk4.1"],
        "install_prefix": "dnf install -y",
    },
    "rhel": {
        "pkg_manager": "dnf",
        "packages": ["python3-gobject", "python3-gobject-base", "webkit2gtk4.1"],
        "install_prefix": "dnf install -y",
    },
    "centos": {
        "pkg_manager": "dnf",
        "packages": ["python3-gobject", "python3-gobject-base", "webkit2gtk4.1"],
        "install_prefix": "dnf install -y",
    },
    # Arch 系
    "arch": {
        "pkg_manager": "pacman",
        "packages": ["python-gobject", "webkit2gtk-4.1"],
        "install_prefix": "pacman -S --noconfirm",
    },
    "manjaro": {
        "pkg_manager": "pacman",
        "packages": ["python-gobject", "webkit2gtk-4.1"],
        "install_prefix": "pacman -S --noconfirm",
    },
    # openSUSE
    "opensuse": {
        "pkg_manager": "zypper",
        "packages": ["python3-gobject", "webkit2gtk3"],
        "install_prefix": "zypper install -y",
    },
    "opensuse-leap": {
        "pkg_manager": "zypper",
        "packages": ["python3-gobject", "webkit2gtk3"],
        "install_prefix": "zypper install -y",
    },
    "opensuse-tumbleweed": {
        "pkg_manager": "zypper",
        "packages": ["python3-gobject", "webkit2gtk3"],
        "install_prefix": "zypper install -y",
    },
}


def detect_distro() -> Optional[DistroInfo]:
    """检测当前 Linux 发行版.

    通过解析 /etc/os-release 文件获取发行版信息。

    Returns:
        DistroInfo 对象，如果不是 Linux 或无法检测则返回 None。
    """
    if platform.system() != "Linux":
        return None

    os_release_path = Path("/etc/os-release")
    if not os_release_path.exists():
        return None

    # 解析 os-release 文件
    info: dict[str, str] = {}
    try:
        with open(os_release_path) as f:
            for line in f:
                line = line.strip()
                if "=" in line:
                    key, _, value = line.partition("=")
                    # 移除引号
                    info[key] = value.strip('"').strip("'")
    except OSError:
        return None

    distro_id = info.get("ID", "").lower()
    name = info.get("NAME", distro_id or "Unknown")
    version_id = info.get("VERSION_ID", "")
    id_like = info.get("ID_LIKE", "").split()

    # 查找匹配的发行版配置
    config = None
    matched_id = distro_id

    # 优先精确匹配
    if distro_id in DISTRO_PACKAGES:
        config = DISTRO_PACKAGES[distro_id]
    else:
        # 尝试匹配父发行版
        for parent_id in id_like:
            if parent_id in DISTRO_PACKAGES:
                config = DISTRO_PACKAGES[parent_id]
                matched_id = parent_id
                break

    if config:
        packages = config["packages"]
        install_cmd = f"{config['install_prefix']} {' '.join(packages)}"
        return DistroInfo(
            id=distro_id,
            name=name,
            version_id=version_id,
            id_like=id_like,
            supported=True,
            packages=packages,
            install_cmd=install_cmd,
        )

    # 不支持的发行版
    return DistroInfo(
        id=distro_id,
        name=name,
        version_id=version_id,
        id_like=id_like,
        supported=False,
        packages=[],
        install_cmd="",
    )


def check_webkit_available() -> bool:
    """检查 WebKit2GTK 是否可用.

    尝试导入 gi 模块并加载 WebKit2。

    Returns:
        True 如果 WebKit2GTK 可用。
    """
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        # 尝试多个 WebKit 版本
        for version in ["4.1", "4.0"]:
            try:
                gi.require_version("WebKit2", version)
                from gi.repository import WebKit2

                return True
            except (ValueError, ImportError):
                continue
        return False
    except ImportError:
        return False


def check_pywebview_available() -> bool:
    """检查 pywebview 是否可用.

    Returns:
        True 如果 pywebview 可导入。
    """
    try:
        import webview

        return True
    except ImportError:
        return False


def has_sudo() -> bool:
    """检查 sudo 是否可用.

    Returns:
        True 如果 sudo 存在。
    """
    return shutil.which("sudo") is not None


def auto_install_deps(distro: DistroInfo) -> tuple[bool, str]:
    """使用 sudo 在终端交互式安装依赖.

    Args:
        distro: 发行版信息。

    Returns:
        (成功与否, 消息) 元组。
    """
    if not distro.supported:
        return False, f"不支持自动安装: {distro.name}"

    if not has_sudo():
        return False, "sudo 不可用，无法获取管理员权限"

    # 构建安装命令
    pkg_config = None
    for distro_id in [distro.id] + distro.id_like:
        if distro_id in DISTRO_PACKAGES:
            pkg_config = DISTRO_PACKAGES[distro_id]
            break

    if not pkg_config:
        return False, f"未找到 {distro.id} 的包配置"

    pkg_manager = pkg_config["pkg_manager"]
    packages = pkg_config["packages"]

    # 构建完整命令（使用 sudo，终端交互式输入密码）
    if pkg_manager == "apt":
        cmd = ["sudo", "apt", "install", "-y"] + packages
    elif pkg_manager == "dnf":
        cmd = ["sudo", "dnf", "install", "-y"] + packages
    elif pkg_manager == "pacman":
        cmd = ["sudo", "pacman", "-S", "--noconfirm"] + packages
    elif pkg_manager == "zypper":
        cmd = ["sudo", "zypper", "install", "-y"] + packages
    else:
        return False, f"不支持的包管理器: {pkg_manager}"

    print(f"\n执行: {' '.join(cmd)}\n")

    try:
        # 使用 subprocess.call 让 sudo 直接与终端交互
        # 不捕获输出，让用户看到安装过程
        returncode = subprocess.call(cmd, timeout=300)

        if returncode == 0:
            return True, "依赖安装成功"
        else:
            return False, f"安装失败 (退出码: {returncode})"

    except subprocess.TimeoutExpired:
        return False, "安装超时（超过 5 分钟）"
    except FileNotFoundError:
        return False, "找不到包管理器"
    except KeyboardInterrupt:
        print("\n")
        return False, "用户取消安装"
    except Exception as e:
        return False, f"安装出错: {e}"


def get_manual_install_guide(distro: Optional[DistroInfo]) -> str:
    """获取手动安装指南.

    Args:
        distro: 发行版信息，可为 None。

    Returns:
        手动安装指南文本。
    """
    if distro and distro.supported:
        return f"""
请手动运行以下命令安装 GUI 依赖：

    sudo {distro.install_cmd}

安装完成后重新运行 frago gui。
"""

    if distro:
        return f"""
无法识别您的发行版 ({distro.name})，请手动安装以下依赖：

    - Python GObject 绑定 (python3-gi 或 python-gobject)
    - WebKit2GTK 库 (webkit2gtk 或类似包)
    - pywebview: pip install pywebview

常见发行版的安装命令：

    # Ubuntu/Debian
    sudo apt install -y python3-gi gir1.2-webkit2-4.1

    # Fedora/RHEL
    sudo dnf install -y python3-gobject webkit2gtk4.1

    # Arch
    sudo pacman -S python-gobject webkit2gtk-4.1

    # openSUSE
    sudo zypper install -y python3-gobject webkit2gtk3

安装完成后重新运行 frago gui。
"""

    return """
请安装 GUI 依赖后重试：

    pip install pywebview

在 Linux 上还需要安装系统包：
    - Python GObject 绑定
    - WebKit2GTK 库

详细说明请参考: https://pywebview.flowrl.com/guide/installation.html
"""


def prompt_auto_install() -> bool:
    """提示用户是否自动安装依赖.

    Returns:
        True 如果用户确认安装。
    """
    print("\n检测到缺少 GUI 系统依赖。")
    print("是否自动安装？(需要管理员权限)")
    print()

    while True:
        try:
            response = input("[Y/n] ").strip().lower()
            if response in ("", "y", "yes"):
                return True
            elif response in ("n", "no"):
                return False
            else:
                print("请输入 y 或 n")
        except (KeyboardInterrupt, EOFError):
            print()
            return False


def ensure_gui_deps() -> tuple[bool, str]:
    """确保 GUI 依赖可用.

    检查依赖，必要时提示自动安装。

    Returns:
        (可以启动 GUI, 消息) 元组。
    """
    # 非 Linux 系统，跳过
    if platform.system() != "Linux":
        return True, ""

    # 检查 WebKit 是否可用
    if check_webkit_available():
        return True, ""

    # 检测发行版
    distro = detect_distro()

    # 检查是否可以自动安装
    if not distro or not distro.supported:
        guide = get_manual_install_guide(distro)
        print(guide)
        return False, "不支持的发行版"

    if not has_sudo():
        # sudo 不可用，提供手动安装指南
        guide = get_manual_install_guide(distro)
        print(guide)
        return False, "sudo 不可用，请手动安装依赖"

    # 提示用户是否自动安装
    if prompt_auto_install():
        success, msg = auto_install_deps(distro)
        if success:
            print(f"\n{msg}")
            print("正在重新启动 GUI...")
            return True, "restart"
        else:
            print(f"\n{msg}")
            guide = get_manual_install_guide(distro)
            print(guide)
            return False, msg
    else:
        guide = get_manual_install_guide(distro)
        print(guide)
        return False, "用户取消安装"
