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
| `env` | dict | 环境变量定义 |
| `system_packages` | bool | 是否使用系统 Python |

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
---

# platform_action_object

## 功能描述
## 使用方法
## 前置条件
## 预期输出
## 注意事项
## 更新历史
```
