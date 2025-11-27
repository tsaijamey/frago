"""Run日志记录器

负责JSONL格式的日志写入和读取
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .exceptions import CorruptedLogError, FileSystemError
from .models import ActionType, ExecutionMethod, InsightEntry, InsightType, LogEntry, LogStatus


class RunLogger:
    """Run日志记录器"""

    def __init__(self, run_dir: Path):
        """初始化日志记录器

        Args:
            run_dir: run实例目录路径
        """
        self.run_dir = run_dir
        self.log_dir = run_dir / "logs"
        self.log_file = self.log_dir / "execution.jsonl"

    def write_log(
        self,
        step: str,
        status: LogStatus,
        action_type: ActionType,
        execution_method: ExecutionMethod,
        data: Dict,
        insights: Optional[List[InsightEntry]] = None,
    ) -> LogEntry:
        """写入日志条目

        Args:
            step: 步骤描述
            status: 执行状态
            action_type: 操作类型
            execution_method: 执行方法
            data: 详细数据
            insights: 关键发现和坑点列表

        Returns:
            LogEntry实例

        Raises:
            FileSystemError: 日志文件写入失败
        """
        # 确保日志目录存在
        from .utils import ensure_directory_exists

        ensure_directory_exists(self.log_dir)

        # 创建日志条目
        entry = LogEntry(
            timestamp=datetime.now(),
            step=step,
            status=status,
            action_type=action_type,
            execution_method=execution_method,
            data=data,
            insights=insights,
            schema_version="1.1",
        )

        # 追加到JSONL文件
        try:
            with self.log_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
                f.flush()  # 确保数据写入磁盘
        except Exception as e:
            raise FileSystemError("write", str(self.log_file), str(e))

        return entry

    def read_logs(
        self, limit: Optional[int] = None, skip_corrupted: bool = True
    ) -> List[LogEntry]:
        """读取日志条目

        Args:
            limit: 最大读取条数（None表示全部）
            skip_corrupted: 是否跳过损坏的行

        Returns:
            LogEntry列表（按时间升序）

        Raises:
            CorruptedLogError: 日志文件损坏且skip_corrupted=False
        """
        if not self.log_file.exists():
            return []

        entries: List[LogEntry] = []
        corrupted_count = 0

        try:
            with self.log_file.open("r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, start=1):
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        data = json.loads(line)
                        entry = LogEntry.from_dict(data)
                        entries.append(entry)
                    except Exception as e:
                        corrupted_count += 1
                        if not skip_corrupted:
                            raise CorruptedLogError(str(self.log_file), line_num, str(e))
        except CorruptedLogError:
            raise
        except Exception as e:
            raise FileSystemError("read", str(self.log_file), str(e))

        # 返回最后N条
        if limit:
            entries = entries[-limit:]

        return entries

    def count_logs(self) -> int:
        """统计日志条目数量

        Returns:
            日志条数
        """
        if not self.log_file.exists():
            return 0

        try:
            with self.log_file.open("r", encoding="utf-8") as f:
                return sum(1 for line in f if line.strip())
        except Exception:
            return 0

    def get_recent_logs(self, count: int = 5) -> List[LogEntry]:
        """获取最近N条日志

        Args:
            count: 获取条数

        Returns:
            LogEntry列表
        """
        return self.read_logs(limit=count, skip_corrupted=True)
