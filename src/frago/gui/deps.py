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
# 包含 WebKit 运行时依赖 + PyGObject/pycairo 编译所需的开发库
#
# 注意：PyGObject 3.51.0+ 需要 girepository-2.0
# - Ubuntu 24.04+: libgirepository-2.0-dev
# - Ubuntu 22.04 及更早: libgirepository1.0-dev
# - Debian 12 (bookworm): libgirepository1.0-dev
# - Debian 13 (trixie)+: libgirepository-2.0-dev
DISTRO_PACKAGES = {
    # Ubuntu/Debian 系
    # 注意：Ubuntu 24.04+ 需要 libgirepository-2.0-dev
    # 通过 _get_girepository_package() 动态选择正确的包
    "ubuntu": {
        "pkg_manager": "apt",
        "packages": [
            # WebKit 运行时
            "gir1.2-webkit2-4.1",
            # PyGObject/pycairo 编译依赖
            "libcairo2-dev",
            # libgirepository 包通过 _get_girepository_package() 动态添加
            "pkg-config",
            "python3-dev",
        ],
        "install_prefix": "apt install -y",
    },
    "debian": {
        "pkg_manager": "apt",
        "packages": [
            "gir1.2-webkit2-4.1",
            "libcairo2-dev",
            # libgirepository 包通过 _get_girepository_package() 动态添加
            "pkg-config",
            "python3-dev",
        ],
        "install_prefix": "apt install -y",
    },
    # Fedora/RHEL 系
    "fedora": {
        "pkg_manager": "dnf",
        "packages": [
            "webkit2gtk4.1",
            "cairo-devel",
            "gobject-introspection-devel",
            "pkg-config",
            "python3-devel",
        ],
        "install_prefix": "dnf install -y",
    },
    "rhel": {
        "pkg_manager": "dnf",
        "packages": [
            "webkit2gtk4.1",
            "cairo-devel",
            "gobject-introspection-devel",
            "pkg-config",
            "python3-devel",
        ],
        "install_prefix": "dnf install -y",
    },
    "centos": {
        "pkg_manager": "dnf",
        "packages": [
            "webkit2gtk4.1",
            "cairo-devel",
            "gobject-introspection-devel",
            "pkg-config",
            "python3-devel",
        ],
        "install_prefix": "dnf install -y",
    },
    # Arch 系
    "arch": {
        "pkg_manager": "pacman",
        "packages": [
            "webkit2gtk-4.1",
            "cairo",
            "gobject-introspection",
            "pkg-config",
            "python",
        ],
        "install_prefix": "pacman -S --noconfirm",
    },
    "manjaro": {
        "pkg_manager": "pacman",
        "packages": [
            "webkit2gtk-4.1",
            "cairo",
            "gobject-introspection",
            "pkg-config",
            "python",
        ],
        "install_prefix": "pacman -S --noconfirm",
    },
    # openSUSE
    "opensuse": {
        "pkg_manager": "zypper",
        "packages": [
            "webkit2gtk3",
            "cairo-devel",
            "gobject-introspection-devel",
            "pkg-config",
            "python3-devel",
        ],
        "install_prefix": "zypper install -y",
    },
    "opensuse-leap": {
        "pkg_manager": "zypper",
        "packages": [
            "webkit2gtk3",
            "cairo-devel",
            "gobject-introspection-devel",
            "pkg-config",
            "python3-devel",
        ],
        "install_prefix": "zypper install -y",
    },
    "opensuse-tumbleweed": {
        "pkg_manager": "zypper",
        "packages": [
            "webkit2gtk3",
            "cairo-devel",
            "gobject-introspection-devel",
            "pkg-config",
            "python3-devel",
        ],
        "install_prefix": "zypper install -y",
    },
}


def _get_girepository_package(distro_id: str, version_id: str, id_like: list[str] = None) -> str:
    """根据发行版和版本返回正确的 girepository 开发包名.

    PyGObject 3.51.0+ 需要 girepository-2.0。
    通过 pkg-config 检测系统实际可用的版本来决定。

    Args:
        distro_id: 发行版 ID（如 'ubuntu', 'debian', 'linuxmint'）
        version_id: 版本号（如 '24.04', '12', '22.2'）
        id_like: 父发行版列表（如 ['ubuntu', 'debian']）

    Returns:
        正确的包名。
    """
    # 最可靠的方法：检查 apt 仓库中哪个包可用
    if shutil.which("apt-cache"):
        # 优先检查 2.0 版本是否可用
        try:
            result = subprocess.run(
                ["apt-cache", "show", "libgirepository-2.0-dev"],
                capture_output=True,
                timeout=10,
            )
            if result.returncode == 0:
                return "libgirepository-2.0-dev"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        # 回退到 1.0 版本
        try:
            result = subprocess.run(
                ["apt-cache", "show", "libgirepository1.0-dev"],
                capture_output=True,
                timeout=10,
            )
            if result.returncode == 0:
                return "libgirepository1.0-dev"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    # 如果 apt-cache 不可用，使用默认值
    return "libgirepository1.0-dev"


def _check_apt_package_available(pkg: str) -> bool:
    """检查 apt 包是否在仓库中可用.

    Args:
        pkg: 包名。

    Returns:
        True 如果包可用。
    """
    if not shutil.which("apt-cache"):
        return False
    try:
        result = subprocess.run(
            ["apt-cache", "show", pkg],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


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
        packages = list(config["packages"])  # 复制列表，避免修改原始配置

        # 对于 apt 系发行版，动态添加正确的 girepository 包
        if config["pkg_manager"] == "apt":
            gi_pkg = _get_girepository_package(distro_id, version_id, id_like)
            packages.append(gi_pkg)

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


def _check_pkg_installed_dpkg(pkg: str) -> bool:
    """使用 dpkg 检测包是否已安装 (Debian/Ubuntu)."""
    if not shutil.which("dpkg"):
        return False
    try:
        # 使用 dpkg-query 进行精确匹配，避免 dpkg -l 的模糊匹配问题
        result = subprocess.run(
            ["dpkg-query", "-W", "-f=${Status}", pkg],
            capture_output=True,
            text=True,
            timeout=5,
        )
        # 只有状态为 "install ok installed" 才算已安装
        installed = result.returncode == 0 and "install ok installed" in result.stdout
        logger.debug(f"dpkg check {pkg}: returncode={result.returncode}, status='{result.stdout.strip()}', installed={installed}")
        return installed
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _check_pkg_installed_rpm(pkg: str) -> bool:
    """使用 rpm 检测包是否已安装 (Fedora/RHEL)."""
    if not shutil.which("rpm"):
        return False
    try:
        result = subprocess.run(
            ["rpm", "-q", pkg],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _check_pkg_installed_pacman(pkg: str) -> bool:
    """使用 pacman 检测包是否已安装 (Arch/Manjaro)."""
    if not shutil.which("pacman"):
        return False
    try:
        result = subprocess.run(
            ["pacman", "-Q", pkg],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _check_pkg_config(lib: str) -> bool:
    """使用 pkg-config 检测库是否可用."""
    if not shutil.which("pkg-config"):
        return False
    try:
        result = subprocess.run(
            ["pkg-config", "--exists", lib],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def check_all_system_deps(distro: Optional[DistroInfo]) -> tuple[bool, list[str]]:
    """检查所有必需的系统依赖.

    Args:
        distro: 发行版信息（包含已动态处理的包列表）。

    Returns:
        (全部满足, 缺失的包列表) 元组。
    """
    if not distro or not distro.supported:
        return False, []

    missing = []
    pkg_manager = None

    # 获取包管理器配置
    for distro_id in [distro.id] + distro.id_like:
        if distro_id in DISTRO_PACKAGES:
            pkg_manager = DISTRO_PACKAGES[distro_id]["pkg_manager"]
            break

    if not pkg_manager:
        return False, []

    # 使用 distro.packages（已包含动态添加的 girepository 包）
    packages = distro.packages
    logger.debug(f"Checking packages for {distro.id} {distro.version_id}: {packages}")

    # 根据包管理器检测每个包
    for pkg in packages:
        installed = False

        if pkg_manager == "apt":
            installed = _check_pkg_installed_dpkg(pkg)
        elif pkg_manager in ("dnf", "zypper"):
            installed = _check_pkg_installed_rpm(pkg)
        elif pkg_manager == "pacman":
            installed = _check_pkg_installed_pacman(pkg)

        if not installed:
            missing.append(pkg)
            logger.debug(f"Package {pkg} is missing")

    logger.debug(f"Missing packages: {missing}")
    return len(missing) == 0, missing


def check_webkit_available() -> bool:
    """检查 WebKit2GTK 系统包是否已安装.

    使用 pkg-config 检测，这是最可靠的跨发行版方法。

    Returns:
        True 如果 WebKit2GTK 系统包已安装。
    """
    for lib in ["webkit2gtk-4.1", "webkit2gtk-4.0", "webkit2gtk-3.0"]:
        if _check_pkg_config(lib):
            return True
    return False


def check_cairo_dev_available() -> bool:
    """检查 cairo 开发库是否已安装.

    PyGObject/pycairo 编译需要此库。

    Returns:
        True 如果 cairo 开发库已安装。
    """
    return _check_pkg_config("cairo")


def check_girepository_dev_available() -> bool:
    """检查 girepository 开发库是否已安装.

    PyGObject 编译需要此库。
    - PyGObject 3.51.0+ 需要 girepository-2.0
    - 旧版本需要 gobject-introspection-1.0

    Returns:
        True 如果 girepository 开发库已安装。
    """
    # 优先检查 2.0 版本（新版 PyGObject 需要）
    if _check_pkg_config("girepository-2.0"):
        return True
    # 回退检查 1.0 版本
    if _check_pkg_config("gobject-introspection-1.0"):
        return True
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


def check_gi_importable() -> bool:
    """检查 gi (PyGObject) 是否可在当前 Python 环境导入.

    Returns:
        True 如果 gi 可导入。
    """
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk

        return True
    except (ImportError, ValueError):
        return False


def install_pygobject_to_venv() -> tuple[bool, str]:
    """安装 PyGObject 到当前虚拟环境.

    优先使用 uv pip，回退到 pip。

    Returns:
        (成功与否, 消息) 元组。
    """
    print("\n系统 WebKit 依赖已安装，但当前 Python 环境缺少 PyGObject。")
    print("正在安装 PyGObject 到 frago 环境...")
    print()

    # 优先使用 uv pip（frago 通过 uv tool 安装，需指定 --python）
    if shutil.which("uv"):
        cmd = ["uv", "pip", "install", "--python", sys.executable, "--quiet", "PyGObject"]
    elif shutil.which("pip"):
        cmd = ["pip", "install", "--quiet", "PyGObject"]
    elif shutil.which("pip3"):
        cmd = ["pip3", "install", "--quiet", "PyGObject"]
    else:
        # 回退到 python -m pip
        cmd = [sys.executable, "-m", "pip", "install", "--quiet", "PyGObject"]

    print(f"执行: {' '.join(cmd)}\n")

    try:
        returncode = subprocess.call(cmd, timeout=120)

        if returncode == 0:
            return True, "PyGObject 安装成功"
        else:
            return False, f"PyGObject 安装失败 (退出码: {returncode})"

    except subprocess.TimeoutExpired:
        return False, "安装超时"
    except FileNotFoundError:
        return False, "找不到 pip 或 uv，请手动安装 PyGObject"
    except Exception as e:
        return False, f"安装出错: {e}"


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

    # 获取包管理器类型
    pkg_manager = None
    for distro_id in [distro.id] + distro.id_like:
        if distro_id in DISTRO_PACKAGES:
            pkg_manager = DISTRO_PACKAGES[distro_id]["pkg_manager"]
            break

    if not pkg_manager:
        return False, f"未找到 {distro.id} 的包配置"

    # 使用 distro.packages（已包含动态添加的 girepository 包）
    packages = distro.packages

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

    检查流程：
    1. 检测发行版
    2. 检查所有必需的系统依赖（WebKit + cairo-dev + gi-dev 等）
    3. 如果有缺失，一次性提示用户安装所有系统包
    4. 全部系统包安装完成后，检查 gi 能否导入
    5. 如果 gi 不能导入，尝试 pip 安装 PyGObject

    Returns:
        (可以启动 GUI, 消息) 元组。
    """
    # 非 Linux 系统，跳过
    if platform.system() != "Linux":
        return True, ""

    # 步骤1: 检测发行版
    distro = detect_distro()

    if not distro or not distro.supported:
        guide = get_manual_install_guide(distro)
        print(guide)
        return False, "不支持的发行版"

    # 步骤2: 检查所有系统依赖
    all_installed, missing_pkgs = check_all_system_deps(distro)

    if not all_installed:
        print(f"检测发行版: {distro.name} ({distro.id} {distro.version_id})")
        print(f"\n检测到缺少以下系统依赖:")
        for pkg in missing_pkgs:
            print(f"  - {pkg}")
        print()

        if not has_sudo():
            print("sudo 不可用，请手动安装:")
            print(f"\n    sudo {distro.install_cmd}\n")
            return False, "sudo 不可用，请手动安装依赖"

        # 提示用户安装
        if prompt_auto_install():
            success, msg = auto_install_deps(distro)
            if not success:
                print(f"\n{msg}")
                guide = get_manual_install_guide(distro)
                print(guide)
                return False, msg
            print(f"\n{msg}")
        else:
            guide = get_manual_install_guide(distro)
            print(guide)
            return False, "用户取消安装"

    # 步骤3: 检查 gi 能否导入
    if check_gi_importable():
        return True, ""

    # 步骤4: 系统包已装但 gi 不能导入，尝试 pip 安装 PyGObject
    # 先确认编译依赖已就绪
    if not check_cairo_dev_available():
        print("\n错误: cairo 开发库未正确安装，无法编译 PyGObject")
        print("请确保已安装所有系统依赖后重试")
        return False, "cairo 开发库缺失"

    if not check_girepository_dev_available():
        print("\n错误: girepository 开发库未正确安装，无法编译 PyGObject")
        print()
        print("请安装 girepository 开发库:")
        print("  Ubuntu 24.04+:  sudo apt install libgirepository-2.0-dev")
        print("  Ubuntu 22.04:   sudo apt install libgirepository1.0-dev")
        print("  Fedora/RHEL:    sudo dnf install gobject-introspection-devel")
        print()
        return False, "girepository 开发库缺失"

    success, msg = install_pygobject_to_venv()
    if success:
        print(f"\n{msg}")
        print("正在重新启动 GUI...")
        return True, "restart"
    else:
        print(f"\n{msg}")
        print("\n尝试手动安装 PyGObject:")
        print(f"    {sys.executable} -m pip install PyGObject")
        return False, msg
