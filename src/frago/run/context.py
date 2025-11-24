"""Run上下文管理器

负责读写 .frago/current_run 配置文件，支持环境变量优先级
"""

import json
import os
from pathlib import Path
from typing import Optional

from .exceptions import ContextNotSetError, FileSystemError, RunNotFoundError
from .models import CurrentRunContext


class ContextManager:
    """Run上下文管理器"""

    def __init__(self, project_root: Path, projects_dir: Path):
        """初始化上下文管理器

        Args:
            project_root: 项目根目录
            projects_dir: projects目录路径
        """
        self.project_root = project_root
        self.projects_dir = projects_dir
        self.config_dir = project_root / ".frago"
        self.config_file = self.config_dir / "current_project"

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
            FileSystemError: 配置文件写入失败
        """
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
