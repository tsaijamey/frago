"""Run命令系统数据模型

定义核心数据结构：RunInstance、LogEntry、Screenshot、CurrentRunContext
"""

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class RunStatus(str, Enum):
    """Run实例状态"""

    ACTIVE = "active"
    ARCHIVED = "archived"


class ActionType(str, Enum):
    """操作类型枚举（9种预定义类型）"""

    NAVIGATION = "navigation"  # 页面导航
    EXTRACTION = "extraction"  # 数据提取
    INTERACTION = "interaction"  # 页面交互
    SCREENSHOT = "screenshot"  # 截图
    RECIPE_EXECUTION = "recipe_execution"  # Recipe调用
    DATA_PROCESSING = "data_processing"  # 数据处理
    ANALYSIS = "analysis"  # 分析推理
    USER_INTERACTION = "user_interaction"  # 用户交互
    OTHER = "other"  # 其他


class ExecutionMethod(str, Enum):
    """执行方法枚举（6种预定义方法）"""

    COMMAND = "command"  # CLI命令执行
    RECIPE = "recipe"  # Recipe调用
    FILE = "file"  # 执行脚本文件
    MANUAL = "manual"  # 人工操作
    ANALYSIS = "analysis"  # 纯推理/思考
    TOOL = "tool"  # AI工具调用


class LogStatus(str, Enum):
    """日志状态"""

    SUCCESS = "success"
    ERROR = "error"
    WARNING = "warning"


class InsightType(str, Enum):
    """洞察类型枚举"""

    KEY_FACTOR = "key_factor"  # 关键成功要素
    PITFALL = "pitfall"  # 坑点/陷阱
    LESSON = "lesson"  # 经验教训
    WORKAROUND = "workaround"  # 变通方案


class InsightEntry(BaseModel):
    """洞察条目模型 - 记录关键发现和坑点"""

    insight_type: InsightType
    summary: str = Field(..., min_length=1, max_length=200)  # 简短摘要
    detail: Optional[str] = Field(default=None, max_length=1000)  # 详细说明
    context: Optional[str] = Field(default=None, max_length=500)  # 发生场景/上下文

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = {
            "insight_type": self.insight_type.value,
            "summary": self.summary,
        }
        if self.detail:
            result["detail"] = self.detail
        if self.context:
            result["context"] = self.context
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InsightEntry":
        """从字典创建实例"""
        if isinstance(data.get("insight_type"), str):
            data["insight_type"] = InsightType(data["insight_type"])
        return cls(**data)


class RunInstance(BaseModel):
    """Run实例模型（存储在 .metadata.json）"""

    run_id: str = Field(..., min_length=1, max_length=50, pattern=r"^[a-z0-9-]{1,50}$")
    theme_description: str = Field(..., min_length=1, max_length=500)
    created_at: datetime
    last_accessed: datetime
    status: RunStatus = RunStatus.ACTIVE

    class Config:
        """Pydantic配置"""
        extra = "allow"  # 允许额外字段，支持自定义元数据

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RunInstance":
        """从字典创建实例（兼容ISO 8601时间戳字符串）"""
        if isinstance(data.get("created_at"), str):
            data["created_at"] = datetime.fromisoformat(
                data["created_at"].replace("Z", "+00:00")
            )
        if isinstance(data.get("last_accessed"), str):
            data["last_accessed"] = datetime.fromisoformat(
                data["last_accessed"].replace("Z", "+00:00")
            )
        if isinstance(data.get("status"), str):
            data["status"] = RunStatus(data["status"])
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（ISO 8601时间戳）"""
        # 使用 model_dump() 获取所有字段，包括额外字段
        result = self.model_dump()

        # 确保时间字段格式正确
        result["created_at"] = self.created_at.isoformat().replace("+00:00", "Z")
        result["last_accessed"] = self.last_accessed.isoformat().replace("+00:00", "Z")
        result["status"] = self.status.value

        return result


class LogEntry(BaseModel):
    """日志条目模型（JSONL格式）"""

    timestamp: datetime
    step: str = Field(..., min_length=1, max_length=200)
    status: LogStatus
    action_type: ActionType
    execution_method: ExecutionMethod
    data: Dict[str, Any] = Field(default_factory=dict)
    insights: Optional[List["InsightEntry"]] = Field(default=None)  # 关键发现和坑点
    schema_version: str = "1.1"  # 升级版本号

    @field_validator("data")
    @classmethod
    def validate_data(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        """验证data字段约束"""
        if not isinstance(v, dict):
            raise ValueError("data must be a valid JSON object")
        return v

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LogEntry":
        """从字典创建实例（兼容ISO 8601时间戳字符串）"""
        if isinstance(data.get("timestamp"), str):
            data["timestamp"] = datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
        if isinstance(data.get("status"), str):
            data["status"] = LogStatus(data["status"])
        if isinstance(data.get("action_type"), str):
            data["action_type"] = ActionType(data["action_type"])
        if isinstance(data.get("execution_method"), str):
            data["execution_method"] = ExecutionMethod(data["execution_method"])
        # 解析 insights 字段
        if data.get("insights"):
            data["insights"] = [
                InsightEntry.from_dict(i) if isinstance(i, dict) else i
                for i in data["insights"]
            ]
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（ISO 8601时间戳）"""
        result = {
            "timestamp": self.timestamp.isoformat().replace("+00:00", "Z"),
            "step": self.step,
            "status": self.status.value,
            "action_type": self.action_type.value,
            "execution_method": self.execution_method.value,
            "data": self.data,
            "schema_version": self.schema_version,
        }
        # 仅当有 insights 时才包含
        if self.insights:
            result["insights"] = [i.to_dict() for i in self.insights]
        return result


class Screenshot(BaseModel):
    """截图记录模型"""

    sequence_number: int = Field(..., ge=1, le=999)
    description: str = Field(..., min_length=1, max_length=100)
    file_path: str  # 相对路径，如 "screenshots/001_search-page.png"
    timestamp: datetime

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Screenshot":
        """从字典创建实例"""
        if isinstance(data.get("timestamp"), str):
            data["timestamp"] = datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "sequence_number": self.sequence_number,
            "description": self.description,
            "file_path": self.file_path,
            "timestamp": self.timestamp.isoformat().replace("+00:00", "Z"),
        }


class CurrentRunContext(BaseModel):
    """当前Run上下文模型（存储在 .frago/current_run）"""

    run_id: str = Field(..., min_length=1, max_length=50)
    last_accessed: datetime
    theme_description: str = Field(..., min_length=1, max_length=500)
    projects_dir: Optional[str] = Field(default=None, description="projects 目录绝对路径")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CurrentRunContext":
        """从字典创建实例"""
        if isinstance(data.get("last_accessed"), str):
            data["last_accessed"] = datetime.fromisoformat(
                data["last_accessed"].replace("Z", "+00:00")
            )
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = {
            "run_id": self.run_id,
            "last_accessed": self.last_accessed.isoformat().replace("+00:00", "Z"),
            "theme_description": self.theme_description,
        }
        if self.projects_dir:
            result["projects_dir"] = self.projects_dir
        return result
