# Recipe 字段规范

适用于：`/frago.recipe`、`/frago.test`

## 验证命令

```bash
frago recipe validate <配方目录或recipe.md路径>
frago recipe validate <路径> --format json
```

## 必需字段

| 字段 | 类型 | 要求 |
|------|------|------|
| `name` | string | 仅含 `[a-zA-Z0-9_-]` |
| `type` | string | `atomic` 或 `workflow` |
| `runtime` | string | `chrome-js`, `python`, `shell` |
| `version` | string | 格式 `1.0` 或 `1.0.0` |
| `description` | string | 必需，≤200 字符 |
| `use_cases` | list | 至少一个场景 |
| `output_targets` | list | `stdout`, `file`, `clipboard` 中的值 |

## 可选字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `inputs` | dict | 输入参数定义（需含 `type` 和 `required`） |
| `outputs` | dict | 输出定义 |
| `dependencies` | list | 依赖的其他配方（workflow 类型） |
| `tags` | list | 标签（AI 可理解字段） |
| `env` | dict | 环境变量定义（详见下文） |
| `system_packages` | bool | 是否使用系统 Python |

## 环境变量（env）字段规范

配方可以声明需要的环境变量，运行时会自动从 `~/.frago/.env` 加载。

### env 字段结构

```yaml
env:
  VAR_NAME:
    required: true          # 是否必需（默认 false）
    default: "默认值"        # 默认值（字符串）
    description: "变量说明"  # 描述
```

### 示例

```yaml
env:
  OPENAI_API_KEY:
    required: true
    description: "OpenAI API 密钥"
  MODEL_NAME:
    required: false
    default: "gpt-4"
    description: "使用的模型名称"
```

### 环境变量加载优先级（高到低）

1. Workflow 上下文共享变量
2. **`~/.frago/.env`**
3. 系统环境变量
4. 配方定义的 `default` 值

### ~/.frago/.env 配置

在 `~/.frago/.env` 中配置常用的环境变量：

```bash
# API 密钥
OPENAI_API_KEY=sk-xxx
ANTHROPIC_API_KEY=sk-ant-xxx

# 其他配置
DEFAULT_MODEL=gpt-4
```

配方运行时会自动加载这些变量。

## Python 配方依赖声明（PEP 723）

Python 配方使用 `uv run` 执行，支持 **PEP 723 内联依赖声明**。

### 格式

在 `recipe.py` 文件头部添加（无需 shebang）：

```python
# /// script
# requires-python = ">=3.9"
# dependencies = ["package1", "package2>=1.0"]
# ///
```

### 示例

```python
# /// script
# requires-python = ">=3.9"
# dependencies = ["edge-tts", "httpx>=0.24"]
# ///
"""
Recipe: tts_generate_voice
Description: 使用 Edge TTS 生成语音
"""

import json
import sys
# ...
```

### 说明

- `uv run` 会自动解析内联依赖并创建临时虚拟环境
- 无需 `requirements.txt` 或 `pyproject.toml`
- 依赖仅在首次运行时安装，后续执行使用缓存
- 若需使用系统包（如 `dbus`），在 `recipe.md` 中设置 `system_packages: true`

## 验证内容

`frago recipe validate` 检查以下内容：

1. **YAML frontmatter** - 解析 recipe.md 的 YAML 头
2. **必需字段** - 所有必需字段是否存在
3. **字段格式** - name 字符规则、version 格式、枚举值
4. **脚本文件** - 根据 runtime 检查对应脚本（recipe.js/py/sh）是否存在且非空
5. **语法检查** - Python 脚本进行语法检查
6. **依赖检查** - workflow 类型检查依赖的配方是否已注册

## 验证输出示例

### 验证通过

```
✓ 配方验证通过: examples/atomic/chrome/my_recipe
  名称: my_recipe
  类型: atomic
  运行时: chrome-js
```

### 验证失败

```
✗ 配方验证失败: examples/atomic/chrome/broken_recipe
错误:
  • name 必须仅包含字母、数字、下划线、连字符
  • use_cases 必须包含至少一个使用场景
  • 脚本文件不存在: recipe.js（runtime: chrome-js）
```

### JSON 格式

```json
{
  "valid": false,
  "path": "examples/atomic/chrome/broken_recipe",
  "name": null,
  "type": null,
  "runtime": null,
  "errors": ["元数据解析失败: 缺少必需字段: 'name'"],
  "warnings": []
}
```

## 完整 recipe.md 模板

```yaml
---
name: platform_action_object
type: atomic
runtime: chrome-js
version: "1.0.0"
description: "一句话描述配方功能（≤200字符）"
use_cases:
  - "场景1：用户需要..."
  - "场景2：当..."
output_targets:
  - stdout
  - file
tags:
  - extraction
  - chrome
inputs:
  param_name:
    type: string
    required: true
    description: "参数说明"
outputs:
  result:
    type: object
    description: "输出说明"
env:
  API_KEY:
    required: true
    description: "API 密钥，在 ~/.frago/.env 中配置"
  TIMEOUT:
    required: false
    default: "30"
    description: "超时时间（秒）"
---

# platform_action_object

## 功能描述
## 使用方法
## 前置条件
## 预期输出
## 注意事项
## 更新历史
```
