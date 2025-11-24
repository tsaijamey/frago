# Data Model: Run命令系统

**Feature**: 005-run-command-system
**Created**: 2025-11-21

---

## 核心实体

### 1. RunInstance（Run实例）

**描述**：一个主题的完整信息中心，持久化存储该主题下所有任务的执行历史和积累的知识。

**存储位置**：`runs/<run_id>/` 目录结构

**属性**：

| 字段 | 类型 | 必需 | 描述 | 验证规则 |
|------|------|------|------|---------|
| `run_id` | str | ✅ | 主题slug（如 "find-job-on-upwork"） | 1-50字符，小写字母/数字/连字符 |
| `theme_description` | str | ✅ | 原始任务描述 | 1-500字符 |
| `created_at` | datetime | ✅ | 首次创建时间 | ISO 8601格式 |
| `last_accessed` | datetime | ✅ | 最后访问时间 | ISO 8601格式 |
| `status` | enum | ✅ | 状态：active/archived | 枚举值 |

**关系**：
- 1个RunInstance → N个LogEntry（通过 `logs/execution.jsonl`）
- 1个RunInstance → N个Screenshot（通过 `screenshots/` 目录）
- 1个RunInstance → N个Script（通过 `scripts/` 目录）

**状态转换**：
```
[创建] → active
active → archived (用户调用 archive 命令)
archived → active (用户重新访问)
```

**文件系统映射**：
```
runs/<run_id>/
├── .metadata.json          # 存储 RunInstance 元数据
├── logs/
│   └── execution.jsonl     # LogEntry 集合
├── screenshots/
│   └── 001_*.png           # Screenshot 文件
├── scripts/
│   └── *.py, *.js, *.sh    # Script 文件
└── outputs/                 # 可选，用户生成的导出文件
```

**验证规则**：
- `run_id` 必须通过 `^[a-z0-9-]{1,50}$` 正则验证
- `theme_description` 不能为空字符串
- `created_at` 和 `last_accessed` 必须是有效的 ISO 8601 时间戳
- `status` 必须是 "active" 或 "archived"

---

### 2. LogEntry（日志条目）

**描述**：单个执行步骤的结构化记录，存储在 JSONL 文件中。

**存储位置**：`runs/<run_id>/logs/execution.jsonl`（每行一个JSON对象）

**属性**：

| 字段 | 类型 | 必需 | 描述 | 验证规则 |
|------|------|------|------|---------|
| `timestamp` | str | ✅ | ISO 8601时间戳 | 格式：YYYY-MM-DDTHH:MM:SSZ |
| `step` | str | ✅ | 步骤描述 | 1-200字符 |
| `status` | enum | ✅ | success/error/warning | 枚举值 |
| `action_type` | enum | ✅ | 操作类型 | 9种预定义值（见下） |
| `execution_method` | enum | ✅ | 执行方法 | 6种预定义值（见下） |
| `data` | object | ✅ | 操作详情（自由结构） | 有效JSON对象 |
| `schema_version` | str | ✅ | 日志格式版本 | 格式：MAJOR.MINOR（如 "1.0"） |

**action_type 枚举值**：
1. `navigation` - 页面导航
2. `extraction` - 数据提取
3. `interaction` - 页面交互（点击、输入、滚动）
4. `screenshot` - 截图
5. `recipe_execution` - Recipe 调用
6. `data_processing` - 数据处理/转换
7. `analysis` - 分析/推理（AI 的思考结论）
8. `user_interaction` - 用户交互（询问、确认）
9. `other` - 其他（需在 data 中说明）

**execution_method 枚举值**：
1. `command` - CLI 命令执行
2. `recipe` - Recipe 调用
3. `file` - 执行脚本文件
4. `manual` - 需要人工操作
5. `analysis` - 纯推理/思考
6. `tool` - 调用 AI 工具（如 AskUserQuestion）

**data 字段约束**：
- 当 `execution_method` 为 `file` 时，必须包含 `file` 字段（记录脚本相对路径）
- 禁止在 `data` 中直接存储代码内容（超过100行的文本）
- 建议包含的字段（根据不同类型）：
  - `command`: 执行的命令字符串、`exit_code`、`output`
  - `recipe`: `recipe_name`、`params`、`output`
  - `file`: `file`（必需）、`language`、`command`、`exit_code`、`output`、`result_file`

**示例**（command类型）：
```json
{
  "timestamp": "2025-11-21T10:30:00Z",
  "step": "导航到Upwork搜索页",
  "status": "success",
  "action_type": "navigation",
  "execution_method": "command",
  "schema_version": "1.0",
  "data": {
    "command": "uv run frago navigate https://upwork.com/search",
    "exit_code": 0,
    "output": "导航成功"
  }
}
```

**示例**（file类型）：
```json
{
  "timestamp": "2025-11-21T10:35:00Z",
  "step": "过滤薪资大于$50的职位",
  "status": "success",
  "action_type": "data_processing",
  "execution_method": "file",
  "schema_version": "1.0",
  "data": {
    "file": "scripts/filter_jobs.py",
    "language": "python",
    "command": "uv run python scripts/filter_jobs.py",
    "exit_code": 0,
    "output": "处理了15条数据，筛选出8条",
    "result_file": "outputs/jobs_filtered.json"
  }
}
```

**验证规则**：
- 所有必需字段必须存在
- `timestamp` 必须符合 ISO 8601 格式
- `status` 必须是 "success"、"error" 或 "warning"
- `action_type` 和 `execution_method` 必须是预定义枚举值之一
- `data` 必须是有效的 JSON 对象（非 null）
- `schema_version` 当前版本为 "1.0"

---

### 3. Screenshot（截图记录）

**描述**：任务执行过程中捕获的页面快照。

**存储位置**：`runs/<run_id>/screenshots/<序号>_<描述slug>.png`

**属性**：

| 字段 | 类型 | 必需 | 描述 | 验证规则 |
|------|------|------|------|---------|
| `sequence_number` | int | ✅ | 步骤编号（001, 002...） | 3位零填充整数 |
| `description` | str | ✅ | 用户描述 | 1-100字符 |
| `file_path` | str | ✅ | 相对路径 | 格式：screenshots/NNN_*.png |
| `timestamp` | datetime | ✅ | 创建时间 | ISO 8601格式 |

**命名规则**：
```
screenshots/
├── 001_search-page.png
├── 002_job-details.png
└── 003_application-form.png
```

**生成逻辑**（伪码）：
```python
def generate_screenshot_path(description: str, screenshots_dir: Path) -> str:
    # 1. 扫描现有截图，获取最大序号
    existing_files = list(screenshots_dir.glob("*.png"))
    max_seq = max([int(f.stem[:3]) for f in existing_files], default=0)

    # 2. 生成新序号
    new_seq = max_seq + 1

    # 3. slug化描述
    desc_slug = slugify(description, max_length=50)

    # 4. 构造文件名
    filename = f"{new_seq:03d}_{desc_slug}.png"
    return f"screenshots/{filename}"
```

**验证规则**：
- 序号必须是3位零填充（001-999）
- 文件扩展名必须是 `.png`
- 描述slug必须符合 `^[a-z0-9-]{1,50}$` 正则

---

### 4. CurrentRunContext（当前Run上下文）

**描述**：全局配置文件，存储当前工作的 run 实例信息。

**存储位置**：`.frago/current_run`（JSON文件）

**属性**：

| 字段 | 类型 | 必需 | 描述 | 验证规则 |
|------|------|------|------|---------|
| `run_id` | str | ✅ | 当前run的ID | 有效的run_id |
| `last_accessed` | datetime | ✅ | 最后设置时间 | ISO 8601格式 |
| `theme_description` | str | ✅ | 主题描述（冗余存储） | 1-500字符 |

**示例**：
```json
{
  "run_id": "find-job-on-upwork",
  "last_accessed": "2025-11-21T10:45:00Z",
  "theme_description": "在Upwork上搜索Python职位"
}
```

**优先级**：
1. 环境变量 `FRAGO_CURRENT_RUN`（最高优先级）
2. 配置文件 `.frago/current_run`
3. 无默认值，未设置时报错提示用户运行 `set-context`

**验证规则**：
- `run_id` 必须指向存在的 run 实例目录
- 如果指向的 run 被删除，自动清空配置文件并提示用户

---

## 数据验证层次

### Level 1: 格式验证（CLI输入时）
- 参数类型检查（字符串长度、枚举值）
- 必需字段存在性
- 文件路径有效性

### Level 2: 业务规则验证（Manager层）
- run_id 唯一性检查
- run 实例存在性验证
- 日志格式完整性

### Level 3: 契约测试（测试层）
- JSONL 输出符合 schema
- API 返回值类型正确
- 错误消息格式一致

---

## 数据迁移策略

### schema_version 字段
- 当前版本：`"1.0"`
- 未来需要修改 LogEntry 结构时：
  1. 递增版本号（如 `"1.1"`）
  2. 提供迁移脚本（读取旧版本日志，转换为新格式）
  3. 向后兼容（新代码能读取旧格式）

### 示例迁移场景
假设未来需要添加 `user_id` 字段：
```python
def migrate_log_entry(entry: dict) -> dict:
    version = entry.get("schema_version", "1.0")

    if version == "1.0":
        # 迁移到 1.1
        entry["user_id"] = "default"
        entry["schema_version"] = "1.1"

    return entry
```

---

## 关系图

```
RunInstance (runs/<id>/)
├─┬─ .metadata.json (元数据)
│ │
│ ├─ logs/execution.jsonl (1:N)
│ │  └─ LogEntry (每行一个)
│ │     ├─ action_type (枚举)
│ │     ├─ execution_method (枚举)
│ │     └─ data (自由结构)
│ │
│ ├─ screenshots/ (1:N)
│ │  └─ Screenshot (按序号命名)
│ │
│ └─ scripts/ (1:N)
│    └─ Script (AI生成的代码文件)
│
CurrentRunContext (.frago/current_run)
└─ run_id (指向某个RunInstance)
```

---

## 性能考虑

### 日志写入
- **追加模式**：使用 `open(file, 'a')` 追加到 JSONL 文件
- **原子性**：每次写入一个完整的 JSON 行（带换行符）
- **预期负载**：单个 run 实例 <1000 条日志，文件大小 <1MB

### 日志读取
- **只读最后N行**：使用 `tail` 或反向读取文件
- **流式解析**：逐行解析 JSONL，避免一次性加载整个文件
- **索引优化**：暂不需要（文件小，扫描快）

### Run 实例发现
- **缓存策略**：扫描 `runs/` 目录，缓存5秒
- **懒加载元数据**：列出 run 列表时不读取完整日志，仅读取 `.metadata.json`
- **并发安全**：文件系统操作天然线性，无需锁

---

## 错误处理模型

### 数据层错误
- `RunNotFoundError`: run_id 不存在
- `InvalidRunIDError`: run_id 格式不合法
- `CorruptedLogError`: JSONL 文件损坏
- `ContextNotSetError`: 当前 run 上下文未设置

### 恢复策略
- **日志损坏**：跳过损坏行，记录警告，继续处理
- **元数据缺失**：从日志文件重建元数据
- **上下文失效**：清空配置，提示用户重新设置
