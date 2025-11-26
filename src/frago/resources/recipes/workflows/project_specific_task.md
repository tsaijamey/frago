---
name: project_specific_task
type: workflow
runtime: python
version: "1.0"
description: "项目专属任务示例 - 演示如何使用项目级 Recipe"
use_cases:
  - "在特定项目中定义专属的自动化流程"
  - "覆盖全局 Recipe 实现项目特定的行为"
  - "保持项目自动化脚本与项目代码一起管理"
output_targets:
  - stdout
  - file
tags:
  - project-specific
  - workflow
  - example
inputs:
  project_name:
    type: string
    required: false
    description: "项目名称（可选，默认使用当前目录名）"
    default: "当前项目"
outputs:
  success:
    type: boolean
    description: "任务是否成功执行"
  message:
    type: string
    description: "执行结果消息"
  project_info:
    type: object
    description: "项目相关信息"
dependencies: []
---

# project_specific_task

## 功能描述

这是一个项目级 Recipe 示例，演示如何在项目目录下创建专属的自动化任务。

项目级 Recipe 存储在项目根目录的 `.frago/recipes/` 目录中，具有最高优先级：
- **优先级**: Project > User > Example
- **用途**: 项目特定的自动化流程、覆盖全局 Recipe
- **版本管理**: 与项目代码一起提交到 Git

## 使用方法

### 创建项目级 Recipe

1. 在项目根目录创建目录结构：
   ```bash
   mkdir -p .frago/recipes/workflows
   mkdir -p .frago/recipes/atomic/chrome
   mkdir -p .frago/recipes/atomic/system
   ```

2. 将 Recipe 脚本和元数据文件放入对应目录：
   ```
   .frago/
   └── recipes/
       ├── atomic/
       │   ├── chrome/
       │   │   ├── my_chrome_recipe.js
       │   │   └── my_chrome_recipe.md
       │   └── system/
       │       ├── my_system_task.py
       │       └── my_system_task.md
       └── workflows/
           ├── project_workflow.py
           └── project_workflow.md
   ```

3. 执行项目级 Recipe：
   ```bash
   # Frago 会自动优先使用项目级 Recipe
   uv run frago recipe run my_chrome_recipe
   ```

### 执行此示例

**前置条件**：
- 已安装 Frago CLI 工具
- 在项目根目录执行

**执行方式**：

```bash
# 使用默认参数
uv run frago recipe run project_specific_task

# 指定项目名称
uv run frago recipe run project_specific_task \
  --params '{"project_name": "MyProject"}'
```

## 前置条件

- Python 3.9+ 环境
- Frago CLI 工具已安装
- 在项目目录中执行（有 .frago/recipes/ 目录）

## 预期输出

**JSON 输出** (stdout):

```json
{
  "success": true,
  "message": "项目任务执行成功",
  "project_info": {
    "name": "MyProject",
    "recipe_source": "Project",
    "cwd": "/path/to/project"
  }
}
```

## 注意事项

### 优先级规则

当存在同名 Recipe 时，系统按以下优先级选择：

1. **项目级** (`.frago/recipes/`) - 最高优先级
2. **用户级** (`~/.frago/recipes/`) - 中等优先级
3. **示例级** (`examples/`) - 最低优先级

**示例场景**：
- 如果 `.frago/recipes/workflows/project_workflow.py` 存在
- 同时 `~/.frago/recipes/workflows/project_workflow.py` 也存在
- 系统会使用项目级的 Recipe（优先级更高）

### 查看优先级

使用 `recipe info` 命令查看 Recipe 来源和优先级：

```bash
uv run frago recipe info project_specific_task
```

输出示例：
```
Recipe: project_specific_task
==================================================

基本信息
──────────────────────────────────────────────────
名称:     project_specific_task
类型:     workflow
运行时:   python
版本:     1.0
来源:     Project
          (同名 Recipe 也存在于: User, Example)
路径:     .frago/recipes/workflows/project_specific_task.py
```

### 版本管理建议

**推荐做法**：
- 将 `.frago/recipes/` 目录提交到 Git
- 在 `.gitignore` 中排除临时文件和敏感数据
- 团队成员共享项目特定的 Recipe

**不推荐**：
- 将 `.frago/` 整体加入 `.gitignore`（会丢失项目 Recipe）
- 在项目 Recipe 中硬编码绝对路径

### 覆盖全局 Recipe

如果需要为特定项目定制全局 Recipe 的行为：

1. 从 `examples/` 或 `~/.frago/recipes/` 复制 Recipe 到项目
2. 修改项目级 Recipe 实现项目特定逻辑
3. 保持相同的 Recipe 名称

**示例**：
```bash
# 复制全局 Recipe 到项目
uv run frago recipe copy youtube_extract_video_transcript

# 修改项目级 Recipe（添加项目特定的后处理）
vim .frago/recipes/atomic/chrome/youtube_extract_video_transcript.js

# 执行时会使用项目级版本
uv run frago recipe run youtube_extract_video_transcript
```

## 更新历史

| 日期 | 版本 | 变更说明 |
|------|------|----------|
| 2025-11-21 | v1.0 | 初始版本，演示项目级 Recipe 使用 |
