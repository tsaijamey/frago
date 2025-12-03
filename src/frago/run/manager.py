"""Run实例管理器

负责创建、查找、列出、归档run实例
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .exceptions import FileSystemError, InvalidRunIDError, RunNotFoundError
from .models import RunInstance, RunStatus
from .utils import ensure_directory_exists, generate_theme_slug, is_valid_run_id


class RunManager:
    """Run实例管理器"""

    def __init__(self, projects_dir: Path):
        """初始化管理器

        Args:
            projects_dir: projects目录路径
        """
        self.projects_dir = projects_dir
        ensure_directory_exists(projects_dir)

    def create_run(self, theme_description: str, run_id: Optional[str] = None) -> RunInstance:
        """创建新run实例

        Args:
            theme_description: 任务描述
            run_id: 可选的自定义run_id（默认自动生成）

        Returns:
            RunInstance实例

        Raises:
            InvalidRunIDError: run_id格式不合法
            FileSystemError: 目录创建失败
        """
        # 生成或验证run_id（始终添加日期前缀）
        from datetime import datetime as dt
        date_prefix = dt.now().strftime("%Y%m%d")

        if run_id is None:
            run_id = generate_theme_slug(theme_description)
        else:
            if not is_valid_run_id(run_id):
                raise InvalidRunIDError(run_id, "格式必须为小写字母、数字、连字符，长度1-59")
            # 自定义 run_id 也添加日期前缀（如果还没有）
            if not run_id.startswith(date_prefix):
                run_id = f"{date_prefix}-{run_id}"

        run_dir = self.projects_dir / run_id
        now = datetime.now()

        # 创建目录结构
        ensure_directory_exists(run_dir)
        ensure_directory_exists(run_dir / "logs")
        ensure_directory_exists(run_dir / "screenshots")
        ensure_directory_exists(run_dir / "scripts")
        ensure_directory_exists(run_dir / "outputs")

        # 创建RunInstance
        instance = RunInstance(
            run_id=run_id,
            theme_description=theme_description,
            created_at=now,
            last_accessed=now,
            status=RunStatus.ACTIVE,
        )

        # 写入.metadata.json
        metadata_file = run_dir / ".metadata.json"
        try:
            metadata_file.write_text(json.dumps(instance.to_dict(), indent=2))
        except Exception as e:
            raise FileSystemError("write", str(metadata_file), str(e))

        return instance

    def find_run(self, run_id: str) -> RunInstance:
        """查找run实例

        Args:
            run_id: run的ID

        Returns:
            RunInstance实例

        Raises:
            RunNotFoundError: run不存在
            FileSystemError: 元数据读取失败
        """
        run_dir = self.projects_dir / run_id
        if not run_dir.exists() or not run_dir.is_dir():
            raise RunNotFoundError(run_id)

        metadata_file = run_dir / ".metadata.json"
        if not metadata_file.exists():
            raise FileSystemError("read", str(metadata_file), "Metadata file not found")

        try:
            data = json.loads(metadata_file.read_text())
            return RunInstance.from_dict(data)
        except Exception as e:
            raise FileSystemError("read", str(metadata_file), str(e))

    def list_runs(
        self, status: Optional[RunStatus] = None
    ) -> List[Dict]:
        """列出所有run实例

        Args:
            status: 过滤状态（None表示全部）

        Returns:
            run信息列表（包含统计数据）
        """
        if not self.projects_dir.exists():
            return []

        runs = []
        for run_dir in self.projects_dir.iterdir():
            if not run_dir.is_dir():
                continue

            metadata_file = run_dir / ".metadata.json"
            if not metadata_file.exists():
                continue

            try:
                data = json.loads(metadata_file.read_text())
                instance = RunInstance.from_dict(data)

                # 状态过滤
                if status and instance.status != status:
                    continue

                # 统计信息
                from .logger import RunLogger

                logger = RunLogger(run_dir)
                log_count = logger.count_logs()
                screenshot_count = len(list((run_dir / "screenshots").glob("*.png")))

                runs.append(
                    {
                        "run_id": instance.run_id,
                        "status": instance.status.value,
                        "created_at": instance.created_at.isoformat().replace("+00:00", "Z"),
                        "last_accessed": instance.last_accessed.isoformat().replace(
                            "+00:00", "Z"
                        ),
                        "theme_description": instance.theme_description,
                        "log_count": log_count,
                        "screenshot_count": screenshot_count,
                    }
                )
            except Exception:
                continue  # 跳过损坏的run

        # 按最后访问时间降序排序
        runs.sort(key=lambda r: r["last_accessed"], reverse=True)

        return runs

    def archive_run(self, run_id: str) -> RunInstance:
        """归档run实例

        Args:
            run_id: run的ID

        Returns:
            RunInstance实例

        Raises:
            RunNotFoundError: run不存在
            FileSystemError: 元数据更新失败
        """
        instance = self.find_run(run_id)
        instance.status = RunStatus.ARCHIVED

        metadata_file = self.projects_dir / run_id / ".metadata.json"
        try:
            metadata_file.write_text(json.dumps(instance.to_dict(), indent=2))
        except Exception as e:
            raise FileSystemError("write", str(metadata_file), str(e))

        return instance

    def get_run_statistics(self, run_id: str) -> Dict:
        """获取run实例统计信息

        Args:
            run_id: run的ID

        Returns:
            统计信息字典
        """
        instance = self.find_run(run_id)
        run_dir = self.projects_dir / run_id

        from .logger import RunLogger

        logger = RunLogger(run_dir)

        # 统计文件数量
        screenshot_count = len(list((run_dir / "screenshots").glob("*.png")))
        script_count = sum(
            1
            for p in (run_dir / "scripts").iterdir()
            if p.is_file() and p.suffix in [".py", ".js", ".sh"]
        )

        # 计算磁盘使用
        disk_usage = sum(f.stat().st_size for f in run_dir.rglob("*") if f.is_file())

        return {
            "log_entries": logger.count_logs(),
            "screenshots": screenshot_count,
            "scripts": script_count,
            "disk_usage_bytes": disk_usage,
        }
