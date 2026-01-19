"""
frago Cloud 认证模块

实现 OAuth 2.0 Device Authorization Grant 流程:
1. login() - 获取 device_code，显示 user_code，轮询获取 token
2. logout() - 清除本地 token
3. whoami() - 获取当前用户信息
"""

import time
import webbrowser
import logging
from typing import Optional, Dict, Any

from .config import (
    get_access_token,
    get_refresh_token,
    save_tokens,
    clear_tokens,
    get_user_info,
    save_user_info,
    clear_user_info,
)
from .client import CloudClient, AuthenticationError, NetworkError, CloudAPIError


logger = logging.getLogger(__name__)


class AuthError(Exception):
    """认证错误"""
    pass


def login(client_id: str = 'frago-cli', scope: str = 'market sync',
          open_browser: bool = True, timeout: int = 600) -> Dict[str, Any]:
    """
    执行设备认证登录流程

    Args:
        client_id: 客户端标识
        scope: 授权范围
        open_browser: 是否自动打开浏览器
        timeout: 超时时间（秒）

    Returns:
        用户信息字典

    Raises:
        AuthError: 认证失败
    """
    client = CloudClient()

    # 1. 获取设备码
    try:
        result = client.post(
            '/auth/device/code',
            data={'client_id': client_id, 'scope': scope},
            authenticated=False
        )
    except NetworkError as e:
        raise AuthError(f'无法连接到服务器: {e.message}')
    except CloudAPIError as e:
        raise AuthError(f'获取设备码失败: {e.message}')

    device_code = result['device_code']
    user_code = result['user_code']
    verification_uri = result['verification_uri']
    expires_in = result['expires_in']
    interval = result.get('interval', 5)

    # 2. 显示提示信息
    print()
    print('=' * 50)
    print('请在浏览器中访问以下地址并输入代码完成登录:')
    print()
    print(f'  地址: {verification_uri}')
    print(f'  代码: {user_code}')
    print()
    print(f'代码将在 {expires_in // 60} 分钟后过期')
    print('=' * 50)
    print()

    # 3. 尝试打开浏览器
    if open_browser:
        try:
            webbrowser.open(verification_uri)
            print('已尝试自动打开浏览器...')
        except Exception:
            print('无法自动打开浏览器，请手动访问上述地址')

    # 4. 轮询获取 token
    print('等待授权中...')

    start_time = time.time()
    while time.time() - start_time < timeout:
        time.sleep(interval)

        try:
            token_result = client.post(
                '/auth/device/token',
                data={'device_code': device_code, 'client_id': client_id},
                authenticated=False
            )

            # 成功获取 token
            if 'access_token' in token_result:
                save_tokens(
                    access_token=token_result['access_token'],
                    refresh_token=token_result['refresh_token'],
                    expires_in=token_result.get('expires_in', 3600)
                )

                # 获取用户信息
                user_info = whoami(force_refresh=True)
                print()
                print(f'登录成功！欢迎, {user_info.get("username", "用户")}')
                return user_info

        except CloudAPIError as e:
            error = e.response.get('error') if e.response else None

            if error == 'authorization_pending':
                # 继续等待
                print('.', end='', flush=True)
                continue
            elif error == 'slow_down':
                # 增加轮询间隔
                interval = min(interval + 5, 30)
                continue
            elif error == 'expired_token':
                raise AuthError('设备码已过期，请重新登录')
            elif error == 'access_denied':
                raise AuthError('用户拒绝授权')
            else:
                raise AuthError(f'认证失败: {e.message}')

        except NetworkError as e:
            # 网络错误，继续重试
            logger.warning(f'网络错误: {e.message}')
            continue

    raise AuthError('登录超时，请重试')


def logout() -> bool:
    """
    退出登录，清除本地 token

    Returns:
        是否成功
    """
    clear_tokens()
    clear_user_info()
    print('已退出登录')
    return True


def whoami(force_refresh: bool = False) -> Optional[Dict[str, Any]]:
    """
    获取当前用户信息

    Args:
        force_refresh: 是否强制从服务器获取

    Returns:
        用户信息字典，未登录返回 None
    """
    # 检查是否已登录
    token = get_access_token()
    if not token:
        return None

    # 尝试使用缓存
    if not force_refresh:
        cached = get_user_info()
        if cached:
            return cached

    # 从服务器获取
    client = CloudClient()
    try:
        result = client.get('/auth/me')
        user_info = result.get('data', result)
        save_user_info(user_info)
        return user_info
    except AuthenticationError:
        # Token 无效，清除
        clear_tokens()
        clear_user_info()
        return None
    except (NetworkError, CloudAPIError) as e:
        logger.warning(f'获取用户信息失败: {e.message}')
        # 返回缓存（如果有）
        return get_user_info()


def is_logged_in() -> bool:
    """
    检查是否已登录

    Returns:
        是否已登录
    """
    return get_access_token() is not None


def get_valid_access_token() -> Optional[str]:
    """
    获取有效的 access_token

    如果 token 过期，会尝试使用 refresh_token 刷新

    Returns:
        有效的 access_token，未登录或刷新失败返回 None
    """
    token = get_access_token()
    if not token:
        return None

    # 尝试验证 token（通过调用 /auth/me）
    client = CloudClient()
    try:
        client.get('/auth/me')
        return token
    except AuthenticationError:
        # Token 无效，尝试刷新
        refresh_token = get_refresh_token()
        if not refresh_token:
            clear_tokens()
            return None

        try:
            result = client.post(
                '/auth/refresh',
                data={'refresh_token': refresh_token},
                authenticated=False
            )
            if 'access_token' in result:
                save_tokens(
                    access_token=result['access_token'],
                    refresh_token=result.get('refresh_token', refresh_token),
                    expires_in=result.get('expires_in', 3600)
                )
                return result['access_token']
        except CloudAPIError:
            pass

        # 刷新失败
        clear_tokens()
        clear_user_info()
        return None
    except NetworkError:
        # 网络错误，假设 token 有效
        return token


def require_login(func):
    """
    装饰器：要求登录

    用于装饰需要登录才能执行的函数
    """
    def wrapper(*args, **kwargs):
        if not is_logged_in():
            print('请先登录: frago login')
            return None
        return func(*args, **kwargs)
    return wrapper


def print_user_info(user_info: Optional[Dict[str, Any]] = None):
    """
    打印用户信息

    Args:
        user_info: 用户信息字典，为 None 时会自动获取
    """
    if user_info is None:
        user_info = whoami()

    if not user_info:
        print('未登录')
        print('使用 `frago login` 登录')
        return

    print()
    print(f'用户: {user_info.get("username", "未知")}')
    print(f'邮箱: {user_info.get("email", "未设置")}')
    print(f'订阅: {_format_subscription(user_info.get("subscription_type", "free_user"))}')
    print()


def _format_subscription(subscription_type: str) -> str:
    """格式化订阅类型显示"""
    mapping = {
        'free_user': '免费版',
        'vip_user': 'VIP',
        'enterprise_user': '企业版',
        'max_user': 'Max',
    }
    return mapping.get(subscription_type, subscription_type)
