# Data Model: frago init 命令与 Recipe 资源安装

## 实体定义

### ResourceType

资源类型枚举

| 值 | 描述 | 安装位置 |
|----|------|----------|
| `command` | Claude Code slash 命令 | `~/.claude/commands/` |
| `skill` | Claude Code skill | `~/.claude/skills/` |
| `recipe` | 示例 recipe | `~/.frago/recipes/` |

### ResourceFile

单个资源文件

| 字段 | 类型 | 描述 |
|------|------|------|
| `name` | string | 文件名（如 `frago.run.md`） |
| `source_path` | Path | 包内源路径 |
| `target_path` | Path | 安装目标路径 |
| `resource_type` | ResourceType | 资源类型 |
| `size_bytes` | int | 文件大小 |

### InstallResult

安装操作结果

| 字段 | 类型 | 描述 |
|------|------|------|
| `installed` | list[str] | 已安装的文件路径列表 |
| `skipped` | list[str] | 跳过的文件路径列表（已存在） |
| `errors` | list[str] | 错误信息列表 |
| `resource_type` | ResourceType | 资源类型 |

### ResourceStatus

资源安装状态

| 字段 | 类型 | 描述 |
|------|------|------|
| `commands` | InstallResult | slash 命令安装状态 |
| `skills` | InstallResult | skills 安装状态 |
| `recipes` | InstallResult | recipe 安装状态 |
| `frago_version` | string | frago 版本号 |
| `install_time` | datetime | 安装时间 |

---

## 目录结构

### 包内资源目录（源）

```text
src/frago/resources/
├── __init__.py
├── commands/
│   ├── frago.run.md
│   ├── frago.recipe.md
│   ├── frago.exec.md
│   └── frago.test.md
├── skills/
│   └── frago-browser-automation/
│       └── SKILL.md
└── recipes/
    ├── atomic/
    │   ├── chrome/
    │   │   ├── youtube_extract_video_transcript.md
    │   │   └── youtube_extract_video_transcript.js
    │   └── system/
    │       ├── clipboard_read.md
    │       └── clipboard_read.py
    └── workflows/
        ├── upwork_batch_extract.md
        └── upwork_batch_extract.py
```

### 用户安装目录（目标）

```text
~/.claude/
├── commands/
│   ├── frago.run.md
│   ├── frago.recipe.md
│   ├── frago.exec.md
│   └── frago.test.md
└── skills/
    └── frago-browser-automation/
        └── SKILL.md

~/.frago/
├── config.yaml          # 现有：frago 配置
└── recipes/
    ├── atomic/
    │   ├── chrome/
    │   └── system/
    └── workflows/
```

---

## 状态转换

### init 命令执行流程

```text
[开始]
    │
    ▼
[检查依赖] ──失败──► [安装依赖] ──失败──► [错误退出]
    │                    │
    ▼ 成功               ▼ 成功
[安装资源]◄──────────────┘
    │
    ├─► [安装 commands] ──► 始终覆盖
    ├─► [安装 skills] ──► 始终覆盖
    └─► [安装 recipes] ──► 仅首次
    │
    ▼
[配置认证]
    │
    ▼
[保存配置]
    │
    ▼
[显示摘要]
    │
    ▼
[完成]
```

### 文件覆盖决策

```text
目标文件是否存在?
    │
    ├── 否 ──► 复制
    │
    └── 是
         │
         └── 是系统资源? (commands/skills)
              │
              ├── 是 ──► 覆盖
              │
              └── 否 (recipe)
                   │
                   └── 跳过
```

---

## 验证规则

### ResourceFile 验证

- `name` 必须非空
- `source_path` 必须存在
- `target_path` 父目录必须可创建

### InstallResult 验证

- `installed` 和 `skipped` 中的路径必须唯一
- `errors` 中的错误必须包含文件路径

---

## 配置扩展

扩展现有 `Config` 模型（`src/frago/init/models.py`）:

```python
class Config(BaseModel):
    # 现有字段
    auth_method: str
    init_completed: bool
    # ... 其他现有字段

    # 新增字段
    resources_installed: bool = False
    resources_version: str = ""
    last_resource_update: Optional[datetime] = None
```
