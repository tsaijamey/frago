# must-tool-priority

分类: 替代（MUST）

## 解决什么问题
agent 面对多种工具时选错优先级，导致功能重复、效率低下，或触发系统崩溃（如 WebSearch 在桌面模式下崩溃）。

## 优先级层级

  1. 已有 Recipe          ← 最高优先级，经过验证的自动化流程
  2. frago 命令           ← 跨 agent 通用，自带日志和统一接口
  3. 系统/第三方命令       ← jq、ffmpeg 等，功能强大
  4. Claude Code 内置工具  ← 最后手段（Read/Write/Edit/Glob/Grep）

## 场景对照

| 场景 | 正确做法 | 禁止做法 |
|------|----------|----------|
| 搜索信息 | frago chrome navigate google 搜索 | WebSearch（桌面模式会崩溃） |
| 查看网页 | frago chrome navigate + get-content | WebFetch |
| 打开 URL | frago chrome navigate | window.open / raw CDP |
| 提取数据 | 先查 frago recipe list | 从头手写 JS |
| 文件操作 | Claude Code Read/Write/Edit | 手动 cat/echo |

## 发现已有 Recipe

  frago recipe list                        # 列出所有 Recipe
  frago recipe list --format json          # JSON 格式（适合 AI 消费）
  frago recipe info <recipe_name>          # 查看 Recipe 详情
  frago recipe list | grep "keyword"       # 搜索相关 Recipe

## 为什么这样设计

- Recipe 最优先：可复用、含错误处理和 fallback selector、有文档
- frago 命令次之：跨 agent 通用、自动记录日志、统一 frago <command> 格式
- 系统命令第三：管道组合灵活，但不跨平台
- Claude Code 工具兜底：仅在以上工具无法满足时使用
