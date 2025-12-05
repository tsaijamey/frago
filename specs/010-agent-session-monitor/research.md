# 研究报告: Agent 会话监控与数据展示优化

**日期**: 2025-12-05
**特性分支**: `010-agent-session-monitor`

## 1. Claude Code 会话数据格式

### 1.1 文件位置和命名规则

**目录结构**:
```
~/.claude/projects/
├── -home-yammi-repos-Frago/              # 项目目录（路径编码）
│   ├── {uuid}.jsonl                      # 标准会话文件
│   └── agent-{short-id}.jsonl            # Agent/Sidechain 会话
└── [其他项目目录...]
```

**命名约定**:
- 项目目录：绝对路径用连字符编码（`/home/yammi/repos/Frago` → `-home-yammi-repos-Frago`）
- 会话文件：`{session_uuid}.jsonl`（UUID 作为文件名）
- Agent 文件：`agent-{short_id}.jsonl`（短 ID 格式）

### 1.2 JSONL 记录类型

| 类型 | 字段标识 | 描述 |
|------|---------|------|
| `user` | `type: "user"` | 用户消息或工具结果 |
| `assistant` | `type: "assistant"` | 助手回复（可含工具调用） |
| `system` | `type: "system"` | 系统事件（错误、重试等） |
| `file-history-snapshot` | `type: "file-history-snapshot"` | 文件状态快照 |

### 1.3 关键字段定义

**通用字段**:
| 字段 | 类型 | 描述 |
|------|------|------|
| `uuid` | string | 记录唯一标识 |
| `sessionId` | UUID | 会话标识（关联同一对话） |
| `parentUuid` | UUID \| null | 父消息 ID（构建对话链） |
| `timestamp` | ISO 8601 | 记录创建时间 |
| `cwd` | string | 工作目录 |
| `gitBranch` | string | Git 分支 |
| `version` | string | Claude Code 版本 |

**消息字段**:
| 字段 | 类型 | 描述 |
|------|------|------|
| `message.role` | enum | `"user"` 或 `"assistant"` |
| `message.content` | string \| array | 消息内容或内容块数组 |
| `message.model` | string | 模型标识（仅 assistant） |
| `message.stop_reason` | enum | `"tool_use"`, `"end_turn"` 等 |
| `message.usage` | object | Token 使用统计 |

**工具调用字段**:
| 字段 | 类型 | 描述 |
|------|------|------|
| `tool_use.id` | string | 工具调用 ID |
| `tool_use.name` | string | 工具名称 |
| `tool_use.input` | object | 工具参数 |
| `tool_result.content` | string | 工具执行结果 |

**Agent/Sidechain 字段**:
| 字段 | 类型 | 描述 |
|------|------|------|
| `isSidechain` | boolean | 是否为 Agent 线程 |
| `agentId` | string | Agent 实例短 ID |
| `slug` | string | Agent 可读标识 |

### 1.4 会话 ID 获取方式

**决策**: 从 JSONL 文件中提取 `sessionId` 字段

**理由**:
- 每条记录都包含 `sessionId`，可靠性高
- 文件名与 sessionId 通常一致，但 agent 文件例外
- 通过 `parentUuid` 链可追溯完整对话历史

**考虑的替代方案**:
- 从文件名提取：不适用于 `agent-*.jsonl` 文件
- 从进程环境变量获取：Claude Code 未暴露此信息

---

## 2. Frago 现有架构分析

### 2.1 相关模块

| 模块 | 位置 | 职责 |
|------|------|------|
| Run 系统 | `src/frago/run/` | 会话管理、日志记录、上下文跟踪 |
| Agent 命令 | `src/frago/cli/agent_command.py` | 智能路由、流式执行 |
| GUI 系统 | `src/frago/gui/` | 桌面应用、历史记录 |

### 2.2 可复用的数据模型

**LogEntry** (`run/models.py`):
```python
class LogEntry(BaseModel):
    timestamp: datetime
    step: str
    status: LogStatus           # success | error | warning
    action_type: ActionType     # 9 种类型
    execution_method: ExecutionMethod  # 6 种方法
    data: Dict[str, Any]
    insights: Optional[List[InsightEntry]]
```

**决策**: 扩展现有 Run 系统，而非创建独立模块

**理由**:
- Run 系统已有完整的日志框架和 JSONL 存储
- 与现有 `frago run` 命令体系保持一致
- 复用 `LogEntry`、`InsightEntry` 等模型

### 2.3 会话关联难点解决方案

**问题**: `frago agent` 启动 Claude Code 子进程后，如何关联到正确的会话文件？

**决策**: 基于时间窗口 + 项目路径 + 文件监听的三重匹配

**方案细节**:
1. 在 `frago agent` 启动时记录启动时间戳 `T0`
2. 监听 `~/.claude/projects/{encoded_cwd}/` 目录的文件变化
3. 检测 `T0` 之后新创建或修改的 `.jsonl` 文件
4. 读取文件末尾记录，验证 `timestamp` 在 `[T0, T0+Δ]` 范围内
5. 提取 `sessionId` 并持续监听该文件

**考虑的替代方案**:
- 解析 Claude Code 进程输出：格式不稳定，易变
- 修改 Claude Code 配置：侵入性强，不可控

---

## 3. 技术选型

### 3.1 文件监听方案

**决策**: 使用 `watchdog` 库进行文件系统监听

**理由**:
- 跨平台支持（Linux inotify、macOS FSEvents、Windows）
- 纯 Python 实现，无额外依赖
- 成熟稳定，广泛使用

**考虑的替代方案**:
- `inotify` 直接调用：仅限 Linux
- 轮询方式：效率低，延迟高

### 3.2 数据解析方案

**决策**: 流式增量解析 JSONL

**理由**:
- 会话文件持续增长，全量读取效率低
- 记录文件偏移量，仅解析新增行
- 支持实时更新

### 3.3 输出展示方案

**决策**: 结构化终端输出 + 可选 JSON 模式

**理由**:
- 人类可读的格式化输出（默认）
- 机器可读的 JSON 输出（`--json` 参数）
- 与现有 Frago 命令风格一致

---

## 4. 目录结构设计

**决策**: `~/.frago/sessions/{agent_type}/{session_id}/`

**结构**:
```
~/.frago/
└── sessions/
    └── claude/                          # agent_type
        └── {session_id}/
            ├── metadata.json            # 会话元数据
            ├── steps.jsonl              # 解析后的步骤记录
            └── summary.json             # 会话摘要（执行完成后）
```

**理由**:
- 预留 agent_type 层级，支持未来扩展
- 与 Claude Code 原始文件隔离，避免污染
- JSONL 格式便于增量写入和流式读取

---

## 5. 待解决问题

### 5.1 并发会话隔离（已解决）

**问题**: 多个终端同时执行 `frago agent`，如何确保各自监控正确的会话？

**解决方案**:
- 每个 `frago agent` 进程独立记录启动时间戳
- 通过时间窗口过滤，只匹配自身启动后的新会话
- 在 `~/.frago/sessions/` 中使用不同的 session_id 目录隔离

### 5.2 文件格式变更容错（已解决）

**问题**: Claude Code 更新可能改变 JSONL 格式

**解决方案**:
- 使用防御性解析，未知字段忽略
- 关键字段缺失时记录警告，不中断运行
- 版本号字段（`version`）用于未来的格式适配
