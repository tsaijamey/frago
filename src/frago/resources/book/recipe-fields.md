# recipe-fields

分类: 效率（AVAILABLE）

## 解决什么问题
agent 写 Recipe 时字段格式错误、缺少必填字段、flow/env 等高级字段用法不正确，导致 {{frago_launcher}} recipe validate 失败。

## 验证命令

  {{frago_launcher}} recipe validate <recipe 目录或 recipe.md 路径>
  {{frago_launcher}} recipe validate <path> --format json

## 必填字段

| 字段 | 类型 | 要求 |
|------|------|------|
| name | string | 只含 [a-zA-Z0-9_-] |
| type | string | atomic 或 workflow |
| runtime | string | chrome-js, python, shell |
| version | string | 格式 1.0 或 1.0.0 |
| description | string | 必填，≤200 字符 |
| use_cases | list | 至少一个场景 |
| output_targets | list | 值从 stdout, file, clipboard 中选 |

## 可选字段

| 字段 | 类型 | 说明 |
|------|------|------|
| inputs | dict | 输入参数定义（需含 type 和 required） |
| outputs | dict | 输出定义 |
| dependencies | list | 依赖的其他 recipe（workflow 类型） |
| tags | list | 标签（AI 可理解的分类） |
| env | dict | 环境变量定义 |
| system_packages | bool | 是否使用系统 Python |

## flow 字段（workflow 必填）

workflow 类型必须包含 flow 字段描述执行步骤和数据流：

  flow:
    - step: 1
      action: "validate_input"
      description: "验证输入目录存在"
      inputs:
        - source: "params.dir"

    - step: 2
      action: "scan_files"
      description: "扫描目录中的媒体文件"
      inputs:
        - source: "params.dir"
      outputs:
        - name: "files"
          type: "list"

    - step: 3
      action: "process_files"
      description: "调用依赖 recipe 处理文件"
      recipe: "file_processor"
      inputs:
        - source: "step.2.files"
      outputs:
        - name: "result"
          type: "object"

输入来源格式：
- params.<name> — 来自 recipe 输入参数
- step.<n>.<output> — 来自前序步骤输出
- env.<var> — 来自环境变量

## env 字段

  env:
    OPENAI_API_KEY:
      required: true
      description: "OpenAI API key"
    MODEL_NAME:
      required: false
      default: "gpt-4"
      description: "使用的模型名称"

环境变量加载优先级（高到低）：
1. Workflow context 共享变量
2. ~/.frago/.env
3. 系统环境变量
4. Recipe 定义的 default 值

## Python 依赖声明（PEP 723）

在 recipe.py 文件顶部用内联声明，无需 requirements.txt：

  # /// script
  # requires-python = ">=3.13"
  # dependencies = ["edge-tts", "httpx>=0.24"]
  # ///

uv run 自动解析依赖并创建临时虚拟环境，首次运行后使用缓存。
如需系统包（如 dbus），在 recipe.md 中设 system_packages: true。

## validate 检查内容

1. YAML frontmatter 解析
2. 必填字段存在性
3. 字段格式（name 字符规则、version 格式、枚举值）
4. 脚本文件存在性（根据 runtime 检查 recipe.js/py/sh）
5. Python 脚本语法检查
6. 依赖检查（workflow 类型检查依赖 recipe 是否已注册）
7. flow 结构检查（workflow 类型）

## 完整 recipe.md 模板

  ---
  name: platform_action_object
  type: atomic
  runtime: chrome-js
  version: "1.0.0"
  description: "一句话描述 recipe 功能（≤200 字符）"
  use_cases:
    - "场景 1: 用户需要..."
    - "场景 2: 当..."
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
      description: "参数描述"
  outputs:
    result:
      type: object
      description: "输出描述"
  ---

  # platform_action_object

  ## 功能描述
  ## 使用方式
  ## 前置条件
  ## 预期输出
  ## 注意事项
  ## 更新历史

注意：Recipe 元数据存储在 recipe.md 的 YAML frontmatter 中，不是单独的 .yaml 文件。
