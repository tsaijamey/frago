# recipe-creation

分类: 效率（AVAILABLE）

## 解决什么问题
agent 有了 spec 之后，需要把需求映射为 recipe.md 元数据 + 脚本代码。本文档覆盖从 spec 到代码的完整流程。

## 从 spec.md 到 recipe 文件的映射

  spec.md section     →  recipe 文件
  ─────────────────────────────────
  Goal                →  recipe.md: description
  Type & Runtime      →  recipe.md: type, runtime
  Inputs              →  recipe.md: inputs
  Outputs             →  recipe.md: outputs, output_targets
  Test Cases          →  recipe.md: use_cases
  Chrome-JS 专属      →  recipe.md: tags（加入目标站点标签）
  Workflow 专属       →  recipe.md: dependencies, flow

## 目录结构和文件命名

  <recipe_dir>/
    spec.md          # 需求 spec（plan 阶段产出）
    recipe.md        # 元数据（YAML frontmatter）
    recipe.py        # Python runtime
    recipe.js        # chrome-js runtime
    recipe.sh        # shell runtime

脚本文件名固定为 recipe.{py,js,sh}，与 runtime 对应。

## recipe.md YAML frontmatter

详细字段规范查阅：
  uv run frago book recipe-fields

必填字段速查：
  ---
  name: platform_verb_object    # 只含 [a-zA-Z0-9_-]
  type: atomic                  # atomic | workflow
  runtime: python               # python | chrome-js | shell
  version: "1.0"
  description: "一句话描述"      # ≤200 字符
  use_cases:
    - "场景1"
  output_targets:
    - stdout
  ---

## 脚本编写规范

详细脚本规范查阅：
  uv run frago book recipe-authoring

关键要点：
  - Python: 参数从 sys.argv[1] 读取 JSON，输出 print(json.dumps(...))
  - Chrome-JS: 参数从 __FRAGO_PARAMS__ 全局变量读取
  - Shell: 参数从 $1 读取 JSON
  - 所有 runtime 的输出必须是有效 JSON
  - 错误时 exit code 非零 + stderr 输出错误信息

## 创建后必须验证

创建完 recipe.md 和脚本后，立即执行：
  uv run frago recipe validate <recipe_dir>

## validate 失败常见原因和修复

  错误                              修复
  ────────────────────────────────────────
  Missing required field: name      recipe.md frontmatter 缺少 name
  Invalid name format               name 只能包含 [a-zA-Z0-9_-]
  Missing script file               确认 recipe.{py,js,sh} 存在且与 runtime 匹配
  Invalid type                      type 只能是 atomic 或 workflow
  Invalid runtime                   runtime 只能是 python、chrome-js、shell
  Missing flow (workflow)           workflow 类型必须有 flow 字段
  Missing dependencies (workflow)   workflow 引用的子 recipe 必须存在

## 最终检查清单

  □ recipe.md frontmatter 所有必填字段完整
  □ 脚本文件与 runtime 匹配（.py/.js/.sh）
  □ 脚本能正确接收 JSON 参数
  □ 脚本输出有效 JSON
  □ frago recipe validate 通过
  □ spec.md 中的测试用例能执行通过
