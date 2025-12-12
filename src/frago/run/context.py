"""Run上下文管理器

负责读写 ~/.frago/current_run 配置文件，支持环境变量优先级
"""

import json
import os
from pathlib import Path
from typing import Optional

from .exceptions import (
    ContextAlreadySetError,
    ContextNotSetError,
    FileSystemError,
    RunNotFoundError,
)
from .models import CurrentRunContext


class ContextManager:
    """Run上下文管理器"""

    def __init__(self, frago_home: Path, projects_dir: Path):
        """初始化上下文管理器

        Args:
            frago_home: Frago 用户目录 (~/.frago)
            projects_dir: projects目录路径
        """
        self.frago_home = frago_home
        self.projects_dir = projects_dir
        self.config_dir = frago_home
        self.config_file = self.config_dir / "current_run"

    def get_current_run(self) -> CurrentRunContext:
        """获取当前run上下文

        优先级: 环境变量 FRAGO_CURRENT_RUN > 配置文件

        Returns:
            CurrentRunContext实例

        Raises:
            ContextNotSetError: 上下文未设置
            RunNotFoundError: 指向的run不存在
        """
        # 1. 检查环境变量（最高优先级）
        env_run_id = os.getenv("FRAGO_CURRENT_RUN")
        if env_run_id:
            run_dir = self.projects_dir / env_run_id
            if not run_dir.exists():
                raise RunNotFoundError(env_run_id)

            # 从metadata读取主题描述
            metadata_file = run_dir / ".metadata.json"
            if metadata_file.exists():
                metadata = json.loads(metadata_file.read_text())
                from datetime import datetime

                return CurrentRunContext(
                    run_id=env_run_id,
                    last_accessed=datetime.now(),
                    theme_description=metadata.get("theme_description", env_run_id),
                )
            else:
                from datetime import datetime

                return CurrentRunContext(
                    run_id=env_run_id,
                    last_accessed=datetime.now(),
                    theme_description=env_run_id,
                )

        # 2. 读取配置文件
        if not self.config_file.exists():
            raise ContextNotSetError()

        try:
            data = json.loads(self.config_file.read_text())
            context = CurrentRunContext.from_dict(data)
        except Exception as e:
            raise FileSystemError("read", str(self.config_file), str(e))

        # 3. 验证run目录存在
        run_dir = self.projects_dir / context.run_id
        if not run_dir.exists():
            # 清空失效的配置
            self._clear_context()
            raise RunNotFoundError(context.run_id)

        return context

    def set_current_run(self, run_id: str, theme_description: str) -> CurrentRunContext:
        """设置当前run上下文

        Args:
            run_id: 目标run的ID
            theme_description: 主题描述

        Returns:
            CurrentRunContext实例

        Raises:
            RunNotFoundError: run_id不存在
            ContextAlreadySetError: 已有其他run在运行
            FileSystemError: 配置文件写入失败
        """
        # 互斥检查：如果已有上下文且不是同一个run，则拒绝
        if self.config_file.exists():
            try:
                data = json.loads(self.config_file.read_text())
                existing_run_id = data.get("run_id")
                if existing_run_id and existing_run_id != run_id:
                    raise ContextAlreadySetError(existing_run_id)
            except json.JSONDecodeError:
                pass  # 配置文件损坏，允许覆盖

        # 验证run存在
        run_dir = self.projects_dir / run_id
        if not run_dir.exists():
            raise RunNotFoundError(run_id)

        # 创建配置目录
        from .utils import ensure_directory_exists

        ensure_directory_exists(self.config_dir)

        # 写入配置
        from datetime import datetime

        context = CurrentRunContext(
            run_id=run_id,
            last_accessed=datetime.now(),
            theme_description=theme_description,
            projects_dir=str(self.projects_dir),
        )

        try:
            self.config_file.write_text(json.dumps(context.to_dict(), indent=2))
        except Exception as e:
            raise FileSystemError("write", str(self.config_file), str(e))

        # 更新run的last_accessed
        metadata_file = run_dir / ".metadata.json"
        if metadata_file.exists():
            metadata = json.loads(metadata_file.read_text())
            metadata["last_accessed"] = context.last_accessed.isoformat().replace(
                "+00:00", "Z"
            )
            metadata_file.write_text(json.dumps(metadata, indent=2))

        return context

    def _clear_context(self) -> None:
        """清空上下文配置（内部方法）"""
        if self.config_file.exists():
            try:
                self.config_file.unlink()
            except Exception:
                pass  # 忽略清空失败

    def release_context(self) -> Optional[str]:
        """释放当前上下文（公开方法）

        Returns:
            被释放的run_id，如果没有上下文则返回None
        """
        released_run_id = None
        if self.config_file.exists():
            try:
                data = json.loads(self.config_file.read_text())
                released_run_id = data.get("run_id")
            except json.JSONDecodeError:
                pass
            self._clear_context()
        return released_run_id

    def get_current_run_id(self) -> Optional[str]:
        """获取当前run_id（不抛出异常）

        Returns:
            run_id或None
        """
        try:
            context = self.get_current_run()
            return context.run_id
        except (ContextNotSetError, RunNotFoundError):
            return None
