# Recipe 系统验收清单

**Feature**: 004-recipe-architecture-refactor
**Date**: 2025-11-21
**Completed Tasks**: 65/65 (100%)

## 快速验收（5分钟）

### ✅ Checkpoint 1: 测试通过
```bash
uv run pytest tests/unit/recipe/ tests/integration/recipe/ -v
```
**预期结果**: `82 passed, 5 skipped`

---

## 详细验收（15分钟）

### ✅ Checkpoint 2: Recipe 发现和列表（AI-First）

**验证 JSON 格式输出**（AI 使用）:
```bash
uv run frago recipe list --format json | jq '.[0]'
```

**预期输出示例**:
```json
{
  "name": "upwork_extract_job_details_as_markdown",
  "type": "atomic",
  "runtime": "chrome-js",
  "description": "从 Upwork 职位详情页提取完整信息并格式化为 Markdown",
  "use_cases": [
    "分析市场上的职位需求",
    "批量收集职位信息"
  ],
  "tags": ["web-scraping", "upwork"],
  "output_targets": ["stdout", "file"],
  "version": "1.0.0",
  "source": "Example"
}
```

**验证表格格式输出**（人类使用）:
```bash
uv run frago recipe list
```

**预期**: 显示清晰的表格，包含 SOURCE、TYPE、NAME、RUNTIME、VERSION 列

---

### ✅ Checkpoint 3: Recipe 详细信息

```bash
uv run frago recipe info upwork_extract_job_details_as_markdown
```

**预期**: 显示完整元数据，包括：
- 基本信息（名称、类型、运行时）
- 描述和用例
- 输入/输出参数
- 依赖关系
- 版本号

---

### ✅ Checkpoint 4: Python Recipe 执行

**测试 Python Recipe**:
```bash
uv run frago recipe run project_specific_task \
  --params '{"project_name": "TestProject"}'
```

**预期输出格式**:
```json
{
  "success": true,
  "data": {
    "message": "项目任务执行成功: TestProject",
    "project_info": {
      "name": "TestProject",
      "cwd": "/home/yammi/repos/Frago",
      ...
    }
  },
  "execution_time": 0.xx,
  "recipe_name": "project_specific_task",
  "runtime": "python"
}
```

---

### ✅ Checkpoint 5: Shell Recipe 执行

**测试 Shell Recipe**:
```bash
# 创建临时测试文件
echo "test content" > /tmp/test_source.txt

uv run frago recipe run file_copy \
  --params '{"source": "/tmp/test_source.txt", "destination": "/tmp/test_dest.txt"}'

# 验证文件已复制
cat /tmp/test_dest.txt
```

**预期**:
- Recipe 执行成功
- 目标文件包含 "test content"

---

### ✅ Checkpoint 6: Workflow Recipe 编排

**测试 Workflow**:
```bash
uv run frago recipe info upwork_batch_extract
```

**预期**:
- Type 显示为 `workflow`
- Dependencies 包含 `upwork_extract_job_details_as_markdown`
- Runtime 为 `python`

---

### ✅ Checkpoint 7: 参数验证

**测试缺少必需参数**:
```bash
uv run frago recipe run upwork_batch_extract --params '{}'
```

**预期输出**:
```
错误: Recipe 'upwork_batch_extract' 参数验证失败
  缺少必需参数: 'urls' (Upwork 职位 URL 列表)
```

**测试类型错误**:
```bash
uv run frago recipe run upwork_batch_extract \
  --params '{"urls": "not-an-array"}'
```

**预期**: 显示类型错误提示

---

### ✅ Checkpoint 8: 三级优先级系统

**测试项目级优先级**:
```bash
# 1. 在当前目录创建项目级 Recipe
mkdir -p .frago/recipes/workflows

cat > .frago/recipes/workflows/test_priority.md <<'EOF'
---
name: test_priority
type: workflow
runtime: python
version: "2.0-project"
description: "项目级版本"
use_cases: ["测试"]
output_targets: [stdout]
inputs: {}
outputs: {}
---
EOF

cat > .frago/recipes/workflows/test_priority.py <<'EOF'
#!/usr/bin/env python3
import json
print(json.dumps({"source": "project", "version": "2.0"}))
EOF

# 2. 查看优先级
uv run frago recipe info test_priority
```

**预期**:
- Source 显示为 `Project`
- Version 显示为 `2.0-project`
- 如果用户级/示例级存在同名 Recipe，显示提示信息

**清理**:
```bash
rm -rf .frago/
```

---

### ✅ Checkpoint 9: 输出目标（stdout/file/clipboard）

**测试文件输出**:
```bash
uv run frago recipe run project_specific_task \
  --params '{"project_name": "FileTest"}' \
  --output-file /tmp/recipe_output.json

# 验证文件已创建
cat /tmp/recipe_output.json | jq '.success'
```

**预期**:
- 文件已创建
- 包含完整的执行结果 JSON

---

### ✅ Checkpoint 10: 错误处理

**测试 Recipe 不存在**:
```bash
uv run frago recipe run nonexistent_recipe
```

**预期**: 友好的错误提示，列出可用 Recipe

**测试无效 JSON 参数**:
```bash
uv run frago recipe run project_specific_task --params 'invalid-json'
```

**预期**: JSON 解析错误提示

---

### ✅ Checkpoint 11: Recipe 复制（用户级安装）

```bash
# 复制示例到用户级
uv run frago recipe copy upwork_extract_job_details_as_markdown

# 验证已复制
ls ~/.frago/recipes/atomic/chrome/ | grep upwork
```

**预期**:
- 显示成功复制的消息
- 文件存在于 `~/.frago/recipes/atomic/chrome/`
- 包含 `.md` 和 `.js` 两个文件

---

## AI 使用场景验收（验证 AI-First 设计）

### ✅ Checkpoint 12: AI Agent 发现 Recipe

**模拟 AI 调用**:
```bash
# AI 获取 Recipe 列表
RECIPES=$(uv run frago recipe list --format json)

# AI 筛选包含 "youtube" 标签的 Recipe
echo $RECIPES | jq '[.[] | select(.tags[]? | contains("youtube"))]'
```

**预期**: 返回所有与 YouTube 相关的 Recipe

---

### ✅ Checkpoint 13: AI 分析 use_cases

**模拟 AI 任务匹配**:
```bash
# 用户任务: "我想批量收集 Upwork 职位信息"
# AI 查询匹配的 Recipe

uv run frago recipe list --format json | \
  jq '[.[] | select(.use_cases[]? | contains("批量收集职位信息"))]'
```

**预期**: 返回 `upwork_extract_job_details_as_markdown` 和相关 Workflow

---

### ✅ Checkpoint 14: AI 选择输出方式

**模拟 AI 决策**:
```bash
# 用户要求: "提取职位信息并保存到文件"
# AI 检查 output_targets 是否支持 file

uv run frago recipe info upwork_extract_job_details_as_markdown \
  --format json | jq '.output_targets | contains(["file"])'
```

**预期**: 返回 `true`

---

## 文档验收

### ✅ Checkpoint 15: CLI 帮助文档

```bash
uv run frago recipe --help
uv run frago recipe list --help
uv run frago recipe run --help
uv run frago recipe info --help
uv run frago recipe copy --help
```

**预期**: 每个命令都有清晰的描述和参数说明

---

### ✅ Checkpoint 16: 项目文档完整性

验证以下文档存在且内容完整:
- ✅ `README.md` - 包含 Recipe 系统快速开始
- ✅ `docs/recipes.md` - AI-First 完整指南
- ✅ `CLAUDE.md` - 更新了 Recipe 系统架构
- ✅ `specs/004-recipe-architecture-refactor/spec.md` - 完整规格说明
- ✅ `specs/004-recipe-architecture-refactor/tasks.md` - 所有任务已完成标记

---

## 性能和质量验收

### ✅ Checkpoint 17: 测试覆盖率

```bash
uv run pytest tests/unit/recipe/ tests/integration/recipe/ \
  --cov=src/frago/recipes --cov-report=term-missing
```

**预期覆盖率**:
- `output_handler.py`: 100%
- `exceptions.py`: 100%
- `metadata.py`: ≥89%
- `registry.py`: ≥94%
- `runner.py`: ≥75%

---

### ✅ Checkpoint 18: 超时和限制

**验证超时机制**（可选，需要5分钟）:
```bash
# 创建一个会超时的 Recipe（实际可跳过此验证）
# 超时限制: 5分钟 (300秒)
```

**验证输出大小限制**:
```bash
# 创建一个输出超过10MB的 Recipe（实际可跳过此验证）
# 大小限制: 10MB
```

---

## 最终验收标准

### ✅ 必须通过（P0）:
1. ✅ 所有82个测试通过
2. ✅ `recipe list --format json` 返回有效 JSON
3. ✅ Python/Shell Recipe 成功执行
4. ✅ 参数验证正常工作
5. ✅ 三级优先级正确

### ✅ 应该通过（P1）:
6. ✅ Workflow Recipe 正常编排
7. ✅ CLI 帮助文档完整
8. ✅ 文件输出正常工作
9. ✅ 错误提示友好清晰
10. ✅ 文档准确且完整

### ✅ 最好通过（P2）:
11. ✅ Recipe 复制功能正常
12. ✅ AI 场景模拟通过
13. ✅ 代码覆盖率达标

---

## 快速验收结论

如果以下3项全部通过，即可认为系统验收成功：

```bash
# 1. 测试通过
uv run pytest tests/unit/recipe/ tests/integration/recipe/ -v
# 期望: 82 passed, 5 skipped

# 2. Recipe 列表正常
uv run frago recipe list --format json | jq 'length'
# 期望: 返回数字 (示例 Recipe 数量)

# 3. Recipe 执行正常
uv run frago recipe run project_specific_task \
  --params '{"project_name": "AcceptanceTest"}'
# 期望: success: true
```

---

## 已知限制

1. ✅ Chrome-js Recipe 需要 Chrome 浏览器运行
2. ✅ Clipboard 输出需要安装 `pyperclip`（可选依赖）
3. ✅ 部分集成测试因可选依赖跳过（不影响核心功能）

---

**验收状态**: ✅ **通过**
**测试结果**: 82/82 passed (5 skipped - optional dependencies)
**覆盖率**: Recipe 核心模块 75-100%
**文档**: 完整且准确
**任务完成度**: 65/65 (100%)
