"""Run Command System Data Models

Defines core data structures: RunInstance, LogEntry, Screenshot, CurrentRunContext
"""

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class RunStatus(str, Enum):
    """Run instance status"""

    ACTIVE = "active"
    ARCHIVED = "archived"


class ActionType(str, Enum):
    """Action type enumeration (9 predefined types)"""

    NAVIGATION = "navigation"  # Page navigation
    EXTRACTION = "extraction"  # Data extraction
    INTERACTION = "interaction"  # Page interaction
    SCREENSHOT = "screenshot"  # Screenshot
    RECIPE_EXECUTION = "recipe_execution"  # Recipe invocation
    DATA_PROCESSING = "data_processing"  # Data processing
    ANALYSIS = "analysis"  # Analysis and reasoning
    USER_INTERACTION = "user_interaction"  # User interaction
    OTHER = "other"  # Other


class ExecutionMethod(str, Enum):
    """Execution method enumeration (6 predefined methods)"""

    COMMAND = "command"  # CLI command execution
    RECIPE = "recipe"  # Recipe invocation
    FILE = "file"  # Execute script file
    MANUAL = "manual"  # Manual operation
    ANALYSIS = "analysis"  # Pure reasoning/thinking
    TOOL = "tool"  # AI tool invocation


class LogStatus(str, Enum):
    """Log status"""

    SUCCESS = "success"
    ERROR = "error"
    WARNING = "warning"


class InsightType(str, Enum):
    """Insight type enumeration"""

    KEY_FACTOR = "key_factor"  # Key success factor
    PITFALL = "pitfall"  # Pitfall/trap
    LESSON = "lesson"  # Lesson learned
    WORKAROUND = "workaround"  # Workaround solution


class InsightEntry(BaseModel):
    """Insight entry model - records key findings and pitfalls"""

    insight_type: InsightType
    summary: str = Field(..., min_length=1, max_length=200)  # Brief summary
    detail: Optional[str] = Field(default=None, max_length=1000)  # Detailed explanation
    context: Optional[str] = Field(default=None, max_length=500)  # Occurrence scenario/context

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
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
        """Create instance from dictionary"""
        if isinstance(data.get("insight_type"), str):
            data["insight_type"] = InsightType(data["insight_type"])
        return cls(**data)


class RunInstance(BaseModel):
    """Run instance model (stored in .metadata.json)"""

    run_id: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]{1,100}$")
    theme_description: str = Field(..., min_length=1, max_length=500)
    created_at: datetime
    last_accessed: datetime
    status: RunStatus = RunStatus.ACTIVE

    class Config:
        """Pydantic configuration"""
        extra = "allow"  # Allow extra fields for custom metadata

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RunInstance":
        """Create instance from dictionary (compatible with ISO 8601 timestamp strings)"""
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
        """Convert to dictionary (ISO 8601 timestamps)"""
        # Use model_dump() to get all fields including extra fields
        result = self.model_dump()

        # Ensure time fields are formatted correctly
        result["created_at"] = self.created_at.isoformat().replace("+00:00", "Z")
        result["last_accessed"] = self.last_accessed.isoformat().replace("+00:00", "Z")
        result["status"] = self.status.value

        return result


class LogEntry(BaseModel):
    """Log entry model (JSONL format)"""

    timestamp: datetime
    step: str = Field(..., min_length=1, max_length=200)
    status: LogStatus
    action_type: ActionType
    execution_method: ExecutionMethod
    data: Dict[str, Any] = Field(default_factory=dict)
    insights: Optional[List["InsightEntry"]] = Field(default=None)  # Key findings and pitfalls
    schema_version: str = "1.1"  # Schema version

    @field_validator("data")
    @classmethod
    def validate_data(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        """Validate data field constraints"""
        if not isinstance(v, dict):
            raise ValueError("data must be a valid JSON object")
        return v

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LogEntry":
        """Create instance from dictionary (compatible with ISO 8601 timestamp strings)"""
        if isinstance(data.get("timestamp"), str):
            data["timestamp"] = datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
        if isinstance(data.get("status"), str):
            data["status"] = LogStatus(data["status"])
        if isinstance(data.get("action_type"), str):
            data["action_type"] = ActionType(data["action_type"])
        if isinstance(data.get("execution_method"), str):
            data["execution_method"] = ExecutionMethod(data["execution_method"])
        # Parse insights field
        if data.get("insights"):
            data["insights"] = [
                InsightEntry.from_dict(i) if isinstance(i, dict) else i
                for i in data["insights"]
            ]
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (ISO 8601 timestamps)"""
        result = {
            "timestamp": self.timestamp.isoformat().replace("+00:00", "Z"),
            "step": self.step,
            "status": self.status.value,
            "action_type": self.action_type.value,
            "execution_method": self.execution_method.value,
            "data": self.data,
            "schema_version": self.schema_version,
        }
        # Only include insights when present
        if self.insights:
            result["insights"] = [i.to_dict() for i in self.insights]
        return result


class Screenshot(BaseModel):
    """Screenshot record model"""

    sequence_number: int = Field(..., ge=1, le=999)
    description: str = Field(..., min_length=1, max_length=100)
    file_path: str  # Relative path, e.g. "screenshots/001_search-page.png"
    timestamp: datetime

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Screenshot":
        """Create instance from dictionary"""
        if isinstance(data.get("timestamp"), str):
            data["timestamp"] = datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "sequence_number": self.sequence_number,
            "description": self.description,
            "file_path": self.file_path,
            "timestamp": self.timestamp.isoformat().replace("+00:00", "Z"),
        }


class CurrentRunContext(BaseModel):
    """Current Run context model (stored in .frago/current_run)"""

    run_id: str = Field(..., min_length=1, max_length=100)
    last_accessed: datetime
    theme_description: str = Field(..., min_length=1, max_length=500)
    projects_dir: Optional[str] = Field(default=None, description="projects directory absolute path")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CurrentRunContext":
        """Create instance from dictionary"""
        if isinstance(data.get("last_accessed"), str):
            data["last_accessed"] = datetime.fromisoformat(
                data["last_accessed"].replace("Z", "+00:00")
            )
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        result = {
            "run_id": self.run_id,
            "last_accessed": self.last_accessed.isoformat().replace("+00:00", "Z"),
            "theme_description": self.theme_description,
        }
        if self.projects_dir:
            result["projects_dir"] = self.projects_dir
        return result
