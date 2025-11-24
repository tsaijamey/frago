# CLI Commands Contract: Run命令系统

**Feature**: 005-run-command-system
**Created**: 2025-11-21
**Version**: 1.0

本文档定义 `uv run frago run` 子命令组的 CLI 接口契约。

---

## 命令组概览

```bash
uv run frago run <subcommand> [options]
```

**子命令列表**：
- `init` - 初始化新 run 实例
- `set-context` - 设置当前工作 run
- `log` - 记录结构化日志
- `screenshot` - 保存截图
- `list` - 列出所有 run 实例
- `info` - 显示 run 实例详情
- `archive` - 归档 run 实例

---

## 1. init - 初始化新run实例

### 用法

```bash
uv run frago run init <description>
```

### 参数

| 参数 | 类型 | 必需 | 描述 |
|------|------|------|------|
| `description` | str | ✅ | 任务描述（用于生成主题slug） |

### 返回

**成功（stdout）**：
```json
{
  "run_id": "find-job-on-upwork",
  "created_at": "2025-11-21T10:30:00Z",
  "path": "/absolute/path/to/runs/find-job-on-upwork"
}
```

**退出码**：
- `0` - 成功
- `1` - 失败（如：无法创建目录）

### 副作用

1. 创建目录结构：
   ```
   runs/<run_id>/
   ├── .metadata.json
   ├── logs/
   ├── screenshots/
   ├── scripts/
   └── outputs/
   ```

2. 写入 `.metadata.json`：
   ```json
   {
     "run_id": "find-job-on-upwork",
     "theme_description": "在Upwork上搜索Python职位",
     "created_at": "2025-11-21T10:30:00Z",
     "last_accessed": "2025-11-21T10:30:00Z",
     "status": "active"
   }
   ```

### 示例

```bash
$ uv run frago run init "在Upwork上搜索Python职位"
{
  "run_id": "zai-upwork-shang-sou-suo-python-zhi-wei",
  "created_at": "2025-11-21T10:30:00Z",
  "path": "/home/user/project/runs/zai-upwork-shang-sou-suo-python-zhi-wei"
}
```

---

## 2. set-context - 设置当前工作run

### 用法

```bash
uv run frago run set-context <run_id>
```

### 参数

| 参数 | 类型 | 必需 | 描述 |
|------|------|------|------|
| `run_id` | str | ✅ | 目标run的ID |

### 返回

**成功（stdout）**：
```json
{
  "run_id": "find-job-on-upwork",
  "theme_description": "在Upwork上搜索Python职位",
  "set_at": "2025-11-21T10:32:00Z"
}
```

**失败（stderr）**：
```
Error: Run 'invalid-id' not found
```

**退出码**：
- `0` - 成功
- `1` - run_id 不存在
- `2` - 配置文件写入失败

### 副作用

1. 创建/更新 `.frago/current_run`：
   ```json
   {
     "run_id": "find-job-on-upwork",
     "last_accessed": "2025-11-21T10:32:00Z",
     "theme_description": "在Upwork上搜索Python职位"
   }
   ```

2. 更新 run 实例的 `.metadata.json` 中的 `last_accessed`

### 示例

```bash
$ uv run frago run set-context find-job-on-upwork
{
  "run_id": "find-job-on-upwork",
  "theme_description": "在Upwork上搜索Python职位",
  "set_at": "2025-11-21T10:32:00Z"
}
```

---

## 3. log - 记录结构化日志

### 用法

```bash
uv run frago run log \
  --step <step> \
  --status <status> \
  --action-type <type> \
  --execution-method <method> \
  --data <json>
```

### 参数

| 参数 | 类型 | 必需 | 描述 | 枚举值 |
|------|------|------|------|--------|
| `--step` | str | ✅ | 步骤描述 | 1-200字符 |
| `--status` | str | ✅ | 执行状态 | success/error/warning |
| `--action-type` | str | ✅ | 操作类型 | navigation/extraction/interaction/screenshot/recipe_execution/data_processing/analysis/user_interaction/other |
| `--execution-method` | str | ✅ | 执行方法 | command/recipe/file/manual/analysis/tool |
| `--data` | str | ✅ | JSON 格式的详细数据 | 有效JSON字符串 |

### 返回

**成功（stdout）**：
```json
{
  "logged_at": "2025-11-21T10:35:00Z",
  "run_id": "find-job-on-upwork",
  "log_file": "runs/find-job-on-upwork/logs/execution.jsonl"
}
```

**失败（stderr）**：
```
Error: Current run context not set. Run 'uv run frago run set-context <run_id>' first.
```

**退出码**：
- `0` - 成功
- `1` - 上下文未设置
- `2` - 参数验证失败
- `3` - 日志文件写入失败

### 副作用

1. 追加到 `runs/<run_id>/logs/execution.jsonl`：
   ```json
   {"timestamp":"2025-11-21T10:35:00Z","step":"提取到5个职位","status":"success","action_type":"extraction","execution_method":"command","schema_version":"1.0","data":{"command":"uv run frago recipe run ...","jobs":[...],"total":5}}
   ```

### 示例

```bash
$ uv run frago run log \
  --step "提取到5个职位" \
  --status "success" \
  --action-type "extraction" \
  --execution-method "command" \
  --data '{"command": "uv run frago recipe run ...", "jobs": [...], "total": 5}'

{
  "logged_at": "2025-11-21T10:35:00Z",
  "run_id": "find-job-on-upwork",
  "log_file": "runs/find-job-on-upwork/logs/execution.jsonl"
}
```

---

## 4. screenshot - 保存截图

### 用法

```bash
uv run frago run screenshot <description>
```

### 参数

| 参数 | 类型 | 必需 | 描述 |
|------|------|------|------|
| `description` | str | ✅ | 截图描述 |

### 返回

**成功（stdout）**：
```json
{
  "file_path": "runs/find-job-on-upwork/screenshots/001_search-page.png",
  "sequence_number": 1,
  "saved_at": "2025-11-21T10:36:00Z"
}
```

**退出码**：
- `0` - 成功
- `1` - 上下文未设置
- `2` - 截图保存失败

### 副作用

1. 调用 CDP 命令截图并保存到 `screenshots/<序号>_<描述slug>.png`
2. 自动记录 log（action_type=screenshot, execution_method=command）

### 示例

```bash
$ uv run frago run screenshot "搜索结果页面"
{
  "file_path": "runs/find-job-on-upwork/screenshots/001_search-page.png",
  "sequence_number": 1,
  "saved_at": "2025-11-21T10:36:00Z"
}
```

---

## 5. list - 列出所有run实例

### 用法

```bash
uv run frago run list [--format <format>] [--status <status>]
```

### 参数

| 参数 | 类型 | 必需 | 描述 | 默认值 |
|------|------|------|------|--------|
| `--format` | str | ❌ | 输出格式 | table |
| `--status` | str | ❌ | 过滤状态 | all |

**format 枚举值**：
- `table` - 表格格式（人类可读）
- `json` - JSON 格式（AI/脚本可解析）

**status 枚举值**：
- `all` - 所有状态
- `active` - 仅活跃
- `archived` - 仅归档

### 返回

**格式：table（stdout）**：
```
RUN_ID                       STATUS   CREATED_AT           LAST_ACCESSED        THEME
find-job-on-upwork          active   2025-11-20 10:30     2025-11-21 10:35     在Upwork上搜索Python职位
analyze-github-langchain    active   2025-11-19 15:00     2025-11-20 09:00     分析LangChain项目
```

**格式：json（stdout）**：
```json
{
  "runs": [
    {
      "run_id": "find-job-on-upwork",
      "status": "active",
      "created_at": "2025-11-20T10:30:00Z",
      "last_accessed": "2025-11-21T10:35:00Z",
      "theme_description": "在Upwork上搜索Python职位",
      "log_count": 15,
      "screenshot_count": 3
    },
    {
      "run_id": "analyze-github-langchain",
      "status": "active",
      "created_at": "2025-11-19T15:00:00Z",
      "last_accessed": "2025-11-20T09:00:00Z",
      "theme_description": "分析LangChain项目",
      "log_count": 42,
      "screenshot_count": 8
    }
  ],
  "total": 2
}
```

**退出码**：
- `0` - 成功

### 示例

```bash
$ uv run frago run list --format json --status active
{
  "runs": [...],
  "total": 2
}
```

---

## 6. info - 显示run实例详情

### 用法

```bash
uv run frago run info <run_id> [--format <format>]
```

### 参数

| 参数 | 类型 | 必需 | 描述 | 默认值 |
|------|------|------|------|--------|
| `run_id` | str | ✅ | 目标run的ID | - |
| `--format` | str | ❌ | 输出格式 | human |

**format 枚举值**：
- `human` - 人类可读格式
- `json` - JSON 格式

### 返回

**格式：human（stdout）**：
```
Run ID: find-job-on-upwork
Status: active
Theme: 在Upwork上搜索Python职位
Created: 2025-11-20 10:30:00
Last Accessed: 2025-11-21 10:35:00

Statistics:
- Log Entries: 15
- Screenshots: 3
- Scripts: 2
- Disk Usage: 1.2 MB

Recent Logs (last 5):
  [2025-11-21 10:35] ✓ 提取到5个职位 (extraction/command)
  [2025-11-21 10:34] ✓ 导航到搜索页 (navigation/command)
  ...
```

**格式：json（stdout）**：
```json
{
  "run_id": "find-job-on-upwork",
  "status": "active",
  "theme_description": "在Upwork上搜索Python职位",
  "created_at": "2025-11-20T10:30:00Z",
  "last_accessed": "2025-11-21T10:35:00Z",
  "statistics": {
    "log_entries": 15,
    "screenshots": 3,
    "scripts": 2,
    "disk_usage_bytes": 1258291
  },
  "recent_logs": [
    {
      "timestamp": "2025-11-21T10:35:00Z",
      "step": "提取到5个职位",
      "status": "success",
      "action_type": "extraction",
      "execution_method": "command"
    }
  ]
}
```

**退出码**：
- `0` - 成功
- `1` - run_id 不存在

---

## 7. archive - 归档run实例

### 用法

```bash
uv run frago run archive <run_id>
```

### 参数

| 参数 | 类型 | 必需 | 描述 |
|------|------|------|------|
| `run_id` | str | ✅ | 目标run的ID |

### 返回

**成功（stdout）**：
```json
{
  "run_id": "find-job-on-upwork",
  "archived_at": "2025-11-21T10:40:00Z",
  "previous_status": "active"
}
```

**退出码**：
- `0` - 成功
- `1` - run_id 不存在

### 副作用

1. 更新 `.metadata.json` 中的 `status` 为 `"archived"`
2. 如果是当前上下文的 run，清空 `.frago/current_run`

---

## 错误响应格式

所有命令失败时，错误信息输出到 stderr，格式统一：

```json
{
  "error": "Error type",
  "message": "Human-readable error message",
  "details": {
    "field": "value"
  }
}
```

**常见错误类型**：
- `ContextNotSet` - 当前 run 上下文未设置
- `RunNotFound` - run_id 不存在
- `InvalidArgument` - 参数验证失败
- `FileSystemError` - 文件系统操作失败

---

## 测试契约

### 单元测试
- 每个命令至少 3 个测试用例（成功、失败、边界）
- 参数验证测试
- 错误消息格式测试

### 集成测试
- 完整生命周期测试（init → set-context → log → archive）
- 多 run 实例并发测试
- 文件系统权限测试

### 契约测试
- JSON 输出格式验证（使用 JSON Schema）
- 退出码正确性
- stderr/stdout 分离正确性
