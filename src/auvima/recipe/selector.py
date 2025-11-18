"""
DOM选择器优化策略

实现选择器稳定性评估和降级逻辑生成，基于research.md中的优先级策略。
"""

from typing import List, Tuple

from .models import Selector, SelectorType


class SelectorPriority:
    """选择器优先级常量（基于research.md §2）"""

    ARIA = 5  # aria-label, role
    DATA_ATTR = 5  # data-testid, data-*
    STABLE_ID = 4  # 非动态生成的ID
    SEMANTIC_CLASS = 3  # BEM类名
    SEMANTIC_TAG = 3  # HTML5标签
    STRUCTURE = 2  # XPath/组合选择器
    GENERATED = 1  # 自动生成的类名（避免使用）

    @classmethod
    def get_priority(cls, selector_type: SelectorType) -> int:
        """根据选择器类型返回优先级"""
        priority_map = {
            SelectorType.ARIA: cls.ARIA,
            SelectorType.DATA_ATTR: cls.DATA_ATTR,
            SelectorType.STABLE_ID: cls.STABLE_ID,
            SelectorType.SEMANTIC_CLASS: cls.SEMANTIC_CLASS,
            SelectorType.SEMANTIC_TAG: cls.SEMANTIC_TAG,
            SelectorType.STRUCTURE: cls.STRUCTURE,
            SelectorType.GENERATED: cls.GENERATED,
        }
        return priority_map.get(selector_type, 1)


def sort_selectors_by_priority(selectors: List[Selector]) -> List[Selector]:
    """
    按优先级降序排列选择器（优先级高的在前）

    Args:
        selectors: 选择器列表

    Returns:
        排序后的选择器列表
    """
    return sorted(selectors, key=lambda s: s.priority, reverse=True)


def evaluate_selector_stability(selector_str: str) -> Tuple[SelectorType, bool]:
    """
    评估选择器字符串的稳定性，返回类型和是否脆弱

    Args:
        selector_str: CSS选择器字符串

    Returns:
        (SelectorType, is_fragile) 元组
    """
    selector_lower = selector_str.lower()

    # ARIA属性（最稳定）
    if "aria-" in selector_lower or "[role=" in selector_lower:
        return SelectorType.ARIA, False

    # data-*属性（最稳定）
    if "data-" in selector_lower:
        return SelectorType.DATA_ATTR, False

    # ID选择器
    if selector_str.startswith("#"):
        # 检测动态生成的ID（包含数字序列或哈希）
        id_value = selector_str[1:]
        is_dynamic = any(
            [
                id_value.isdigit(),  # 纯数字ID
                len([c for c in id_value if c.isdigit()]) > 5,  # 包含大量数字
                len(id_value) > 20,  # 过长（可能是哈希）
            ]
        )
        return SelectorType.STABLE_ID, is_dynamic

    # 类选择器
    if "." in selector_str:
        # 检测生成的类名（如.css-1x2y3z4, ._hash123）
        is_generated = any(
            [
                "css-" in selector_lower,
                selector_str.split(".")[-1].startswith("_"),  # _开头的内部类名
                len(selector_str.split(".")[-1]) > 15,  # 过长的类名
            ]
        )
        if is_generated:
            return SelectorType.GENERATED, True
        else:
            return SelectorType.SEMANTIC_CLASS, False

    # 标签选择器
    if selector_str.split("[")[0] in [
        "button",
        "nav",
        "article",
        "section",
        "header",
        "footer",
        "aside",
        "main",
    ]:
        return SelectorType.SEMANTIC_TAG, False

    # XPath或组合选择器
    if any(
        [
            ">" in selector_str,
            "+" in selector_str,
            "~" in selector_str,
            " " in selector_str and len(selector_str.split()) > 2,
        ]
    ):
        return SelectorType.STRUCTURE, False

    # 默认为结构选择器（中等脆弱性）
    return SelectorType.STRUCTURE, False


def create_selector_from_string(
    selector_str: str, element_description: str
) -> Selector:
    """
    从选择器字符串创建Selector对象，自动评估稳定性

    Args:
        selector_str: CSS选择器字符串
        element_description: 元素描述

    Returns:
        Selector对象
    """
    selector_type, is_fragile = evaluate_selector_stability(selector_str)
    priority = SelectorPriority.get_priority(selector_type)

    return Selector(
        selector=selector_str,
        priority=priority,
        type=selector_type,
        element_description=element_description,
        is_fragile=is_fragile,
    )


def generate_fallback_logic(selectors: List[Selector]) -> str:
    """
    生成JavaScript降级逻辑代码

    Args:
        selectors: 按优先级排序的选择器列表

    Returns:
        JavaScript代码字符串
    """
    if not selectors:
        return "// No selectors available"

    # 排序确保高优先级在前
    sorted_selectors = sort_selectors_by_priority(selectors)

    lines = []
    lines.append(f"// 尝试定位: {selectors[0].element_description}")

    for i, sel in enumerate(sorted_selectors):
        if i == 0:
            lines.append(
                f"let element = document.querySelector('{sel.selector}'); "
                f"// 优先级{sel.priority}: {sel.type}"
            )
        else:
            lines.append("if (!element) {")
            lines.append(
                f"  element = document.querySelector('{sel.selector}'); "
                f"// 降级: 优先级{sel.priority}: {sel.type}"
            )
            lines.append("}")

    lines.append("if (!element) {")
    lines.append(
        f"  throw new Error('无法定位{selectors[0].element_description}，页面结构可能已变化');"
    )
    lines.append("}")

    return "\n".join(lines)


def extract_selectors_from_dom_element(
    element_data: dict, element_description: str
) -> List[Selector]:
    """
    从DOM元素数据中提取多个可能的选择器

    Args:
        element_data: 包含元素属性的字典（如{"id": "btn", "class": ["btn", "primary"], "aria-label": "Submit"}）
        element_description: 元素描述

    Returns:
        选择器列表（按优先级排序）
    """
    selectors = []

    # 提取ARIA属性
    if "aria-label" in element_data:
        selectors.append(
            Selector(
                selector=f'[aria-label="{element_data["aria-label"]}"]',
                priority=SelectorPriority.ARIA,
                type=SelectorType.ARIA,
                element_description=element_description,
                is_fragile=False,
            )
        )

    if "role" in element_data:
        selectors.append(
            Selector(
                selector=f'[role="{element_data["role"]}"]',
                priority=SelectorPriority.ARIA,
                type=SelectorType.ARIA,
                element_description=element_description,
                is_fragile=False,
            )
        )

    # 提取data-*属性
    data_attrs = {k: v for k, v in element_data.items() if k.startswith("data-")}
    for attr, value in data_attrs.items():
        selectors.append(
            Selector(
                selector=f'[{attr}="{value}"]',
                priority=SelectorPriority.DATA_ATTR,
                type=SelectorType.DATA_ATTR,
                element_description=element_description,
                is_fragile=False,
            )
        )

    # 提取ID
    if "id" in element_data and element_data["id"]:
        selector_str = f'#{element_data["id"]}'
        selector_type, is_fragile = evaluate_selector_stability(selector_str)
        selectors.append(
            Selector(
                selector=selector_str,
                priority=SelectorPriority.get_priority(selector_type),
                type=selector_type,
                element_description=element_description,
                is_fragile=is_fragile,
            )
        )

    # 提取类名（选择最稳定的）
    if "class" in element_data and element_data["class"]:
        classes = element_data["class"] if isinstance(element_data["class"], list) else element_data["class"].split()
        for cls in classes:
            if cls:  # 跳过空类名
                selector_str = f".{cls}"
                selector_type, is_fragile = evaluate_selector_stability(selector_str)
                selectors.append(
                    Selector(
                        selector=selector_str,
                        priority=SelectorPriority.get_priority(selector_type),
                        type=selector_type,
                        element_description=element_description,
                        is_fragile=is_fragile,
                    )
                )

    # 按优先级排序
    return sort_selectors_by_priority(selectors)
