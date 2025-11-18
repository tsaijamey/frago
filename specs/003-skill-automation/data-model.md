# Data Model: 技能自动化生成系统

**Feature**: 003-skill-automation
**Date**: 2025-11-18
**Purpose**: 定义配方系统的核心实体、关系和数据结构

---

## 核心实体

### 1. Recipe（配方）

**描述**: 可复用的浏览器操作脚本，存储为JavaScript文件。

**属性**:

| 字段 | 类型 | 必需 | 描述 | 示例 |
|------|------|------|------|------|
| `name` | `str` | ✅ | 配方唯一标识符（文件名不含扩展名） | `youtube_extract_subtitles` |
| `platform` | `str` | ✅ | 目标平台/网站 | `youtube`, `github`, `twitter` |
| `action` | `str` | ✅ | 操作类型 | `extract`, `collect`, `clone`, `monitor` |
| `description` | `str` | ✅ | 功能简述 | "提取YouTube视频完整字幕内容" |
| `script_path` | `Path` | ✅ | JavaScript脚本路径 | `src/auvima/recipes/youtube_extract_subtitles.js` |
| `doc_path` | `Path` | ✅ | 知识文档路径 | `src/auvima/recipes/youtube_extract_subtitles.md` |
| `created_at` | `datetime` | ✅ | 创建时间 | `2025-11-18T10:30:00Z` |
| `updated_at` | `datetime` | ✅ | 最后更新时间 | `2025-11-18T15:45:00Z` |
| `version` | `int` | ✅ | 版本号（更新次数） | `1`, `2`, `3` |
| `selectors` | `List[Selector]` | ✅ | 使用的DOM选择器列表 | 见下方Selector实体 |
| `prerequisites` | `List[str]` | ❌ | 前置条件描述 | `["已登录YouTube账户", "视频正在播放"]` |
| `tags` | `List[str]` | ❌ | 标签（用于分类） | `["video", "text-extraction", "social-media"]` |

**验证规则**:
- `name` 必须匹配正则 `^[a-z0-9_]+$`（小写字母、数字、下划线）
- `platform` 建议使用标准平台缩写（见research.md §3）
- `action` 建议使用标准动词（extract/collect/clone/monitor/analyze）
- `script_path` 和 `doc_path` 必须在 `src/auvima/recipes/` 目录下
- `version` 初始值为1，每次更新自增

**状态转换**:
```
创建 → 验证通过 → 活跃
活跃 → 更新请求 → 更新中 → 验证通过 → 活跃
活跃 → 标记废弃 → 已废弃
```

---

### 2. Selector（选择器）

**描述**: DOM元素选择器，包含稳定性评估和降级策略。

**属性**:

| 字段 | 类型 | 必需 | 描述 | 示例 |
|------|------|------|------|------|
| `selector` | `str` | ✅ | CSS选择器字符串 | `[aria-label="显示字幕"]` |
| `priority` | `int` | ✅ | 稳定性优先级（1-5） | `5`（ARIA）, `3`（class）, `1`（生成类名） |
| `type` | `SelectorType` | ✅ | 选择器类型枚举 | `ARIA`, `DATA_ATTR`, `ID`, `CLASS`, `TAG` |
| `element_description` | `str` | ✅ | 元素描述（用于文档） | "字幕按钮" |
| `fallback_selector` | `Optional[str]` | ❌ | 降级选择器 | `#subtitle-button` |
| `is_fragile` | `bool` | ✅ | 是否为脆弱选择器 | `false`（ARIA）, `true`（生成类名） |

**枚举: SelectorType**:
```python
class SelectorType(Enum):
    ARIA = "aria"              # aria-label, role (优先级5)
    DATA_ATTR = "data"         # data-* (优先级5)
    STABLE_ID = "id"           # 非动态ID (优先级4)
    SEMANTIC_CLASS = "class"   # BEM类名 (优先级3)
    SEMANTIC_TAG = "tag"       # HTML5标签 (优先级3)
    STRUCTURE = "structure"    # XPath/组合 (优先级2)
    GENERATED = "generated"    # 自动生成 (优先级1)
```

**验证规则**:
- `priority` 必须在1-5范围内
- `type` 为 `GENERATED` 时，`is_fragile` 必须为 `true`
- 如果 `is_fragile=true`，生成的知识文档必须在"注意事项"标注

**关系**:
- 一个 `Recipe` 可包含多个 `Selector`
- `Selector` 按 `priority` 降序排列，用于生成降级逻辑

---

### 3. ExplorationSession（探索会话）

**描述**: 交互式探索过程的记录，用于生成配方脚本。

**属性**:

| 字段 | 类型 | 必需 | 描述 | 示例 |
|------|------|------|------|------|
| `session_id` | `str` | ✅ | 会话唯一ID（UUID） | `550e8400-e29b-41d4-a716-446655440000` |
| `user_description` | `str` | ✅ | 用户原始需求描述 | "在YouTube视频页面提取完整字幕内容" |
| `target_url` | `str` | ✅ | 探索的目标页面URL | `https://www.youtube.com/watch?v=...` |
| `steps` | `List[ExplorationStep]` | ✅ | 探索步骤序列 | 见下方ExplorationStep实体 |
| `created_at` | `datetime` | ✅ | 会话开始时间 | `2025-11-18T10:30:00Z` |
| `completed_at` | `Optional[datetime]` | ❌ | 会话完成时间 | `2025-11-18T10:35:00Z` |
| `status` | `SessionStatus` | ✅ | 会话状态 | `IN_PROGRESS`, `COMPLETED`, `FAILED` |
| `interaction_count` | `int` | ✅ | 用户交互次数 | `2`（不超过3） |
| `generated_recipe_name` | `Optional[str]` | ❌ | 生成的配方名称 | `youtube_extract_subtitles` |

**枚举: SessionStatus**:
```python
class SessionStatus(Enum):
    INITIALIZING = "initializing"  # 初始化
    IN_PROGRESS = "in_progress"    # 探索中
    WAITING_USER = "waiting_user"  # 等待用户输入
    COMPLETED = "completed"        # 成功完成
    FAILED = "failed"              # 失败（无法定位元素或超过3次交互）
    CANCELLED = "cancelled"        # 用户取消
```

**验证规则**:
- `interaction_count` 不得超过3（符合用户故事约束）
- `status=COMPLETED` 时，`completed_at` 和 `generated_recipe_name` 必须存在
- `steps` 至少包含1个步骤

**关系**:
- 一个 `ExplorationSession` 生成一个 `Recipe`
- `ExplorationSession` 可被序列化为JSON存储（用于调试或回放）

---

### 4. ExplorationStep（探索步骤）

**描述**: 探索会话中的单个操作步骤。

**属性**:

| 字段 | 类型 | 必需 | 描述 | 示例 |
|------|------|------|------|------|
| `step_number` | `int` | ✅ | 步骤序号（从1开始） | `1`, `2`, `3` |
| `action` | `StepAction` | ✅ | 操作类型 | `NAVIGATE`, `CLICK`, `EXTRACT`, `WAIT` |
| `target_selector` | `Optional[Selector]` | ❌ | 目标元素选择器 | 见Selector实体 |
| `parameters` | `Dict[str, Any]` | ❌ | 操作参数 | `{"url": "...", "timeout": 5000}` |
| `screenshot_path` | `Optional[Path]` | ❌ | 截图路径（如有） | `/tmp/exploration_step1.png` |
| `result` | `Optional[str]` | ❌ | 步骤执行结果 | "成功点击按钮" 或 "元素未找到" |
| `user_confirmed` | `bool` | ✅ | 用户是否确认此步骤 | `true` |

**枚举: StepAction**:
```python
class StepAction(Enum):
    NAVIGATE = "navigate"      # 导航到URL
    CLICK = "click"            # 点击元素
    EXTRACT = "extract"        # 提取内容
    WAIT = "wait"              # 等待元素或延迟
    SCROLL = "scroll"          # 滚动页面
    INPUT = "input"            # 输入文本
    SCREENSHOT = "screenshot"  # 截图（用于交互确认）
```

**验证规则**:
- `action=NAVIGATE` 时，`parameters["url"]` 必需
- `action=CLICK|EXTRACT` 时，`target_selector` 必需
- `action=WAIT` 时，`parameters["timeout"]` 或 `parameters["selector"]` 必需
- `user_confirmed=true` 的步骤才会写入最终配方脚本

**关系**:
- 多个 `ExplorationStep` 组成一个 `ExplorationSession`
- `ExplorationStep` 顺序执行，步骤依赖前一步的页面状态

---

### 5. KnowledgeDocument（知识文档）

**描述**: 配方的配套Markdown文档，包含6个标准章节。

**属性**:

| 字段 | 类型 | 必需 | 描述 | 示例 |
|------|------|------|------|------|
| `recipe_name` | `str` | ✅ | 关联的配方名称 | `youtube_extract_subtitles` |
| `sections` | `Dict[str, str]` | ✅ | 6个章节内容 | `{"功能描述": "...", "使用方法": "..."}` |
| `update_history` | `List[UpdateRecord]` | ✅ | 更新历史记录 | 见下方UpdateRecord实体 |
| `created_at` | `datetime` | ✅ | 文档创建时间 | `2025-11-18T10:30:00Z` |
| `last_updated` | `datetime` | ✅ | 最后更新时间 | `2025-11-18T15:45:00Z` |

**标准章节枚举**:
```python
class DocSection(Enum):
    DESCRIPTION = "功能描述"
    USAGE = "使用方法"
    PREREQUISITES = "前置条件"
    OUTPUT = "预期输出"
    NOTES = "注意事项"
    HISTORY = "更新历史"
```

**验证规则**:
- `sections` 必须包含所有6个标准章节
- `update_history` 按时间倒序排列（最新在前）

**关系**:
- 一个 `Recipe` 对应一个 `KnowledgeDocument`
- `KnowledgeDocument` 通过 `recipe_name` 关联 `Recipe`

---

### 6. UpdateRecord（更新记录）

**描述**: 配方更新历史的单条记录。

**属性**:

| 字段 | 类型 | 必需 | 描述 | 示例 |
|------|------|------|------|------|
| `date` | `datetime` | ✅ | 更新日期 | `2025-11-18T15:45:00Z` |
| `reason` | `str` | ✅ | 更新原因 | "YouTube改版导致字幕按钮选择器失效" |
| `changes` | `str` | ✅ | 主要变更内容 | "更新按钮选择器从 `.old-selector` 改为 `.new-selector`" |
| `tested_on` | `Optional[str]` | ❌ | 测试环境说明 | "Chrome 120, YouTube 2025-11版本" |

**验证规则**:
- `reason` 和 `changes` 不得为空
- 初始版本的 `UpdateRecord` 中 `reason` 为 "初始版本"

---

## 实体关系图

```
Recipe (1) ←→ (1) KnowledgeDocument
   ↓
   contains (1..*)
   ↓
Selector

ExplorationSession (1) → generates (1) Recipe
   ↓
   contains (1..*)
   ↓
ExplorationStep
   ↓
   uses (0..1)
   ↓
Selector

KnowledgeDocument (1) ←→ (*) UpdateRecord
```

---

## 数据存储策略

### 文件系统布局

```
src/auvima/recipes/
├── youtube_extract_subtitles.js      # Recipe脚本
├── youtube_extract_subtitles.md      # KnowledgeDocument
├── github_clone_repo_info.js
├── github_clone_repo_info.md
└── ...

[临时目录]/explorations/
├── 550e8400-e29b-41d4-a716-446655440000.json  # ExplorationSession序列化
└── ...
```

### 元数据索引（可选）

为支持快速列出和搜索配方，可在 `src/auvima/recipes/.index.json` 维护元数据索引：

```json
{
  "recipes": [
    {
      "name": "youtube_extract_subtitles",
      "platform": "youtube",
      "action": "extract",
      "description": "提取YouTube视频完整字幕内容",
      "created_at": "2025-11-18T10:30:00Z",
      "updated_at": "2025-11-18T15:45:00Z",
      "version": 2,
      "tags": ["video", "text-extraction"]
    }
  ],
  "last_updated": "2025-11-18T15:45:00Z"
}
```

**维护策略**:
- 配方创建/更新时自动更新索引
- 索引损坏时可通过扫描 `.js` 和 `.md` 文件重建

---

## 数据验证规范

### Pydantic模型示例

```python
from pydantic import BaseModel, Field, validator
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
from enum import Enum

class SelectorType(str, Enum):
    ARIA = "aria"
    DATA_ATTR = "data"
    STABLE_ID = "id"
    SEMANTIC_CLASS = "class"
    SEMANTIC_TAG = "tag"
    STRUCTURE = "structure"
    GENERATED = "generated"

class Selector(BaseModel):
    selector: str
    priority: int = Field(ge=1, le=5)
    type: SelectorType
    element_description: str
    fallback_selector: Optional[str] = None
    is_fragile: bool = False

    @validator('is_fragile', always=True)
    def check_fragile_for_generated(cls, v, values):
        if values.get('type') == SelectorType.GENERATED and not v:
            raise ValueError('Generated selectors must be marked as fragile')
        return v

class Recipe(BaseModel):
    name: str = Field(regex=r'^[a-z0-9_]+$')
    platform: str
    action: str
    description: str
    script_path: Path
    doc_path: Path
    created_at: datetime
    updated_at: datetime
    version: int = Field(ge=1)
    selectors: List[Selector]
    prerequisites: List[str] = []
    tags: List[str] = []

    @validator('script_path', 'doc_path')
    def check_paths_in_recipes_dir(cls, v):
        if 'recipes' not in str(v):
            raise ValueError(f'Path must be in recipes directory: {v}')
        return v
```

---

## 下一步

生成 `contracts/` 目录中的JSON Schema文件，形式化数据结构规范。
