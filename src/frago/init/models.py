"""
数据模型定义

包含 frago init 命令使用的所有 Pydantic 模型：
- Config: 持久化配置
- APIEndpoint: 自定义 API 端点配置
- TemporaryState: Ctrl+C 恢复状态
- InstallationStep: 安装步骤状态机
- DependencyCheckResult: 依赖检查结果
- ResourceType: 资源类型枚举
- InstallResult: 资源安装结果
- ResourceStatus: 资源安装状态
"""

from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, List, Literal
from datetime import datetime, timedelta
from enum import Enum


class APIEndpoint(BaseModel):
    """API 端点配置（嵌套在 Config 中）"""

    type: Literal["deepseek", "aliyun", "kimi", "minimax", "custom"]
    url: Optional[str] = None
    api_key: str

    @model_validator(mode="after")
    def validate_url_for_custom(self) -> "APIEndpoint":
        """验证 URL 必填性（custom 类型必须提供 URL）"""
        if self.type == "custom" and not self.url:
            raise ValueError("Custom endpoint requires URL")
        return self


class Config(BaseModel):
    """Frago 配置实体（持久化到 ~/.frago/config.json）"""

    schema_version: str = "1.0"

    # 依赖信息
    node_version: Optional[str] = None
    node_path: Optional[str] = None
    npm_version: Optional[str] = None
    claude_code_version: Optional[str] = None
    claude_code_path: Optional[str] = None

    # 认证配置（互斥）
    auth_method: Literal["official", "custom"] = "official"
    api_endpoint: Optional[APIEndpoint] = None

    # 可选功能
    ccr_enabled: bool = False
    ccr_config_path: Optional[str] = None

    # 工作目录配置
    working_directory: Optional[str] = None  # 默认 projects 目录的父目录

    # 多设备同步配置
    sync_repo_url: Optional[str] = None  # 用户私有仓库 URL（用于 sync）

    # 资源安装状态
    resources_installed: bool = False
    resources_version: Optional[str] = None
    last_resource_update: Optional[datetime] = None

    # 元数据
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    init_completed: bool = False

    @model_validator(mode="after")
    def validate_auth_consistency(self) -> "Config":
        """验证认证配置一致性（互斥性约束）"""
        if self.auth_method == "custom" and not self.api_endpoint:
            raise ValueError("Custom auth requires api_endpoint")
        if self.auth_method == "official" and self.api_endpoint:
            raise ValueError("Official auth cannot have api_endpoint")
        return self

    class ConfigDict:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }


class TemporaryState(BaseModel):
    """临时状态（Ctrl+C 恢复用，保存到 ~/.frago/.init_state.json）"""

    completed_steps: List[str] = Field(default_factory=list)
    current_step: Optional[str] = None
    interrupted_at: datetime = Field(default_factory=datetime.now)
    recoverable: bool = True

    def is_expired(self, days: int = 7) -> bool:
        """检查是否过期（默认 7 天）"""
        return datetime.now() - self.interrupted_at > timedelta(days=days)

    def add_step(self, step: str) -> None:
        """记录完成步骤"""
        if step not in self.completed_steps:
            self.completed_steps.append(step)

    def set_current_step(self, step: str) -> None:
        """设置当前步骤"""
        self.current_step = step

    def is_step_completed(self, step: str) -> bool:
        """检查步骤是否已完成"""
        return step in self.completed_steps


class StepStatus(str, Enum):
    """安装步骤状态枚举"""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class InstallationStep(BaseModel):
    """安装步骤状态机"""

    name: str
    status: StepStatus = StepStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    error_code: Optional[int] = None

    def start(self) -> None:
        """标记步骤开始"""
        self.status = StepStatus.IN_PROGRESS
        self.started_at = datetime.now()

    def complete(self) -> None:
        """标记步骤成功"""
        self.status = StepStatus.COMPLETED
        self.completed_at = datetime.now()

    def fail(self, error: str, code: int) -> None:
        """标记步骤失败"""
        self.status = StepStatus.FAILED
        self.completed_at = datetime.now()
        self.error_message = error
        self.error_code = code

    def skip(self) -> None:
        """标记步骤跳过"""
        self.status = StepStatus.SKIPPED
        self.completed_at = datetime.now()


class DependencyCheckResult(BaseModel):
    """依赖检查结果（用于并行检查）"""

    name: str
    installed: bool = False
    version: Optional[str] = None
    path: Optional[str] = None
    version_sufficient: bool = False
    required_version: str
    error: Optional[str] = None

    def needs_install(self) -> bool:
        """是否需要安装"""
        return not self.installed or not self.version_sufficient

    def display_status(self) -> str:
        """生成显示状态"""
        if not self.installed:
            return f"❌ {self.name}: 未安装"
        elif not self.version_sufficient:
            return f"⚠️  {self.name}: 版本不足 (当前 {self.version}, 要求 {self.required_version})"
        else:
            return f"✅ {self.name}: {self.version}"


class ResourceType(str, Enum):
    """资源类型枚举"""

    COMMAND = "command"  # Claude Code slash 命令
    SKILL = "skill"      # Claude Code skill
    RECIPE = "recipe"    # 示例 recipe


class InstallResult(BaseModel):
    """资源安装操作结果"""

    resource_type: ResourceType
    installed: List[str] = Field(default_factory=list)  # 已安装的文件路径列表
    skipped: List[str] = Field(default_factory=list)    # 跳过的文件路径列表（已存在）
    backed_up: List[str] = Field(default_factory=list)  # 已备份的文件路径列表
    errors: List[str] = Field(default_factory=list)     # 错误信息列表

    @property
    def success(self) -> bool:
        """是否全部成功（无错误）"""
        return len(self.errors) == 0

    @property
    def total_count(self) -> int:
        """总处理文件数"""
        return len(self.installed) + len(self.skipped)


class ResourceStatus(BaseModel):
    """资源安装状态（用于 --status 显示）"""

    commands: Optional[InstallResult] = None
    skills: Optional[InstallResult] = None
    recipes: Optional[InstallResult] = None
    frago_version: str = ""
    install_time: Optional[datetime] = None

    @property
    def all_success(self) -> bool:
        """所有资源是否安装成功"""
        results = [self.commands, self.skills, self.recipes]
        return all(r is None or r.success for r in results)
