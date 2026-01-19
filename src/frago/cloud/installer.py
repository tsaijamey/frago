"""
Claude Code 安装器

提供 Claude Code 二进制文件的下载和安装功能:
- 自动检测官方源可达性
- 官方源不可达时降级到镜像源
- 文件完整性校验（SHA256）
- 跨平台支持
"""

import hashlib
import os
import platform
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, Tuple

import requests
from requests.exceptions import RequestException, Timeout, ConnectionError

from .client import CloudClient, get_client, NetworkError, CloudAPIError
from .config import get_api_base_url

# GCS 官方源
GCS_BASE_URL = 'https://storage.googleapis.com/claude-code-dist-86c565f3-f756-42ad-8dfa-d59b1c096819/claude-code-releases'

# 官方源超时时间（秒）
OFFICIAL_SOURCE_TIMEOUT = 10

# 下载超时时间（秒）
DOWNLOAD_TIMEOUT = 600

# 默认安装路径
DEFAULT_INSTALL_PATHS = {
    'linux': Path.home() / '.local' / 'bin',
    'darwin': Path.home() / '.local' / 'bin',
    'win32': Path.home() / 'AppData' / 'Local' / 'Programs' / 'claude-code',
}


class InstallerError(Exception):
    """安装器错误"""

    def __init__(self, message: str, code: str = 'installer_error'):
        super().__init__(message)
        self.message = message
        self.code = code


class DownloadError(InstallerError):
    """下载错误"""
    pass


class VerificationError(InstallerError):
    """校验错误"""
    pass


class InstallError(InstallerError):
    """安装错误"""
    pass


def detect_platform() -> Tuple[str, str]:
    """
    检测当前系统的平台和架构

    Returns:
        Tuple[str, str]: (platform, arch) 如 ('linux', 'x64')
    """
    system = platform.system().lower()
    machine = platform.machine().lower()

    # 平台映射
    if system == 'linux':
        plat = 'linux'
    elif system == 'darwin':
        plat = 'darwin'
    elif system == 'windows':
        plat = 'win32'
    else:
        raise InstallerError(f'不支持的操作系统: {system}', 'unsupported_os')

    # 架构映射
    if machine in ('x86_64', 'amd64'):
        arch = 'x64'
    elif machine in ('arm64', 'aarch64'):
        arch = 'arm64'
    else:
        raise InstallerError(f'不支持的架构: {machine}', 'unsupported_arch')

    return plat, arch


def get_platform_arch() -> str:
    """
    获取平台架构字符串

    Returns:
        str: 如 'linux-x64', 'darwin-arm64'
    """
    plat, arch = detect_platform()

    # 检测是否是 musl libc (Alpine Linux 等)
    if plat == 'linux':
        try:
            result = subprocess.run(
                ['ldd', '--version'],
                capture_output=True,
                text=True
            )
            if 'musl' in result.stdout.lower() or 'musl' in result.stderr.lower():
                return f'{plat}-{arch}-musl'
        except Exception:
            pass

    return f'{plat}-{arch}'


def check_official_source() -> bool:
    """
    测试官方源可达性

    Returns:
        bool: True 可达，False 不可达
    """
    try:
        response = requests.head(
            f'{GCS_BASE_URL}/latest',
            timeout=OFFICIAL_SOURCE_TIMEOUT
        )
        return response.status_code == 200
    except Exception:
        return False


def get_official_latest_version() -> Optional[str]:
    """
    从官方源获取最新版本号

    Returns:
        str: 版本号，失败返回 None
    """
    try:
        response = requests.get(
            f'{GCS_BASE_URL}/latest',
            timeout=OFFICIAL_SOURCE_TIMEOUT
        )
        response.raise_for_status()
        return response.text.strip()
    except Exception:
        return None


def get_mirror_info(platform_arch: str = None) -> Optional[dict]:
    """
    从镜像服务器获取版本信息

    Args:
        platform_arch: 平台架构，默认自动检测

    Returns:
        dict: 版本信息，包含 version, sha256, file_size, download_url
    """
    if platform_arch is None:
        platform_arch = get_platform_arch()

    try:
        client = get_client()
        response = client.get(
            '/claude-code/latest',
            params={'platform': platform_arch},
            authenticated=False
        )

        if response.get('status') == 'success':
            return response.get('data')

    except Exception:
        pass

    return None


def download_from_official(
    version: str,
    platform_arch: str,
    dest_path: Path,
    progress_callback=None
) -> bool:
    """
    从官方源下载二进制文件

    Args:
        version: 版本号
        platform_arch: 平台架构
        dest_path: 目标路径
        progress_callback: 进度回调函数 (downloaded, total)

    Returns:
        bool: 下载成功返回 True
    """
    url = f'{GCS_BASE_URL}/{version}/{platform_arch}/claude'

    try:
        response = requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT)
        response.raise_for_status()

        total_size = int(response.headers.get('content-length', 0))
        downloaded_size = 0

        with open(dest_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded_size += len(chunk)
                if progress_callback:
                    progress_callback(downloaded_size, total_size)

        return True

    except Exception:
        return False


def download_from_mirror(
    platform_arch: str,
    dest_path: Path,
    version: str = None,
    progress_callback=None
) -> Tuple[bool, Optional[dict]]:
    """
    从镜像源下载二进制文件

    Args:
        platform_arch: 平台架构
        dest_path: 目标路径
        version: 指定版本，默认最新
        progress_callback: 进度回调函数

    Returns:
        Tuple[bool, dict]: (成功与否, 版本信息)
    """
    try:
        client = get_client()

        # 获取下载信息
        params = {'platform': platform_arch}
        if version:
            params['version'] = version

        response = client.get(
            '/claude-code/latest',
            params=params,
            authenticated=False
        )

        if response.get('status') != 'success':
            return False, None

        info = response.get('data', {})

        # 构建下载 URL
        download_url = f"{get_api_base_url()}/claude-code/download/{platform_arch}"
        if version:
            download_url += f"?version={version}"

        # 下载文件
        resp = requests.get(download_url, stream=True, timeout=DOWNLOAD_TIMEOUT, allow_redirects=True)
        resp.raise_for_status()

        total_size = int(resp.headers.get('content-length', 0))
        downloaded_size = 0

        with open(dest_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded_size += len(chunk)
                if progress_callback:
                    progress_callback(downloaded_size, total_size)

        return True, info

    except Exception as e:
        return False, None


def verify_checksum(file_path: Path, expected_sha256: str) -> bool:
    """
    验证文件 SHA256 校验和

    Args:
        file_path: 文件路径
        expected_sha256: 预期的 SHA256 值

    Returns:
        bool: 校验成功返回 True
    """
    sha256_hash = hashlib.sha256()

    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256_hash.update(chunk)

    computed = sha256_hash.hexdigest()
    return computed == expected_sha256


def install_binary(source_path: Path, install_dir: Path = None) -> Path:
    """
    安装二进制文件到系统路径

    Args:
        source_path: 源文件路径
        install_dir: 安装目录，默认根据系统选择

    Returns:
        Path: 安装后的文件路径
    """
    plat, _ = detect_platform()

    if install_dir is None:
        install_dir = DEFAULT_INSTALL_PATHS.get(plat)

    if install_dir is None:
        raise InstallError(f'无法确定 {plat} 的安装目录', 'no_install_dir')

    # 确保安装目录存在
    install_dir.mkdir(parents=True, exist_ok=True)

    # 确定目标文件名
    if plat == 'win32':
        target_name = 'claude.exe'
    else:
        target_name = 'claude'

    target_path = install_dir / target_name

    # 如果已存在，先备份
    if target_path.exists():
        backup_path = target_path.with_suffix('.bak')
        target_path.rename(backup_path)

    try:
        # 复制文件
        import shutil
        shutil.copy2(source_path, target_path)

        # 设置可执行权限（非 Windows）
        if plat != 'win32':
            target_path.chmod(target_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        return target_path

    except Exception as e:
        # 恢复备份
        backup_path = target_path.with_suffix('.bak')
        if backup_path.exists():
            backup_path.rename(target_path)
        raise InstallError(f'安装失败: {e}', 'install_failed')


def check_in_path(install_dir: Path) -> bool:
    """
    检查安装目录是否在 PATH 中

    Args:
        install_dir: 安装目录

    Returns:
        bool: 在 PATH 中返回 True
    """
    path_dirs = os.environ.get('PATH', '').split(os.pathsep)
    return str(install_dir) in path_dirs


def get_path_hint(install_dir: Path) -> str:
    """
    生成添加到 PATH 的提示

    Args:
        install_dir: 安装目录

    Returns:
        str: 提示信息
    """
    plat, _ = detect_platform()

    if plat == 'linux' or plat == 'darwin':
        shell = os.environ.get('SHELL', '/bin/bash')
        if 'zsh' in shell:
            return f'echo \'export PATH="{install_dir}:$PATH"\' >> ~/.zshrc && source ~/.zshrc'
        else:
            return f'echo \'export PATH="{install_dir}:$PATH"\' >> ~/.bashrc && source ~/.bashrc'
    else:
        return f'将 "{install_dir}" 添加到系统环境变量 PATH 中'


class ClaudeCodeInstaller:
    """
    Claude Code 安装器

    使用示例:
        installer = ClaudeCodeInstaller()

        # 安装最新版本
        installer.install()

        # 安装指定版本
        installer.install(version='2.1.12')

        # 强制使用镜像源
        installer.install(mirror_only=True)
    """

    def __init__(self, verbose: bool = True):
        """
        初始化安装器

        Args:
            verbose: 是否输出详细信息
        """
        self.verbose = verbose
        self.platform_arch = get_platform_arch()

    def _log(self, message: str):
        """输出日志"""
        if self.verbose:
            print(message)

    def _progress(self, downloaded: int, total: int):
        """显示下载进度"""
        if self.verbose and total > 0:
            percent = downloaded * 100 // total
            mb_downloaded = downloaded / (1024 * 1024)
            mb_total = total / (1024 * 1024)
            print(f'\r下载进度: {percent}% ({mb_downloaded:.1f}/{mb_total:.1f} MB)', end='', flush=True)
            if downloaded >= total:
                print()

    def install(
        self,
        version: str = None,
        force: bool = False,
        mirror_only: bool = False,
        install_dir: Path = None
    ) -> Path:
        """
        安装 Claude Code

        Args:
            version: 指定版本，默认最新
            force: 强制重新安装
            mirror_only: 仅使用镜像源
            install_dir: 安装目录

        Returns:
            Path: 安装后的文件路径

        Raises:
            InstallerError: 安装失败
        """
        self._log(f'检测系统环境: {self.platform_arch}')

        # 检查是否已安装
        plat, _ = detect_platform()
        if install_dir is None:
            install_dir = DEFAULT_INSTALL_PATHS.get(plat)

        existing_path = install_dir / ('claude.exe' if plat == 'win32' else 'claude')
        if existing_path.exists() and not force:
            self._log(f'Claude Code 已安装在 {existing_path}')
            self._log('使用 --force 强制重新安装')
            return existing_path

        # 获取版本信息
        use_mirror = mirror_only
        sha256 = None
        target_version = version

        if not mirror_only:
            self._log('检测官方源可达性...')
            if check_official_source():
                self._log('官方源可达')
                if not target_version:
                    target_version = get_official_latest_version()
                    if target_version:
                        self._log(f'最新版本: {target_version}')
            else:
                self._log('官方源不可达，降级到镜像源')
                use_mirror = True

        if use_mirror or not target_version:
            self._log('获取镜像源信息...')
            mirror_info = get_mirror_info(self.platform_arch)
            if mirror_info:
                target_version = mirror_info.get('version')
                sha256 = mirror_info.get('sha256')
                self._log(f'镜像版本: {target_version}')
            else:
                raise DownloadError('无法获取版本信息', 'no_version_info')

        if not target_version:
            raise DownloadError('无法确定版本', 'no_version')

        # 创建临时文件
        with tempfile.NamedTemporaryFile(delete=False, suffix='.tmp') as tmp_file:
            tmp_path = Path(tmp_file.name)

        try:
            # 下载
            success = False

            if use_mirror:
                self._log(f'从镜像下载 Claude Code v{target_version}...')
                success, info = download_from_mirror(
                    self.platform_arch,
                    tmp_path,
                    target_version,
                    self._progress
                )
                if info and not sha256:
                    sha256 = info.get('sha256')
            else:
                self._log(f'从官方源下载 Claude Code v{target_version}...')
                success = download_from_official(
                    target_version,
                    self.platform_arch,
                    tmp_path,
                    self._progress
                )

            if not success:
                raise DownloadError('下载失败', 'download_failed')

            # 验证校验和
            if sha256:
                self._log('验证文件完整性...')
                if not verify_checksum(tmp_path, sha256):
                    raise VerificationError('文件校验失败', 'checksum_mismatch')
                self._log('校验通过')
            else:
                self._log('警告: 无法验证文件校验和')

            # 安装
            self._log(f'安装到 {install_dir}...')
            installed_path = install_binary(tmp_path, install_dir)
            self._log(f'Claude Code 安装成功!')
            self._log(f'安装位置: {installed_path}')

            # 检查 PATH
            if not check_in_path(install_dir):
                self._log('')
                self._log('注意: 安装目录不在 PATH 中')
                self._log(f'请执行: {get_path_hint(install_dir)}')

            return installed_path

        finally:
            # 清理临时文件
            if tmp_path.exists():
                tmp_path.unlink()

    def check_update(self) -> Optional[str]:
        """
        检查是否有更新

        Returns:
            str: 最新版本号，无更新返回 None
        """
        # 获取当前安装的版本
        plat, _ = detect_platform()
        install_dir = DEFAULT_INSTALL_PATHS.get(plat)
        claude_path = install_dir / ('claude.exe' if plat == 'win32' else 'claude')

        if not claude_path.exists():
            return None

        try:
            result = subprocess.run(
                [str(claude_path), '--version'],
                capture_output=True,
                text=True
            )
            current_version = result.stdout.strip().replace('Claude Code ', '')
        except Exception:
            return None

        # 获取最新版本
        if check_official_source():
            latest_version = get_official_latest_version()
        else:
            info = get_mirror_info(self.platform_arch)
            latest_version = info.get('version') if info else None

        if latest_version and latest_version != current_version:
            return latest_version

        return None
