"""
配方系统核心数据模型

基于data-model.md定义的实体，使用Pydantic进行数据验证。
"""

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


class SelectorType(str, Enum):
    """DOM选择器类型枚举"""

    ARIA = "aria"  # aria-label, role (优先级5)
    DATA_ATTR = "data"  # data-* (优先级5)
    STABLE_ID = "id"  # 非动态ID (优先级4)
    SEMANTIC_CLASS = "class"  # BEM类名 (优先级3)
    SEMANTIC_TAG = "tag"  # HTML5标签 (优先级3)
    STRUCTURE = "structure"  # XPath/组合 (优先级2)
    GENERATED = "generated"  # 自动生成 (优先级1)


class Selector(BaseModel):
    """DOM元素选择器，包含稳定性评估和降级策略"""

    selector: str = Field(..., description="CSS选择器字符串")
    priority: int = Field(..., ge=1, le=5, description="稳定性优先级（1-5）")
    type: SelectorType = Field(..., description="选择器类型")
    element_description: str = Field(..., description="元素描述（用于文档）")
    fallback_selector: Optional[str] = Field(None, description="降级选择器")
    is_fragile: bool = Field(False, description="是否为脆弱选择器")

    @field_validator("is_fragile")
    @classmethod
    def check_fragile_for_generated(cls, v: bool, info) -> bool:
        """验证生成类型的选择器必须标记为脆弱"""
        if info.data.get("type") == SelectorType.GENERATED and not v:
            raise ValueError("Generated selectors must be marked as fragile")
        return v

    class Config:
        use_enum_values = True


class Recipe(BaseModel):
    """可复用的浏览器操作配方"""

    name: str = Field(..., pattern=r"^[a-z0-9_]+$", description="配方唯一标识符")
    platform: str = Field(..., description="目标平台/网站")
    action: str = Field(..., description="操作类型")
    description: str = Field(..., description="功能简述")
    script_path: Path = Field(..., description="JavaScript脚本路径")
    doc_path: Path = Field(..., description="知识文档路径")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="最后更新时间")
    version: int = Field(1, ge=1, description="版本号（更新次数）")
    selectors: List[Selector] = Field(..., description="使用的DOM选择器列表")
    prerequisites: List[str] = Field(default_factory=list, description="前置条件描述")
    tags: List[str] = Field(default_factory=list, description="标签（用于分类）")

    @field_validator("script_path", "doc_path")
    @classmethod
    def check_paths_in_recipes_dir(cls, v: Path) -> Path:
        """验证路径必须在recipes目录下"""
        if "recipes" not in str(v):
            raise ValueError(f"Path must be in recipes directory: {v}")
        return v


class SessionStatus(str, Enum):
    """探索会话状态枚举"""

    INITIALIZING = "initializing"  # 初始化
    IN_PROGRESS = "in_progress"  # 探索中
    WAITING_USER = "waiting_user"  # 等待用户输入
    COMPLETED = "completed"  # 成功完成
    FAILED = "failed"  # 失败
    CANCELLED = "cancelled"  # 用户取消


class StepAction(str, Enum):
    """探索步骤操作类型枚举"""

    NAVIGATE = "navigate"  # 导航到URL
    CLICK = "click"  # 点击元素
    EXTRACT = "extract"  # 提取内容
    WAIT = "wait"  # 等待元素或延迟
    SCROLL = "scroll"  # 滚动页面
    INPUT = "input"  # 输入文本
    SCREENSHOT = "screenshot"  # 截图


class ExplorationStep(BaseModel):
    """探索会话中的单个操作步骤"""

    step_number: int = Field(..., ge=1, description="步骤序号（从1开始）")
    action: StepAction = Field(..., description="操作类型")
    target_selector: Optional[Selector] = Field(None, description="目标元素选择器")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="操作参数")
    screenshot_path: Optional[Path] = Field(None, description="截图路径")
    result: Optional[str] = Field(None, description="步骤执行结果")
    user_confirmed: bool = Field(False, description="用户是否确认此步骤")

    @field_validator("target_selector")
    @classmethod
    def validate_selector_required(cls, v: Optional[Selector], info) -> Optional[Selector]:
        """验证某些操作必须提供target_selector"""
        action = info.data.get("action")
        if action in [StepAction.CLICK, StepAction.EXTRACT] and v is None:
            raise ValueError(f"Action {action} requires target_selector")
        return v

    @field_validator("parameters")
    @classmethod
    def validate_parameters(cls, v: Dict[str, Any], info) -> Dict[str, Any]:
        """验证参数完整性"""
        action = info.data.get("action")
        if action == StepAction.NAVIGATE and "url" not in v:
            raise ValueError("Navigate action requires 'url' parameter")
        if action == StepAction.WAIT and ("timeout" not in v and "selector" not in v):
            raise ValueError("Wait action requires 'timeout' or 'selector' parameter")
        return v

    class Config:
        use_enum_values = True


class ExplorationSession(BaseModel):
    """交互式探索过程的记录，用于生成配方脚本"""

    session_id: UUID = Field(default_factory=uuid4, description="会话唯一ID")
    user_description: str = Field(..., description="用户原始需求描述")
    target_url: str = Field(..., description="探索的目标页面URL")
    steps: List[ExplorationStep] = Field(default_factory=list, description="探索步骤序列")
    created_at: datetime = Field(default_factory=datetime.now, description="会话开始时间")
    completed_at: Optional[datetime] = Field(None, description="会话完成时间")
    status: SessionStatus = Field(
        SessionStatus.INITIALIZING, description="会话状态"
    )
    interaction_count: int = Field(
        0, ge=0, le=3, description="用户交互次数（不超过3次）"
    )
    generated_recipe_name: Optional[str] = Field(None, description="生成的配方名称")

    @field_validator("steps")
    @classmethod
    def validate_steps_not_empty_when_completed(
        cls, v: List[ExplorationStep], info
    ) -> List[ExplorationStep]:
        """验证完成状态必须有步骤"""
        status = info.data.get("status")
        if status == SessionStatus.COMPLETED and len(v) < 1:
            raise ValueError("Completed session must have at least one step")
        return v

    @field_validator("generated_recipe_name")
    @classmethod
    def validate_recipe_name_when_completed(
        cls, v: Optional[str], info
    ) -> Optional[str]:
        """验证完成状态必须有配方名称"""
        status = info.data.get("status")
        if status == SessionStatus.COMPLETED and v is None:
            raise ValueError("Completed session must have generated_recipe_name")
        return v

    class Config:
        use_enum_values = True


class UpdateRecord(BaseModel):
    """配方更新历史的单条记录"""

    date: datetime = Field(default_factory=datetime.now, description="更新日期")
    reason: str = Field(..., min_length=1, description="更新原因")
    changes: str = Field(..., min_length=1, description="主要变更内容")
    tested_on: Optional[str] = Field(None, description="测试环境说明")


class KnowledgeDocument(BaseModel):
    """配方的配套Markdown知识文档（6个标准章节）"""

    recipe_name: str = Field(..., pattern=r"^[a-z0-9_]+$", description="关联的配方名称")
    sections: Dict[str, str] = Field(..., description="6个章节内容")
    update_history: List[UpdateRecord] = Field(
        default_factory=list, description="更新历史记录"
    )
    created_at: datetime = Field(default_factory=datetime.now, description="文档创建时间")
    last_updated: datetime = Field(
        default_factory=datetime.now, description="最后更新时间"
    )

    @field_validator("sections")
    @classmethod
    def validate_required_sections(cls, v: Dict[str, str]) -> Dict[str, str]:
        """验证必须包含所有6个标准章节"""
        required_sections = {
            "功能描述",
            "使用方法",
            "前置条件",
            "预期输出",
            "注意事项",
            "更新历史",
        }
        missing = required_sections - set(v.keys())
        if missing:
            raise ValueError(f"Missing required sections: {missing}")
        return v
