# Recipe 系统指南（AI-First）

## 概述

本指南展示 **Claude Code AI Agent** 如何使用新的 Recipe 系统。设计理念：AI 是主要使用者，人类可以手动执行（次要场景）。

**AI 核心能力**:
1. 通过元数据发现和选择合适的 Recipe
2. 根据任务需求选择输出去向（stdout/file/clipboard）
3. 自动生成编排 Workflow Recipe
4. 理解结构化错误并采取应对策略

---

## AI 使用场景快速开始

### 场景 1: AI 发现并执行 Recipe

**用户意图**: "帮我提取这个 YouTube 视频的字幕并保存为文件"

**AI 执行流程**:

#### Step 1: 查询可用 Recipe（JSON 格式）

```bash
# AI 调用 Bash 工具
uv run frago recipe list --format json
```

**AI 接收到的 JSON 响应**:
```json
[
  {
    "name": "youtube_extract_video_transcript",
    "type": "atomic",
    "runtime": "chrome-js",
    "description": "从 YouTube 视频页面提取完整字幕内容",
    "use_cases": [
      "获取字幕用于翻译",
      "制作字幕文件",
      "分析视频内容"
    ],
    "tags": ["web-scraping", "youtube", "transcript"],
    "output_targets": ["stdout", "file"],
    "version": "1.2.0",
    "source": "Example"
  },
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
]
```

#### Step 2: AI 分析并选择 Recipe

AI 思考过程:
1. 用户需要提取 YouTube 字幕 → 匹配 `youtube_extract_video_transcript`
2. 检查 `use_cases`: 包含 "获取字幕用于翻译" ✓
3. 检查 `output_targets`: 支持 `file` ✓
4. 决策：使用该 Recipe，输出到文件

#### Step 3: AI 执行 Recipe

```bash
# AI 调用 Bash 工具
uv run frago recipe run youtube_extract_video_transcript \
  --params '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}' \
  --output-file transcript.json
```

**执行成功响应**:
```json
{
  "success": true,
  "data": {
    "title": "Rick Astley - Never Gonna Give You Up",
    "transcript": "We're no strangers to love...",
    "language": "en",
    "duration": 213
  },
  "execution_time": 3.21,
  "recipe_name": "youtube_extract_video_transcript",
  "runtime": "chrome-js"
}
```

**同时文件已保存**: `transcript.json`

---

### 场景 2: AI 处理错误并重试

**执行失败响应**:
```json
{
  "success": false,
  "error": {
    "type": "RecipeExecutionError",
    "message": "Recipe 'youtube_extract_video_transcript' 执行失败",
    "recipe_name": "youtube_extract_video_transcript",
    "runtime": "chrome-js",
    "exit_code": 1,
    "stdout": "Navigated to https://youtube.com/watch?v=...",
    "stderr": "Error: Element not found: .transcript-button"
  },
  "execution_time": 1.5,
  "recipe_name": "youtube_extract_video_transcript",
  "runtime": "chrome-js"
}
```

**AI 分析错误**:
1. `error.type`: RecipeExecutionError → 执行失败
2. `error.stderr`: "Element not found: .transcript-button" → 页面结构变化或无字幕
3. **AI 策略**: 向用户报告 "该视频可能没有字幕或 YouTube 页面结构已更新"

---

### 场景 3: AI 自动生成 Workflow Recipe

**用户意图**: "批量提取 10 个 Upwork 职位并保存为 JSON 文件"

**AI 执行流程**:

#### Step 1: AI 调用 `/frago.recipe` 命令

```
/frago.recipe create workflow "批量提取 10 个 Upwork 职位并保存为 JSON"
```

#### Step 2: AI 自动生成 Workflow 脚本

AI 生成的文件: `~/.frago/recipes/workflows/upwork_batch_extract.py`

```python
#!/usr/bin/env python3
"""
Workflow: 批量提取 Upwork 职位
生成时间: 2025-11-20
由 Claude Code 自动生成
"""
import sys, json
from frago.recipes import RecipeRunner

def main():
    params = json.loads(sys.argv[1] if len(sys.argv) > 1 else '{}')
    urls = params.get('urls', [])

    if not urls:
        print(json.dumps({"error": "Missing 'urls' parameter"}), file=sys.stderr)
        sys.exit(1)

    runner = RecipeRunner()
    results = []

    for i, url in enumerate(urls[:10], 1):
        try:
            print(f"处理第 {i}/10 个职位...", file=sys.stderr)
            result = runner.run('upwork_extract_job_details_as_markdown', {'url': url})
            results.append(result['data'])
        except Exception as e:
            results.append({"url": url, "error": str(e)})

    print(json.dumps({"success": True, "jobs": results}, ensure_ascii=False))

if __name__ == '__main__':
    main()
```

#### Step 3: AI 生成元数据文件

`~/.frago/recipes/workflows/upwork_batch_extract.md`:

```yaml
---
name: upwork_batch_extract
type: workflow
runtime: python
description: "批量提取多个 Upwork 职位并保存为 JSON"
use_cases:
  - "批量收集职位数据"
  - "市场分析"
tags:
  - upwork
  - batch-processing
output_targets:
  - stdout
  - file
dependencies:
  - upwork_extract_job_details_as_markdown
version: 1.0.0
---
```

#### Step 4: AI 执行 Workflow

```bash
uv run frago recipe run upwork_batch_extract \
  --params '{"urls": ["https://...", "https://...", ...]}' \
  --output-file jobs.json
```

---

## 人类手动使用（次要场景）

### 场景：创建一个简单的剪贴板读取 Recipe

#### 1. 创建脚本文件

```bash
# 创建 Python 脚本
cat > ~/.frago/recipes/atomic/system/clipboard_read.py <<'EOF'
#!/usr/bin/env python3
import sys
import json
import subprocess

# 从命令行参数读取输入
params = json.loads(sys.argv[1] if len(sys.argv) > 1 else '{}')

# 读取剪贴板内容（使用 xclip）
result = subprocess.run(['xclip', '-selection', 'clipboard', '-o'],
                        capture_output=True, text=True, check=True)

# 输出 JSON 结果到 stdout
output = {
    "content": result.stdout,
    "length": len(result.stdout)
}
print(json.dumps(output, ensure_ascii=False))
EOF

# 添加执行权限（Python 脚本不强制，但推荐）
chmod +x ~/.frago/recipes/atomic/system/clipboard_read.py
```

#### 2. 创建元数据文件

```bash
cat > ~/.frago/recipes/atomic/system/clipboard_read.md <<'EOF'
---
name: clipboard_read
type: atomic
runtime: python
inputs: {}
outputs:
  content: string
  length: number
version: 1.0.0
dependencies: []
description: "读取系统剪贴板内容"
---

# 剪贴板读取 Recipe

## 功能描述

读取 Linux 系统剪贴板的当前内容（使用 xclip 工具）。

## 前置条件

- 安装 xclip: `sudo apt install xclip`
- 运行在 X11 环境（Wayland 需调整）

## 使用方法

```bash
uv run frago recipe run clipboard_read
```

## 预期输出

```json
{
  "success": true,
  "data": {
    "content": "复制的文本内容",
    "length": 10
  }
}
```

## 注意事项

- 如剪贴板为空，`content` 为空字符串
- 仅支持文本内容，不支持图片等二进制数据
EOF
```

#### 3. 验证并执行

```bash
# 查看 Recipe 信息
uv run frago recipe info clipboard_read

# 执行 Recipe
uv run frago recipe run clipboard_read
```

---

## 创建编排 Recipe (Workflow)

### 场景：批量提取多个 YouTube 视频字幕

#### 1. 创建 Workflow 脚本

```bash
cat > ~/.frago/recipes/workflows/youtube_batch_extract.py <<'EOF'
#!/usr/bin/env python3
import sys
import json
from pathlib import Path

# 导入 RecipeRunner（假设已实现）
# from frago.recipes import RecipeRunner

def main():
    # 从命令行参数读取输入
    params = json.loads(sys.argv[1] if len(sys.argv) > 1 else '{}')
    video_urls = params.get('urls', [])

    if not video_urls:
        print(json.dumps({"error": "Missing 'urls' parameter"}), file=sys.stderr)
        sys.exit(1)

    # 初始化 RecipeRunner
    # runner = RecipeRunner()

    results = []
    for url in video_urls:
        try:
            # 调用原子 Recipe
            # result = runner.run('youtube_extract_video_transcript', {'url': url})
            # results.append(result)

            # 临时模拟（实际实现后删除）
            results.append({
                "url": url,
                "title": f"Video from {url}",
                "transcript": "..."
            })
        except Exception as e:
            results.append({
                "url": url,
                "error": str(e)
            })

    # 输出 JSON 结果
    output = {
        "success": True,
        "videos": results,
        "total": len(video_urls),
        "success_count": sum(1 for r in results if 'error' not in r)
    }
    print(json.dumps(output, ensure_ascii=False))

if __name__ == '__main__':
    main()
EOF

chmod +x ~/.frago/recipes/workflows/youtube_batch_extract.py
```

#### 2. 创建元数据文件

```bash
cat > ~/.frago/recipes/workflows/youtube_batch_extract.md <<'EOF'
---
name: youtube_batch_extract
type: workflow
runtime: python
inputs:
  urls:
    type: array
    required: true
    description: "YouTube 视频 URL 列表"
outputs:
  videos: array
  total: number
  success_count: number
version: 1.0.0
dependencies:
  - youtube_extract_video_transcript
description: "批量提取多个 YouTube 视频字幕"
---

# YouTube 批量提取 Workflow

## 功能描述

批量调用 `youtube_extract_video_transcript` Recipe，提取多个 YouTube 视频的字幕。

## 使用方法

```bash
uv run frago recipe run youtube_batch_extract \
  --params '{"urls": ["https://youtube.com/watch?v=...", "..."]}'
```

## 预期输出

```json
{
  "success": true,
  "videos": [
    {"url": "...", "title": "...", "transcript": "..."},
    {"url": "...", "title": "...", "transcript": "..."}
  ],
  "total": 2,
  "success_count": 2
}
```
EOF
```

#### 3. 执行 Workflow

```bash
uv run frago recipe run youtube_batch_extract \
  --params '{
    "urls": [
      "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
      "https://www.youtube.com/watch?v=oHg5SJYRHA0"
    ]
  }'
```

---

## 项目级 Recipe（可选）

### 场景：在特定项目中使用项目专属 Recipe

#### 1. 在项目根目录创建 Recipe 目录

```bash
# 进入项目目录
cd /path/to/your/project

# 创建项目级 Recipe 目录
mkdir -p .frago/recipes/workflows

# 创建项目专属 Workflow
cat > .frago/recipes/workflows/project_specific_task.py <<'EOF'
#!/usr/bin/env python3
import sys, json

params = json.loads(sys.argv[1] if len(sys.argv) > 1 else '{}')

# 项目专属逻辑
output = {"message": "This is a project-specific workflow"}
print(json.dumps(output))
EOF

chmod +x .frago/recipes/workflows/project_specific_task.py
```

#### 2. 创建元数据文件

```bash
cat > .frago/recipes/workflows/project_specific_task.md <<'EOF'
---
name: project_specific_task
type: workflow
runtime: python
version: 1.0.0
description: "项目专属自动化任务"
---

# 项目专属任务

仅在当前项目中使用的 Workflow。
EOF
```

#### 3. 执行（自动优先使用项目级）

```bash
# 在项目目录执行
uv run frago recipe run project_specific_task

# 列出所有 Recipe（项目级会标注 [Project]）
uv run frago recipe list
```

**输出**:
```text
SOURCE   TYPE      NAME                       RUNTIME  VERSION
────────────────────────────────────────────────────────────────
Project  workflow  project_specific_task      python   1.0.0
User     atomic    clipboard_read             python   1.0.0
Example  atomic    youtube_extract_video...   chrome-js 1.2.0
```

---

## 常见任务

### 查看 Recipe 详细信息

```bash
uv run frago recipe info <recipe_name>
```

### 使用参数文件

```bash
# 创建参数文件
cat > params.json <<EOF
{
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
}
EOF

# 使用参数文件
uv run frago recipe run youtube_extract_video_transcript \
  --params-file params.json
```

### 将结果保存到文件

```bash
uv run frago recipe run youtube_extract_video_transcript \
  --params '{"url": "..."}' \
  --output-file result.json
```

### 调试 Recipe 执行

```bash
# 启用调试模式
uv run frago --debug recipe run <recipe_name> --params '{...}'
```

**输出**:
```text
[DEBUG] RecipeRegistry: 扫描路径 /home/user/.frago/recipes
[DEBUG] RecipeRegistry: 找到 5 个 Recipe
[DEBUG] RecipeRunner: 选择执行器 ChromeJSExecutor
[DEBUG] ChromeJSExecutor: 执行命令: frago chrome exec-js ...
[DEBUG] ChromeJSExecutor: 退出码: 0
{
  "success": true,
  "data": { ... }
}
```

---

## 最佳实践

### 1. Recipe 命名规范

- 使用小写字母、数字、下划线、连字符
- 原子 Recipe: `<platform>_<action>`（如 `youtube_extract_transcript`）
- Workflow Recipe: `<platform>_batch_<action>` 或 `<workflow_name>`

### 2. 参数验证

在 Recipe 脚本中验证必需参数：

```python
import sys, json

params = json.loads(sys.argv[1] if len(sys.argv) > 1 else '{}')

# 验证必需参数
if 'url' not in params:
    error = {"error": "Missing required parameter: url"}
    print(json.dumps(error), file=sys.stderr)
    sys.exit(1)
```

### 3. 错误处理

统一错误输出格式：

```python
try:
    # Recipe 逻辑
    result = do_something()
    print(json.dumps({"success": True, "data": result}))
except Exception as e:
    error = {
        "success": False,
        "error": {
            "type": type(e).__name__,
            "message": str(e)
        }
    }
    print(json.dumps(error), file=sys.stderr)
    sys.exit(1)
```

### 4. 版本管理

在元数据中使用语义化版本号：

```yaml
version: "1.0.0"  # 主版本.次版本.修订号
```

- 主版本：不兼容的 API 变更
- 次版本：新增功能（向后兼容）
- 修订号：Bug 修复

### 5. 依赖声明

在 Workflow 元数据中声明依赖：

```yaml
dependencies:
  - youtube_extract_video_transcript
  - clipboard_read
```

系统会在执行前检查依赖是否存在。

---

## 环境变量支持

Recipe 系统支持环境变量，用于管理 API 密钥、运行时配置等敏感或可变信息。

### 设计原则

- **完整继承系统环境**：Recipe 执行时继承所有系统环境变量（PATH、HOME 等）
- **三级配置优先级**：项目级 > 用户级 > 系统环境
- **声明式定义**：在 Recipe 元数据中声明所需环境变量
- **Workflow 上下文共享**：多个 Recipe 间可共享环境变量

### 在 Recipe 中声明环境变量

在元数据的 `env` 字段中声明所需的环境变量：

```yaml
---
name: openai_chat
type: atomic
runtime: python
description: "调用 OpenAI API 进行对话"
use_cases:
  - "AI 对话生成"
  - "文本处理"
output_targets:
  - stdout
env:
  OPENAI_API_KEY:
    required: true
    description: "OpenAI API 密钥"
  MODEL_NAME:
    required: false
    default: "gpt-4o"
    description: "使用的模型名称"
  MAX_TOKENS:
    required: false
    default: "1000"
    description: "最大 token 数"
version: "1.0.0"
---
```

**字段说明**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `required` | boolean | 是否必需（缺失时报错） |
| `default` | string | 默认值（未提供时使用） |
| `description` | string | 环境变量描述 |

### 配置环境变量

#### 方式一：配置文件（推荐）

创建 `.env` 文件存储环境变量：

**用户级配置**（适用于所有项目）：
```bash
# ~/.frago/.env
OPENAI_API_KEY=sk-your-api-key
DEEPSEEK_API_KEY=sk-your-deepseek-key
DEFAULT_MODEL=gpt-4o
```

**项目级配置**（仅当前项目）：
```bash
# .frago/.env
MODEL_NAME=gpt-4o-mini
MAX_TOKENS=2000
DEBUG=true
```

#### 方式二：CLI 参数覆盖

使用 `--env` 或 `-e` 参数在执行时覆盖：

```bash
# 单个环境变量
uv run frago recipe run openai_chat \
  --params '{"prompt": "Hello"}' \
  -e OPENAI_API_KEY=sk-xxx

# 多个环境变量
uv run frago recipe run openai_chat \
  --params '{"prompt": "Hello"}' \
  -e OPENAI_API_KEY=sk-xxx \
  -e MODEL_NAME=gpt-4 \
  -e MAX_TOKENS=500
```

#### 方式三：系统环境变量

直接在 shell 中导出：

```bash
export OPENAI_API_KEY=sk-your-api-key
uv run frago recipe run openai_chat --params '{"prompt": "Hello"}'
```

### 优先级规则

环境变量按以下优先级解析（高到低）：

```
┌─────────────────────────────────────────┐
│ 1. CLI --env 参数     (最高优先级)      │
├─────────────────────────────────────────┤
│ 2. Workflow 上下文    (跨 Recipe 共享)  │
├─────────────────────────────────────────┤
│ 3. 项目级 .frago/.env (当前项目)        │
├─────────────────────────────────────────┤
│ 4. 用户级 ~/.frago/.env (所有项目)      │
├─────────────────────────────────────────┤
│ 5. 系统环境变量       (os.environ)      │
├─────────────────────────────────────────┤
│ 6. Recipe 默认值      (metadata.env)    │
└─────────────────────────────────────────┘
```

### 在脚本中使用环境变量

**Python Recipe**：
```python
#!/usr/bin/env python3
import os
import sys
import json

# 环境变量已自动注入，直接使用 os.environ
api_key = os.environ.get('OPENAI_API_KEY')
model = os.environ.get('MODEL_NAME', 'gpt-4o')

if not api_key:
    print(json.dumps({"error": "OPENAI_API_KEY not set"}), file=sys.stderr)
    sys.exit(1)

# 使用环境变量...
result = {"model": model, "status": "ready"}
print(json.dumps(result))
```

**Shell Recipe**：
```bash
#!/bin/bash
# 环境变量已自动注入，直接使用
echo "Using model: $MODEL_NAME"
echo "API Key present: $([ -n \"$OPENAI_API_KEY\" ] && echo 'yes' || echo 'no')"

# 输出 JSON
cat <<EOF
{
  "model": "$MODEL_NAME",
  "configured": true
}
EOF
```

### Workflow 上下文共享

在 Workflow 中，多个 Recipe 可共享环境变量：

```python
#!/usr/bin/env python3
"""Workflow: 批量处理任务"""
import sys
import json
from frago.recipes import RecipeRunner, WorkflowContext

def main():
    params = json.loads(sys.argv[1] if len(sys.argv) > 1 else '{}')

    # 创建共享上下文
    context = WorkflowContext()

    # 设置共享的环境变量
    context.set("BATCH_ID", "batch_001")
    context.set("TOTAL_ITEMS", str(len(params.get('items', []))))

    runner = RecipeRunner()
    results = []

    for i, item in enumerate(params.get('items', [])):
        # 更新当前进度
        context.set("CURRENT_INDEX", str(i + 1))

        # 执行 Recipe，传递共享上下文
        result = runner.run(
            'process_item',
            params={'item': item},
            workflow_context=context
        )
        results.append(result['data'])

    print(json.dumps({"success": True, "results": results}))

if __name__ == '__main__':
    main()
```

被调用的 Recipe 可以通过 `os.environ` 访问这些共享变量：

```python
#!/usr/bin/env python3
"""Atomic Recipe: 处理单个项目"""
import os
import sys
import json

# 获取 Workflow 共享的上下文
batch_id = os.environ.get('BATCH_ID', 'unknown')
current = os.environ.get('CURRENT_INDEX', '0')
total = os.environ.get('TOTAL_ITEMS', '0')

params = json.loads(sys.argv[1] if len(sys.argv) > 1 else '{}')
item = params.get('item')

print(f"Processing {current}/{total} in batch {batch_id}", file=sys.stderr)

result = {"item": item, "batch_id": batch_id, "processed": True}
print(json.dumps(result))
```

### 查看 Recipe 环境变量定义

```bash
# 查看 Recipe 详情，包含环境变量定义
uv run frago recipe info openai_chat

# JSON 格式输出（包含 env 字段）
uv run frago recipe info openai_chat --format json
```

**输出示例**：
```
Recipe: openai_chat
==================================================

基本信息
──────────────────────────────────────────────────
名称:     openai_chat
类型:     atomic
运行时:   python
版本:     1.0.0
来源:     User

环境变量
──────────────────────────────────────────────────
• OPENAI_API_KEY (必需): OpenAI API 密钥
• MODEL_NAME (可选, 默认: gpt-4o): 使用的模型名称
• MAX_TOKENS (可选, 默认: 1000): 最大 token 数

依赖
──────────────────────────────────────────────────
无
```

### 安全最佳实践

1. **不要硬编码敏感信息**：将 API 密钥等存储在 `.env` 文件中
2. **将 `.env` 加入 `.gitignore`**：避免提交敏感信息到版本控制
3. **使用 `required: true`**：确保关键环境变量存在
4. **提供合理默认值**：对非敏感配置使用 `default` 字段

```bash
# .gitignore
.frago/.env
```

---

## 迁移现有 Recipe

### 从旧方式迁移到新系统

#### 旧方式（直接调用 `exec-js`）

```bash
frago chrome exec-js src/frago/recipes/upwork_extract_job.js
```

#### 新方式

1. **迁移脚本到新位置**:
   ```bash
   # 脚本已自动迁移到 examples/atomic/chrome/
   uv run frago recipe copy upwork_extract_job_details_as_markdown
   ```

2. **使用新命令**:
   ```bash
   uv run frago recipe run upwork_extract_job_details_as_markdown \
     --params '{"url": "..."}'
   ```

### 新旧方式对比

| 特性 | 旧方式 (`exec-js`) | 新方式 (`recipe run`) |
|------|-------------------|---------------------|
| 参数传递 | 命令行参数 | JSON 格式（统一） |
| 元数据 | 无 | YAML frontmatter |
| 查找路径 | 固定路径 | 三级查找（项目/用户/示例） |
| 错误处理 | 原始输出 | 结构化 JSON 错误 |
| 依赖管理 | 无 | 自动检查依赖 |
| 编排能力 | 无 | 支持 Workflow |

---

## 故障排查

### Recipe 未找到

**问题**: `错误: Recipe 'xxx' 未找到`

**解决**:
1. 检查 Recipe 名称拼写
2. 运行 `uv run frago recipe list` 查看可用 Recipe
3. 确认元数据文件 `.md` 存在

### 参数格式错误

**问题**: `错误: 参数格式无效`

**解决**:
- 使用双引号（JSON 规范）: `{"url": "..."}` 而非 `{'url': '...'}`
- 转义特殊字符: `"{\"key\": \"value\"}"`
- 或使用参数文件: `--params-file params.json`

### 依赖 Recipe 未找到

**问题**: Workflow 执行失败，提示依赖缺失

**解决**:
```bash
# 复制依赖的示例 Recipe
uv run frago recipe copy <dependency_name>

# 或创建自定义的依赖 Recipe
```

### Recipe 执行超时

**问题**: `错误: Recipe 执行超时`

**解决**:
- 增加超时时间: `--timeout 600`
- 检查 Recipe 脚本是否有无限循环
- 检查网络连接（Chrome CDP 操作）

---

---

## AI-First 设计总结

### AI 使用 Recipe 系统的核心流程

```text
1. 用户提出任务
   ↓
2. AI 调用: uv run frago recipe list --format json
   ↓
3. AI 分析元数据:
   - description: 快速理解功能
   - use_cases: 判断是否适用当前任务
   - output_targets: 选择输出方式（stdout/file/clipboard）
   ↓
4. AI 决策:
   - 使用现有 Recipe → 执行
   - 无合适 Recipe → 调用 /frago.recipe 生成新 Recipe
   ↓
5. AI 执行: uv run frago recipe run <name> --params '{...}' [--output-file/--output-clipboard]
   ↓
6. AI 处理结果:
   - success: true → 向用户报告
   - success: false → 分析 error.stderr，采取策略（重试/报告）
```

### 关键设计原则

1. **元数据驱动**: AI 通过语义字段理解 Recipe 能力，无需读取脚本代码
2. **结构化输出**: 所有 CLI 命令支持 `--format json`，便于 AI 解析
3. **输出形态声明**: Recipe 明确声明支持的输出去向，AI 可根据任务规划
4. **AI 生成 Workflow**: `/frago.recipe` 命令让 AI 自动创建编排 Recipe
5. **错误可理解**: 结构化错误让 AI 能分析失败原因并自动应对

### AI vs 人类使用对比

| 特性 | AI 使用方式 | 人类使用方式 |
|------|------------|-------------|
| **发现 Recipe** | `recipe list --format json` + 语义分析 | `recipe list`（表格）或 `recipe info` |
| **创建 Recipe** | `/frago.recipe create` 自动生成 | 手动编写脚本和元数据 |
| **执行 Recipe** | Bash 工具调用，自动选择输出方式 | 手动敲命令，手动指定 --output-file |
| **错误处理** | 解析 JSON 错误，自动应对策略 | 读取错误信息，手动排查 |
| **编排任务** | 自动生成 Workflow Python 脚本 | 手动组合多个 Recipe |

---

## 下一步

- **阅读完整文档**: [spec.md](./spec.md)
- **查看数据模型**: [data-model.md](./data-model.md)
- **CLI 命令参考**: [contracts/cli-commands.md](./contracts/cli-commands.md)
- **技术研究**: [research.md](./research.md)

---

## 反馈

遇到问题或有改进建议？请在项目仓库提交 Issue。
