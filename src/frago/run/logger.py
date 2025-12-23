"""Run Logger

Responsible for writing and reading logs in JSONL format
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .exceptions import CorruptedLogError, FileSystemError
from .models import ActionType, ExecutionMethod, InsightEntry, InsightType, LogEntry, LogStatus


class RunLogger:
    """Run Logger"""

    def __init__(self, run_dir: Path):
        """Initialize logger

        Args:
            run_dir: run instance directory path
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
        """Write log entry

        Args:
            step: step description
            status: execution status
            action_type: action type
            execution_method: execution method
            data: detailed data
            insights: list of key findings and pitfalls

        Returns:
            LogEntry instance

        Raises:
            FileSystemError: log file write failed
        """
        # Ensure log directory exists
        from .utils import ensure_directory_exists

        ensure_directory_exists(self.log_dir)

        # Create log entry
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

        # Append to JSONL file
        try:
            with self.log_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
                f.flush()  # Ensure data is written to disk
        except Exception as e:
            raise FileSystemError("write", str(self.log_file), str(e))

        return entry

    def read_logs(
        self, limit: Optional[int] = None, skip_corrupted: bool = True
    ) -> List[LogEntry]:
        """Read log entries

        Args:
            limit: maximum number of entries to read (None means all)
            skip_corrupted: whether to skip corrupted lines

        Returns:
            list of LogEntry (in chronological order)

        Raises:
            CorruptedLogError: log file corrupted and skip_corrupted=False
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

        # Return last N entries
        if limit:
            entries = entries[-limit:]

        return entries

    def count_logs(self) -> int:
        """Count log entries

        Returns:
            number of log entries
        """
        if not self.log_file.exists():
            return 0

        try:
            with self.log_file.open("r", encoding="utf-8") as f:
                return sum(1 for line in f if line.strip())
        except Exception:
            return 0

    def get_recent_logs(self, count: int = 5) -> List[LogEntry]:
        """Get recent N log entries

        Args:
            count: number of entries to retrieve

        Returns:
            list of LogEntry
        """
        return self.read_logs(limit=count, skip_corrupted=True)
