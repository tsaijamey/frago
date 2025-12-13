# 工具优先级

适用于：`/frago.run`、`/frago.do`

## 优先级顺序

```
1. 已有配方 (Recipe)        ← 最优先
2. frago 命令               ← 跨 agent 通用
3. 系统命令或第三方软件命令   ← 功能强大
4. Claude Code 内置工具      ← 最后兜底
```

## 场景对照

- **搜索信息**：❌ `WebSearch` → ✅ `frago chrome navigate "https://google.com/search?q=..."`
- **查看网页**：❌ `Fetch` → ✅ `frago chrome navigate <url>` + `get-content`
- **提取数据**：❌ 手写 JS → ✅ 先查 `frago recipe list`
- **文件操作**：❌ 手动创建 → ✅ 使用 Claude Code 的 Write/Edit 工具

## 为什么这样设计

### 1. Recipe 最优先

- **可复用**：已经验证过的自动化流程
- **稳定**：包含错误处理和降级选择器
- **文档化**：有使用说明和前置条件

### 2. frago 命令次之

- **跨 agent 通用**：在 run/do/recipe/test 中都能使用
- **自动日志**：CDP 命令自动记录到 execution.jsonl
- **统一接口**：`frago <command>` 格式一致

### 3. 系统命令

- **功能强大**：`jq` 处理 JSON、`ffmpeg` 处理视频
- **灵活组合**：管道、重定向等 Shell 特性

### 4. Claude Code 工具兜底

- **文件操作**：Read/Write/Edit/Glob/Grep
- **辅助功能**：AskUserQuestion、TodoWrite
- 仅当上述工具无法满足时使用

## 发现现有 Recipe

```bash
# 列出所有 Recipe
frago recipe list

# AI 格式（JSON）
frago recipe list --format json

# 查看特定 Recipe 详情
frago recipe info <recipe_name>

# 搜索相关 Recipe
frago recipe list | grep "关键词"
```

## 命令帮助

```bash
# 查看所有 frago 命令
frago --help

# 查看具体命令用法
frago <command> --help
```
