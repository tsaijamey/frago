"""主配置文件管理模块

提供 ~/.frago/config.json 的读写操作，支持部分更新。
"""

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from frago.init.models import Config
from pydantic import ValidationError

# 主配置文件路径
CONFIG_PATH = Path.home() / ".frago" / "config.json"


def load_config() -> Config:
    """加载主配置文件

    Returns:
        Config 实例

    Notes:
        - 如果文件不存在，返回默认配置
        - 如果文件损坏，备份并返回默认配置
    """
    if not CONFIG_PATH.exists():
        return Config()

    try:
        data = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
        return Config(**data)
    except json.JSONDecodeError as e:
        # JSON 解析失败，备份损坏文件
        _backup_corrupted_config(f"json_error_{e}")
        return Config()
    except ValidationError as e:
        # Pydantic 验证失败，备份损坏文件
        _backup_corrupted_config(f"validation_error")
        return Config()
    except Exception as e:
        # 其他错误
        _backup_corrupted_config(f"unknown_error")
        return Config()


def save_config(config: Config) -> None:
    """保存配置文件

    Args:
        config: Config 实例

    Notes:
        - 自动创建父目录
        - 使用 JSON 格式化输出（indent=2）
        - 自动更新 updated_at 字段
    """
    # 确保目录存在
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    # 更新时间戳
    config.updated_at = datetime.now()

    # 序列化为 JSON
    config_dict = config.model_dump(mode='json')

    # 写入文件
    CONFIG_PATH.write_text(
        json.dumps(config_dict, indent=2, ensure_ascii=False) + '\n',
        encoding='utf-8'
    )


def update_config(updates: Dict[str, Any]) -> Config:
    """部分更新配置文件

    Args:
        updates: 要更新的字段字典，例如 {"working_directory": "/path"}

    Returns:
        更新后的 Config 实例

    Raises:
        ValidationError: 如果更新后的配置不合法

    Examples:
        >>> config = update_config({"working_directory": "/home/user/projects"})
        >>> config = update_config({"sync_repo_url": "git@github.com:user/repo.git"})
    """
    # 加载现有配置
    config = load_config()

    # 应用更新
    for key, value in updates.items():
        if hasattr(config, key):
            setattr(config, key, value)

    # 保存配置（会触发 Pydantic 验证）
    save_config(config)

    return config


def _backup_corrupted_config(reason: str) -> None:
    """备份损坏的配置文件

    Args:
        reason: 损坏原因（用于备份文件名）
    """
    if not CONFIG_PATH.exists():
        return

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = CONFIG_PATH.with_suffix(f'.json.bak.{timestamp}')

    try:
        shutil.copy(CONFIG_PATH, backup_path)
    except Exception:
        pass  # 备份失败不影响主流程
