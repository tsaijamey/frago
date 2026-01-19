"""
frago Cloud 配置模块

管理云端服务的配置，包括:
- API_BASE_URL: 云端 API 地址
- Token 存储路径
"""

import os
from pathlib import Path
from typing import Optional
import yaml


# 默认 API 地址
DEFAULT_API_BASE_URL = 'https://api.agentic-llm.com/api/market'

# 配置目录
FRAGO_CONFIG_DIR = Path.home() / '.frago'
FRAGO_CONFIG_FILE = FRAGO_CONFIG_DIR / 'config.yaml'
FRAGO_RECIPES_DIR = FRAGO_CONFIG_DIR / 'recipes'


def ensure_config_dir():
    """确保配置目录存在"""
    FRAGO_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    FRAGO_RECIPES_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    """加载配置文件"""
    ensure_config_dir()

    if not FRAGO_CONFIG_FILE.exists():
        return {}

    try:
        with open(FRAGO_CONFIG_FILE, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def save_config(config: dict):
    """保存配置文件"""
    ensure_config_dir()

    with open(FRAGO_CONFIG_FILE, 'w', encoding='utf-8') as f:
        yaml.safe_dump(config, f, default_flow_style=False, allow_unicode=True)


def get_api_base_url() -> str:
    """
    获取 API 基础地址

    优先级:
    1. 环境变量 FRAGO_API_URL
    2. 配置文件 api_url
    3. 默认值
    """
    # 环境变量优先
    env_url = os.environ.get('FRAGO_API_URL')
    if env_url:
        return env_url.rstrip('/')

    # 配置文件次之
    config = load_config()
    config_url = config.get('api_url')
    if config_url:
        return config_url.rstrip('/')

    # 默认值
    return DEFAULT_API_BASE_URL


def set_api_base_url(url: str):
    """设置 API 基础地址"""
    config = load_config()
    config['api_url'] = url.rstrip('/')
    save_config(config)


def get_access_token() -> Optional[str]:
    """获取存储的 access_token"""
    config = load_config()
    return config.get('access_token')


def get_refresh_token() -> Optional[str]:
    """获取存储的 refresh_token"""
    config = load_config()
    return config.get('refresh_token')


def save_tokens(access_token: str, refresh_token: str, expires_in: int = 3600):
    """保存认证 Token"""
    config = load_config()
    config['access_token'] = access_token
    config['refresh_token'] = refresh_token
    config['token_expires_in'] = expires_in
    save_config(config)


def clear_tokens():
    """清除认证 Token"""
    config = load_config()
    config.pop('access_token', None)
    config.pop('refresh_token', None)
    config.pop('token_expires_in', None)
    save_config(config)


def get_user_info() -> Optional[dict]:
    """获取缓存的用户信息"""
    config = load_config()
    return config.get('user_info')


def save_user_info(user_info: dict):
    """缓存用户信息"""
    config = load_config()
    config['user_info'] = user_info
    save_config(config)


def clear_user_info():
    """清除用户信息缓存"""
    config = load_config()
    config.pop('user_info', None)
    save_config(config)


# 配置项定义
CONFIG_ITEMS = {
    'api_url': {
        'description': 'API 服务器地址',
        'default': DEFAULT_API_BASE_URL,
        'getter': get_api_base_url,
        'setter': set_api_base_url,
    },
}


def config_get(key: str) -> Optional[str]:
    """获取配置项"""
    if key in CONFIG_ITEMS:
        return CONFIG_ITEMS[key]['getter']()

    config = load_config()
    return config.get(key)


def config_set(key: str, value: str):
    """设置配置项"""
    if key in CONFIG_ITEMS:
        CONFIG_ITEMS[key]['setter'](value)
    else:
        config = load_config()
        config[key] = value
        save_config(config)


def config_list() -> dict:
    """列出所有配置项"""
    config = load_config()
    result = {}

    # 添加定义的配置项
    for key, item in CONFIG_ITEMS.items():
        result[key] = {
            'value': item['getter'](),
            'description': item['description'],
            'default': item['default'],
        }

    # 添加其他配置项
    for key, value in config.items():
        if key not in result and key not in ['access_token', 'refresh_token', 'user_info']:
            result[key] = {
                'value': value,
                'description': '自定义配置',
                'default': None,
            }

    return result
