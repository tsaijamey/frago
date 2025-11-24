# Research: Recipe 系统架构重构（AI-First）

**Feature**: Recipe 系统架构重构
**Branch**: 004-recipe-architecture-refactor
**Date**: 2025-11-20
**核心理念**: AI Agent（Claude Code）是主要使用者

## 研究概述

本文档记录 AI-first 架构重构的技术决策。所有设计以"**AI 可理解、可调度**"为核心原则。

---

## 1. AI 元数据字段设计

### 决策
Recipe 元数据扩展以下 AI 可理解字段：
- `description` (string, 必需): 简短功能描述，<200 字符
- `use_cases` (array, 必需): 适用场景列表，如 `["提取网页数据", "批量处理"]`
- `tags` (array, 可选): 语义标签，如 `["web-scraping", "upwork"]`
- `output_targets` (array, 必需): 支持的输出去向，枚举值 `[stdout, file, clipboard]`

### 理由
1. **AI 选择能力**: `description` 和 `use_cases` 让 AI 能通过语义理解判断 Recipe 是否适用于当前任务
2. **输出规划**: `output_targets` 让 AI 知道如何处理结果（保存文件 vs 快速查看 vs 传递给下个步骤）
3. **可发现性**: `tags` 支持未来的语义搜索和分类

### YAML 示例
```yaml
---
name: upwork_extract_job_details
type: atomic
runtime: chrome-js
description: "从 Upwork 职位详情页提取完整信息并格式化为 Markdown"
use_cases:
  - "分析市场上的职位需求"
  - "批量收集职位信息"
  - "为投标准备数据"
tags:
  - web-scraping
  - upwork
  - job-market
output_targets:
  - stdout
  - file
inputs:
  url:
    type: string
    required: true
    description: "Upwork 职位详情页 URL"
outputs:
  type: object
  properties:
    title: {type: string}
    description: {type: string}
    skills: {type: array, items: {type: string}}
version: 1.0.0
---
```

---

## 2. CLI 输出格式（AI 友好）

### 决策
所有 `recipe` 命令必须支持 `--format json` 选项，输出结构化 JSON。

### 理由
1. **AI 解析**: JSON 是 AI 最容易解析的格式，避免正则表达式解析表格
2. **完整信息**: JSON 可以包含所有元数据字段，表格输出会丢失细节
3. **编程接口**: JSON 输出也方便脚本化使用

### 命令示例
```bash
# AI 调用方式
$ uv run frago recipe list --format json
[
  {
    "name": "upwork_extract_job_details",
    "type": "atomic",
    "runtime": "chrome-js",
    "description": "从 Upwork 职位详情页提取完整信息",
    "use_cases": ["分析市场", "批量收集"],
    "tags": ["web-scraping", "upwork"],
    "output_targets": ["stdout", "file"],
    "source": "Example"
  }
]
```

---

## 3. 输出去向处理（OutputHandler）

### 决策
新增 `output_handler.py` 模块，统一处理三种输出去向。

### 理由
1. **AI 决策**: AI 根据任务类型选择输出方式（批量任务→文件，快速查看→stdout，立即使用→剪贴板）
2. **一致性**: 统一的输出处理逻辑，避免每个 Recipe 自己实现
3. **可扩展**: 未来可支持更多输出目标（如数据库、API 推送）

### 架构设计
```python
class OutputHandler:
    @staticmethod
    def handle(data: dict, target: str, options: dict) -> None:
        """
        处理 Recipe 输出

        Args:
            data: Recipe 返回的 JSON 数据
            target: 输出目标 ('stdout' | 'file' | 'clipboard')
            options: 目标特定选项 (如 file 需要 'path')
        """
        if target == 'stdout':
            print(json.dumps(data, ensure_ascii=False, indent=2))
        elif target == 'file':
            path = options['path']
            Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2))
        elif target == 'clipboard':
            import pyperclip
            pyperclip.copy(json.dumps(data))
```

### CLI 集成
```bash
# stdout（默认）
$ uv run frago recipe run youtube_extract_transcript --params '{...}'

# 文件
$ uv run frago recipe run youtube_extract_transcript --params '{...}' --output-file transcript.json

# 剪贴板
$ uv run frago recipe run youtube_extract_transcript --params '{...}' --output-clipboard
```

---

## 4. AI 生成 Workflow 的实现

### 决策
扩展 `/frago.recipe` 命令，支持 `create workflow` 子命令，AI 根据自然语言生成 Python Workflow 脚本。

### 理由
1. **一致性**: Recipe 创建流程统一由 AI 驱动（无论原子还是编排）
2. **降低门槛**: 用户无需学习 Python 编程，只需描述意图
3. **最佳实践**: AI 生成的 Workflow 包含错误处理、循环、日志等最佳实践

### 命令示例
```bash
# AI 调用 /frago.recipe
/frago.recipe create workflow "批量提取 10 个 Upwork 职位并保存为 CSV"
```

### AI 生成的 Workflow 示例
```python
#!/usr/bin/env python3
"""
Workflow: 批量提取 Upwork 职位
生成时间: 2025-11-20
由 Claude Code 自动生成
"""
import sys
import json
from frago.recipes import RecipeRunner

def main():
    params = json.loads(sys.argv[1] if len(sys.argv) > 1 else '{}')
    urls = params.get('urls', [])

    if not urls:
        print(json.dumps({"error": "Missing 'urls' parameter"}), file=sys.stderr)
        sys.exit(1)

    runner = RecipeRunner()
    results = []

    for i, url in enumerate(urls[:10], 1):  # 限制 10 个
        try:
            print(f"处理第 {i}/10 个职位...", file=sys.stderr)
            result = runner.run('upwork_extract_job_details', {'url': url})
            results.append(result['data'])
        except Exception as e:
            print(f"错误: {url} - {e}", file=sys.stderr)
            results.append({"url": url, "error": str(e)})

    # 转换为 CSV 格式（简化）
    output = {"success": True, "count": len(results), "jobs": results}
    print(json.dumps(output, ensure_ascii=False))

if __name__ == '__main__':
    main()
```

---

## 5. Recipe 发现机制（AI 场景）

### 决策
AI 通过以下流程发现和选择 Recipe：
1. `recipe list --format json` 获取所有 Recipe 元数据
2. 基于 `description` 和 `use_cases` 字段进行语义匹配
3. 检查 `output_targets` 是否满足任务需求
4. 选择最合适的 Recipe 并执行

### 示例场景
```
用户: "帮我提取这个 YouTube 视频的字幕并保存为文件"
↓
AI 思考过程:
1. 调用: uv run frago recipe list --format json
2. 分析元数据, 发现 youtube_extract_video_transcript
   - description: "提取 YouTube 视频字幕"
   - use_cases: ["获取字幕用于翻译", "制作字幕文件"]
   - output_targets: ["stdout", "file"]  ← 支持文件输出
3. 决策: 使用该 Recipe, 输出到文件
4. 执行: uv run frago recipe run youtube_extract_video_transcript \
           --params '{"url": "..."}' \
           --output-file transcript.txt
```

---

## 6. 错误处理（AI 可理解）

### 决策
Recipe 执行失败时，返回统一的 JSON 错误格式：
```json
{
  "success": false,
  "error": {
    "type": "RecipeExecutionError",
    "message": "Recipe 'upwork_extract_job' 执行失败",
    "recipe_name": "upwork_extract_job",
    "runtime": "chrome-js",
    "exit_code": 1,
    "stdout": "...",
    "stderr": "Error: Element not found: .job-title"
  }
}
```

### 理由
1. **AI 理解**: 结构化错误让 AI 知道失败原因（选择器错误 vs 网络问题 vs 参数错误）
2. **自动应对**: AI 可以根据错误类型采取策略（重试 vs 调整参数 vs 报告用户）
3. **可调试**: 包含 stdout/stderr 原始输出，便于排查

---

## 7. 向后兼容策略

### 决策
保留现有 `uv run frago exec-js` 命令，新系统作为独立功能。

### 理由
1. **零破坏**: 现有 Recipe 和工作流无需修改
2. **渐进迁移**: 可以逐步将旧 Recipe 迁移到新架构
3. **清晰分离**: `exec-js` 专注于单次执行，`recipe` 专注于管理和编排

### 迁移路径
```bash
# 旧方式（继续支持）
uv run frago exec-js recipes/upwork_extract_job.js

# 新方式（推荐，AI 使用）
uv run frago recipe run upwork_extract_job --params '{...}'
```

---

## 8. 测试策略（AI 场景优先）

### 决策
新增 `test_ai_workflow.py` 集成测试，模拟 AI Agent 使用场景。

### 测试用例
```python
def test_ai_discovers_and_runs_recipe():
    """模拟 AI 发现并执行 Recipe 的完整流程"""
    # 1. AI 查询可用 Recipe
    result = subprocess.run(
        ['uv', 'run', 'frago', 'recipe', 'list', '--format', 'json'],
        capture_output=True, text=True
    )
    recipes = json.loads(result.stdout)

    # 2. AI 选择合适的 Recipe（基于语义）
    target_recipe = next(
        r for r in recipes
        if 'youtube' in r['description'].lower()
    )

    # 3. AI 执行 Recipe
    result = subprocess.run(
        ['uv', 'run', 'frago', 'recipe', 'run', target_recipe['name'],
         '--params', '{"url": "..."}'],
        capture_output=True, text=True
    )

    # 4. AI 解析结果
    output = json.loads(result.stdout)
    assert output['success'] is True
    assert 'transcript' in output['data']
```

---

## 研究总结

所有技术决策以 **AI-first** 为核心：
1. **元数据驱动**: AI 通过语义字段理解 Recipe 能力
2. **结构化输出**: JSON 格式便于 AI 解析和决策
3. **输出形态声明**: AI 可根据任务选择合适的输出方式
4. **AI 生成 Workflow**: 降低编程门槛，统一创建流程
5. **错误可理解**: 结构化错误让 AI 能自动应对

下一步: 进入 Phase 1，生成数据模型和 CLI 契约（AI-first 视角）。
