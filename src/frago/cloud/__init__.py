# frago Cloud Module
# CLI 云端服务客户端

__version__ = '0.1.0'

from .config import (
    get_api_base_url,
    get_access_token,
    save_tokens,
    clear_tokens,
)

from .client import (
    CloudClient,
    get_client,
    CloudAPIError,
    AuthenticationError,
    NetworkError,
)

from .installer import (
    ClaudeCodeInstaller,
    InstallerError,
    DownloadError,
    VerificationError,
    InstallError,
    detect_platform,
    get_platform_arch,
    check_official_source,
)

__all__ = [
    'get_api_base_url',
    'get_access_token',
    'save_tokens',
    'clear_tokens',
    'CloudClient',
    'get_client',
    'CloudAPIError',
    'AuthenticationError',
    'NetworkError',
    'ClaudeCodeInstaller',
    'InstallerError',
    'DownloadError',
    'VerificationError',
    'InstallError',
    'detect_platform',
    'get_platform_arch',
    'check_official_source',
]
