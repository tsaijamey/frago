"""
frago Cloud HTTP 客户端

提供与云端 API 通信的基础设施:
- 自动添加认证 Header
- 统一错误处理
- Token 自动刷新
"""

import logging
from typing import Optional, Any
from urllib.parse import urljoin

import requests
from requests.exceptions import RequestException, Timeout, ConnectionError

from .config import (
    get_api_base_url,
    get_access_token,
    get_refresh_token,
    save_tokens,
    clear_tokens,
)


logger = logging.getLogger(__name__)


class CloudAPIError(Exception):
    """云端 API 错误"""

    def __init__(self, message: str, status_code: Optional[int] = None,
                 error_code: Optional[str] = None, response: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.response = response


class AuthenticationError(CloudAPIError):
    """认证错误"""
    pass


class NetworkError(CloudAPIError):
    """网络错误"""
    pass


class ServerError(CloudAPIError):
    """服务器错误"""
    pass


class CloudClient:
    """
    frago Cloud HTTP 客户端

    使用方法:
        client = CloudClient()

        # 无需认证的请求
        recipes = client.get('/recipes/')

        # 需要认证的请求
        client.post('/recipes/', data={'name': 'my-recipe', ...})
    """

    DEFAULT_TIMEOUT = 30  # 默认超时时间（秒）

    def __init__(self, base_url: Optional[str] = None, timeout: int = DEFAULT_TIMEOUT):
        """
        初始化客户端

        Args:
            base_url: API 基础地址，默认从配置获取
            timeout: 请求超时时间（秒）
        """
        self.base_url = base_url or get_api_base_url()
        self.timeout = timeout
        self._session = requests.Session()

    def _get_url(self, endpoint: str) -> str:
        """构建完整 URL"""
        if endpoint.startswith('http'):
            return endpoint
        return urljoin(self.base_url + '/', endpoint.lstrip('/'))

    def _get_headers(self, authenticated: bool = True) -> dict:
        """获取请求头"""
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'frago-cli/0.1.0',
        }

        if authenticated:
            token = get_access_token()
            if token:
                headers['Authorization'] = f'Bearer {token}'

        return headers

    def _handle_response(self, response: requests.Response) -> Any:
        """处理响应"""
        try:
            data = response.json()
        except ValueError:
            data = {'raw': response.text}

        if response.status_code >= 500:
            raise ServerError(
                message=data.get('message', '服务器内部错误'),
                status_code=response.status_code,
                response=data
            )

        if response.status_code == 401:
            raise AuthenticationError(
                message=data.get('message', '认证失败'),
                status_code=response.status_code,
                error_code=data.get('error'),
                response=data
            )

        if response.status_code == 403:
            raise AuthenticationError(
                message=data.get('message', '权限不足'),
                status_code=response.status_code,
                response=data
            )

        if response.status_code >= 400:
            raise CloudAPIError(
                message=data.get('message', f'请求失败: {response.status_code}'),
                status_code=response.status_code,
                error_code=data.get('error'),
                response=data
            )

        return data

    def _refresh_token(self) -> bool:
        """
        刷新 Access Token

        Returns:
            是否刷新成功
        """
        refresh_token = get_refresh_token()
        if not refresh_token:
            return False

        try:
            response = self._session.post(
                self._get_url('/auth/refresh'),
                json={'refresh_token': refresh_token},
                headers=self._get_headers(authenticated=False),
                timeout=self.timeout
            )

            if response.status_code == 200:
                data = response.json()
                save_tokens(
                    access_token=data['access_token'],
                    refresh_token=data.get('refresh_token', refresh_token),
                    expires_in=data.get('expires_in', 3600)
                )
                return True

        except Exception as e:
            logger.debug(f'Token 刷新失败: {e}')

        return False

    def _request(self, method: str, endpoint: str,
                 authenticated: bool = True,
                 retry_on_auth_error: bool = True,
                 **kwargs) -> Any:
        """
        发送 HTTP 请求

        Args:
            method: HTTP 方法
            endpoint: API 端点
            authenticated: 是否需要认证
            retry_on_auth_error: 认证失败时是否尝试刷新 Token
            **kwargs: 传递给 requests 的其他参数

        Returns:
            响应数据
        """
        url = self._get_url(endpoint)
        headers = self._get_headers(authenticated)

        # 合并自定义 headers
        if 'headers' in kwargs:
            headers.update(kwargs.pop('headers'))

        try:
            response = self._session.request(
                method=method,
                url=url,
                headers=headers,
                timeout=kwargs.pop('timeout', self.timeout),
                **kwargs
            )

            return self._handle_response(response)

        except AuthenticationError as e:
            # 尝试刷新 Token 并重试
            if retry_on_auth_error and e.status_code == 401 and self._refresh_token():
                return self._request(
                    method, endpoint,
                    authenticated=authenticated,
                    retry_on_auth_error=False,
                    **kwargs
                )
            raise

        except Timeout:
            raise NetworkError(
                message='请求超时，请检查网络连接',
                error_code='timeout'
            )

        except ConnectionError:
            raise NetworkError(
                message='无法连接到服务器，请检查网络或 API 地址配置',
                error_code='connection_error'
            )

        except RequestException as e:
            raise NetworkError(
                message=f'网络请求失败: {str(e)}',
                error_code='request_error'
            )

    def get(self, endpoint: str, params: Optional[dict] = None,
            authenticated: bool = True, **kwargs) -> Any:
        """GET 请求"""
        return self._request('GET', endpoint, authenticated=authenticated,
                           params=params, **kwargs)

    def post(self, endpoint: str, data: Optional[dict] = None,
             authenticated: bool = True, **kwargs) -> Any:
        """POST 请求"""
        return self._request('POST', endpoint, authenticated=authenticated,
                           json=data, **kwargs)

    def put(self, endpoint: str, data: Optional[dict] = None,
            authenticated: bool = True, **kwargs) -> Any:
        """PUT 请求"""
        return self._request('PUT', endpoint, authenticated=authenticated,
                           json=data, **kwargs)

    def patch(self, endpoint: str, data: Optional[dict] = None,
              authenticated: bool = True, **kwargs) -> Any:
        """PATCH 请求"""
        return self._request('PATCH', endpoint, authenticated=authenticated,
                           json=data, **kwargs)

    def delete(self, endpoint: str, authenticated: bool = True, **kwargs) -> Any:
        """DELETE 请求"""
        return self._request('DELETE', endpoint, authenticated=authenticated, **kwargs)

    def upload(self, endpoint: str, files: dict, data: Optional[dict] = None,
               authenticated: bool = True, **kwargs) -> Any:
        """
        文件上传请求

        Args:
            endpoint: API 端点
            files: 文件字典，格式 {'field_name': ('filename', file_obj, 'content_type')}
            data: 表单数据
            authenticated: 是否需要认证
        """
        url = self._get_url(endpoint)
        headers = self._get_headers(authenticated)
        # 文件上传不设置 Content-Type，让 requests 自动处理
        headers.pop('Content-Type', None)

        try:
            response = self._session.post(
                url=url,
                headers=headers,
                files=files,
                data=data,
                timeout=kwargs.pop('timeout', self.timeout * 3),  # 上传超时时间更长
                **kwargs
            )

            return self._handle_response(response)

        except Timeout:
            raise NetworkError(
                message='上传超时，请检查网络连接或文件大小',
                error_code='upload_timeout'
            )

        except ConnectionError:
            raise NetworkError(
                message='无法连接到服务器',
                error_code='connection_error'
            )

        except RequestException as e:
            raise NetworkError(
                message=f'上传失败: {str(e)}',
                error_code='upload_error'
            )


# 默认客户端实例
_default_client: Optional[CloudClient] = None


def get_client() -> CloudClient:
    """获取默认客户端实例"""
    global _default_client
    if _default_client is None:
        _default_client = CloudClient()
    return _default_client


def reset_client():
    """重置默认客户端（配置变更后调用）"""
    global _default_client
    _default_client = None
