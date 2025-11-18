"""
JavaScript和Markdown模板系统

提供配方脚本和知识文档的模板渲染功能。
"""

from datetime import datetime
from typing import Dict, List, Optional

from .models import ExplorationStep, Selector, UpdateRecord


class JavaScriptTemplate:
    """JavaScript配方脚本模板"""

    @staticmethod
    def render_wait_for_element(selector: str, timeout_ms: int = 5000) -> str:
        """生成等待元素出现的JavaScript代码"""
        return f"""
// 等待元素加载
function waitForElement(selector, timeout = {timeout_ms}) {{
  return new Promise((resolve, reject) => {{
    const startTime = Date.now();
    const checkInterval = setInterval(() => {{
      const element = document.querySelector(selector);
      if (element) {{
        clearInterval(checkInterval);
        resolve(element);
      }} else if (Date.now() - startTime > timeout) {{
        clearInterval(checkInterval);
        reject(new Error(`元素未在${{timeout}}ms内加载: ${{selector}}`));
      }}
    }}, 100);
  }});
}}
""".strip()

    @staticmethod
    def render_click_action(selector: str, element_description: str) -> str:
        """生成点击操作的JavaScript代码"""
        return f"""
// 点击: {element_description}
const clickElement = await waitForElement('{selector}');
clickElement.click();
await new Promise(resolve => setTimeout(resolve, 500)); // 等待操作生效
""".strip()

    @staticmethod
    def render_extract_content(selector: str, element_description: str) -> str:
        """生成内容提取的JavaScript代码"""
        return f"""
// 提取: {element_description}
const contentElement = await waitForElement('{selector}');
const extractedContent = contentElement.innerText || contentElement.textContent;
""".strip()

    @staticmethod
    def render_complete_recipe(
        recipe_name: str,
        description: str,
        steps_code: List[str],
        result_extraction: str,
    ) -> str:
        """
        生成完整的配方脚本

        Args:
            recipe_name: 配方名称
            description: 配方描述
            steps_code: 步骤代码列表
            result_extraction: 结果提取代码

        Returns:
            完整的JavaScript代码
        """
        steps_joined = "\n\n".join(steps_code)

        return f'''
/**
 * 配方: {recipe_name}
 * 描述: {description}
 * 生成时间: {datetime.now().isoformat()}
 */

(async function() {{
  try {{
    {JavaScriptTemplate.render_wait_for_element("body")}

    {steps_joined}

    {result_extraction}

    // 返回成功结果
    return {{
      success: true,
      data: result,
      timestamp: new Date().toISOString()
    }};

  }} catch (error) {{
    // 返回错误信息
    return {{
      success: false,
      error: error.message,
      stack: error.stack,
      timestamp: new Date().toISOString()
    }};
  }}
}})();
'''.strip()


class MarkdownTemplate:
    """Markdown知识文档模板"""

    @staticmethod
    def render_section_description(description: str, user_description: str) -> str:
        """渲染功能描述章节"""
        return f"""## 功能描述

{description}

**用户需求**: {user_description}
""".strip()

    @staticmethod
    def render_section_usage(
        recipe_name: str, prerequisites: Optional[List[str]] = None
    ) -> str:
        """渲染使用方法章节"""
        prereq_steps = ""
        if prerequisites:
            prereq_steps = "\n".join(
                [f"# {i+1}. {pre}" for i, pre in enumerate(prerequisites)]
            )
            prereq_steps = f"\n{prereq_steps}\n"

        return f'''## 使用方法

```bash{prereq_steps}
# 执行配方
uv run auvima exec-js recipes/{recipe_name}.js
```
'''.strip()

    @staticmethod
    def render_section_prerequisites(prerequisites: List[str]) -> str:
        """渲染前置条件章节（checklist格式）"""
        if not prerequisites:
            prerequisites = ["Chrome已通过CDP启动（端口9222）"]

        checklist = "\n".join([f"- [ ] {pre}" for pre in prerequisites])

        return f"""## 前置条件

{checklist}
""".strip()

    @staticmethod
    def render_section_output(
        example_success: Optional[Dict] = None,
        example_failure: Optional[Dict] = None,
    ) -> str:
        """渲染预期输出章节"""
        if example_success is None:
            example_success = {
                "success": True,
                "data": {"message": "操作成功"},
                "timestamp": "2025-11-18T10:30:00Z",
            }

        if example_failure is None:
            example_failure = {
                "success": False,
                "error": "无法定位元素，页面结构可能已变化",
                "timestamp": "2025-11-18T10:30:00Z",
            }

        import json

        return f'''## 预期输出

**成功情况**:
```json
{json.dumps(example_success, indent=2, ensure_ascii=False)}
```

**失败情况**:
```json
{json.dumps(example_failure, indent=2, ensure_ascii=False)}
```
'''.strip()

    @staticmethod
    def render_section_notes(fragile_selectors: List[Selector]) -> str:
        """渲染注意事项章节（标注脆弱选择器）"""
        notes = []

        if fragile_selectors:
            notes.append("**脆弱选择器警告**:")
            for sel in fragile_selectors:
                notes.append(
                    f"- ⚠️ `{sel.selector}` ({sel.element_description}) - "
                    f"如果网站改版失效，请运行 `/auvima.recipe update`"
                )
            notes.append("")

        notes.extend(
            [
                "**已知限制**:",
                "- 此配方依赖当前页面结构，网站改版可能导致失效",
                "- 动态加载内容可能需要额外等待时间",
            ]
        )

        return "## 注意事项\n\n" + "\n".join(notes)

    @staticmethod
    def render_section_history(
        created_at: datetime, update_records: Optional[List[UpdateRecord]] = None
    ) -> str:
        """渲染更新历史章节"""
        lines = ["## 更新历史", ""]
        lines.append(f"### {created_at.strftime('%Y-%m-%d')}（初始版本）")
        lines.append("- 创建配方脚本")
        lines.append("")

        if update_records:
            for record in update_records:
                lines.append(f"### {record.date.strftime('%Y-%m-%d')}")
                lines.append(f"- **原因**: {record.reason}")
                lines.append(f"- **变更**: {record.changes}")
                if record.tested_on:
                    lines.append(f"- **测试**: {record.tested_on}")
                lines.append("")

        return "\n".join(lines).strip()

    @staticmethod
    def render_complete_document(
        recipe_name: str,
        description: str,
        user_description: str,
        prerequisites: List[str],
        fragile_selectors: List[Selector],
        created_at: datetime,
        update_records: Optional[List[UpdateRecord]] = None,
    ) -> str:
        """
        生成完整的知识文档

        Args:
            recipe_name: 配方名称
            description: 配方描述
            user_description: 用户原始需求描述
            prerequisites: 前置条件列表
            fragile_selectors: 脆弱选择器列表
            created_at: 创建时间
            update_records: 更新记录列表

        Returns:
            完整的Markdown文档
        """
        sections = [
            f"# {recipe_name}",
            "",
            MarkdownTemplate.render_section_description(description, user_description),
            "",
            MarkdownTemplate.render_section_usage(recipe_name, prerequisites[:2] if len(prerequisites) > 2 else None),
            "",
            MarkdownTemplate.render_section_prerequisites(prerequisites),
            "",
            MarkdownTemplate.render_section_output(),
            "",
            MarkdownTemplate.render_section_notes(fragile_selectors),
            "",
            MarkdownTemplate.render_section_history(created_at, update_records),
        ]

        return "\n".join(sections)
