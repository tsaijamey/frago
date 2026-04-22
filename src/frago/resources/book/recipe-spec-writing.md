# recipe-spec-writing

分类: 效率（AVAILABLE）

## 解决什么问题
agent 直接写 recipe 时容易遗漏边界情况、参数定义不清晰、缺少测试用例。spec 先行把需求定义清楚，再生成代码，质量更高。

## spec.md 文件位置
spec.md 与 recipe.md 同级，放在 recipe 目录内：
  ~/.frago/recipes/atomic/system/<name>/spec.md
  ~/.frago/recipes/atomic/chrome/<name>/spec.md
  ~/.frago/recipes/workflows/<name>/spec.md

## spec.md 必需 section

### 1. Goal
一段话描述这个 recipe 要做什么。写清楚输入是什么、输出是什么、核心价值。

### 2. Type & Runtime
明确选择并给出理由：

type 选择：
  - atomic — 单一功能，独立执行
  - workflow — 编排多个 atomic recipe

runtime 选择（仅 atomic）：
  - python — 数据处理、API 调用、文件操作
  - chrome-js — 浏览器页面操作、DOM 交互、内容提取
  - shell — 系统命令组合、文件批处理

写一句话说明为什么选这个 runtime，不要只写"因为需要"。

### 3. Inputs
每个输入参数：
  - 名称、类型、是否必填
  - 说明（含默认值和约束）
  - 示例值

格式与 recipe-fields 的 inputs 字段对齐：
  inputs:
    query:
      type: string
      required: true
      description: "搜索关键词"
    max_results:
      type: integer
      required: false
      description: "最大结果数，默认 10"

### 4. Outputs
定义输出字段和 output_targets：
  - 每个输出字段的名称、类型、说明
  - output_targets: stdout / file / clipboard（可多选）

### 5. Error Scenarios
枚举可能的错误场景及处理方式：
  - 网络超时 → 重试 N 次后返回错误
  - 目标页面结构变更 → 选择器失败时的 fallback
  - 参数缺失 → 返回清晰错误信息

### 6. Test Cases
至少一个可执行的测试用例：
  命令: {{frago_launcher}} recipe run <name> --params '{"query": "test"}'
  预期输出: {"success": true, "results": [...]}
  验证点: results 数组非空，每项包含 title 和 url

### 7. Chrome-JS 专属（runtime 为 chrome-js 时必填）
  - target_sites: 目标网站列表
  - selector_strategy: 选择器策略说明（优先 data 属性 > aria > 语义标签 > class）

### 8. Workflow 专属（type 为 workflow 时必填）
  - dependencies: 依赖的子 recipe 列表
  - flow_steps: 执行步骤概述（对应 recipe.md 的 flow 字段）

## 怎么从一句话需求推导

  1. 提取动词 → 确定核心操作
  2. 提取对象 → 确定操作目标
  3. 判断是否需要浏览器 → 选 runtime
  4. 判断是否编排多步 → 选 type
  5. 推导输入参数（用户需要提供什么）
  6. 推导输出字段（用户期望得到什么）
  7. 列举失败场景

## 不做什么
- spec 只定义需求，不写实现代码
- 不做架构设计，那是 recipe-creation 的事
- 不填写 recipe.md 的 YAML frontmatter
