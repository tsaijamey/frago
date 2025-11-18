"""
配方系统公共接口

导出核心模块供外部使用。
"""

from .models import (
    ExplorationSession,
    ExplorationStep,
    KnowledgeDocument,
    Recipe,
    Selector,
    SelectorType,
    SessionStatus,
    StepAction,
    UpdateRecord,
)
from .selector import (
    SelectorPriority,
    create_selector_from_string,
    evaluate_selector_stability,
    extract_selectors_from_dom_element,
    generate_fallback_logic,
    sort_selectors_by_priority,
)
from .templates import JavaScriptTemplate, MarkdownTemplate

__all__ = [
    # 数据模型
    "Recipe",
    "Selector",
    "SelectorType",
    "ExplorationSession",
    "ExplorationStep",
    "SessionStatus",
    "StepAction",
    "KnowledgeDocument",
    "UpdateRecord",
    # 选择器工具
    "SelectorPriority",
    "sort_selectors_by_priority",
    "evaluate_selector_stability",
    "create_selector_from_string",
    "generate_fallback_logic",
    "extract_selectors_from_dom_element",
    # 模板
    "JavaScriptTemplate",
    "MarkdownTemplate",
]
