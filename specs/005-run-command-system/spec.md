# Feature Specification: Run命令系统

**Feature Branch**: `005-run-command-system`
**Created**: 2025-11-21
**Status**: Draft
**Input**: User description: "添加run命令系统：包括CLI run子命令组和/frago.run slash命令，用于管理和执行AI主持的浏览器自动化任务"

## 澄清

### 会话 2025-11-21

- Q: `/frago.run` 与Recipe系统的关系是什么？ → A: `/frago.run` 不是因为Recipe能力不足，而是为Recipe创建提供探索和调研的上下文环境。它作为信息中心，支持：1) Recipe创建前的调研工作；2) 跨多个Recipe调用的上下文积累；3) 构建复杂Workflow时的信息组织。

- Q: run实例应该是事务型还是主题型？ → A: run实例应该是**主题型**而非事务型。例如"find-job-on-upwork"是一个主题，用户可能在不同时间多次执行相关任务，信息在同一主题run中持续积累和复用。避免因事务型设计导致工作目录积累大量重复的run实例。

- Q: `/frago.run` 如何处理现有的主题run实例？ → A: 每次启动时自动发现现有run实例，通过交互式菜单让用户选择：1) 继续现有run（复用已积累的信息）；2) 创建新run。需要提供 `uv run frago run set-context <run_id>` 命令固化工作环境配置，确保后续所有frago命令在正确的run空间中执行。

- Q: 数据如何积累？是否需要单独的save命令？ → A: **所有数据都通过 `log` 命令追加到execution.jsonl**。不需要save命令，因为：1) AI难以判断"何时该save"；2) 文件名管理容易出错；3) log的--data字段支持任意复杂JSON，包括大段文本、提取结果、分析结论等。outputs/目录仅用于可选的导出文件或生成的衍生文件（如CSV、Recipe草稿）。

- Q: 在日志中如何体现AI运行的recipe、命令、代码？ → A: 通过结构化的日志字段记录：1) `action_type`（操作类型）定义做什么（navigation/extraction/recipe_execution等）；2) `execution_method`（执行方法）定义怎么做（command/recipe/file/manual/analysis/tool）；3) `data`字段包含具体细节。**约束**：AI需要运行代码时，必须先保存为文件（存储在`scripts/`目录），日志中用`file`字段记录相对路径，**禁止在jsonl中直接存储代码内容**。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - AI主持的复杂任务执行与上下文积累 (Priority: P1)

用户需要执行需要AI持续探索和积累上下文的复杂浏览器自动化任务（如"调研Upwork上Python开发职位的薪资范围和技能要求，并创建提取这些信息的Recipe"）。这些任务涉及：
- 探索性调研工作（为创建Recipe做准备）
- 跨多个步骤的信息积累（如先分析页面结构，再测试选择器，最后固化为Recipe）

用户使用 `/frago.run "任务描述"` 命令，Claude Code会创建独立的run实例作为**信息中心**，在这个持久的上下文中通过CDP命令和Recipe调用逐步完成任务，并记录所有关键操作和发现。

**Why this priority**: 这是新系统的核心价值 - 提供一个持久的信息中心，让AI能够围绕一个run实例持续探索、积累上下文，支持Recipe的创建前调研以及复杂Workflow的构建。

**Independent Test**: 可以通过运行 `/frago.run "访问example.com并提取页面标题"` 来独立测试，验证系统能否创建工作空间、执行任务、记录日志并输出结果。

**Acceptance Scenarios**:

1. **Given** 用户在Claude Code中首次运行某主题任务，**When** 输入 `/frago.run "在Upwork上找Python职位"`，**Then** 系统分析任务描述提取主题（如"find-job-on-upwork"），列出现有run实例，通过交互式菜单询问用户是继续现有run还是创建新run
2. **Given** 用户选择创建新run，**When** 确认后，**Then** 系统创建主题型run实例（如`runs/find-job-on-upwork/`），调用 `set-context` 固化工作环境，AI开始执行任务并记录所有操作
3. **Given** 用户选择继续现有run，**When** 确认后，**Then** 系统调用 `set-context` 设置该run为当前上下文，AI读取历史日志和截图恢复上下文，继续执行新任务
4. **Given** 用户运行复杂任务，**When** AI需要调用高频操作（如提取YouTube字幕），**Then** AI能够发现并调用现有的Recipe加速执行
5. **Given** 任务执行过程中，**When** AI遇到需要用户决策的关键点（如"选择哪个搜索结果"），**Then** AI使用AskUserQuestion工具请求用户确认

---

### User Story 2 - 主题型run实例管理与自动发现 (Priority: P1)

run实例采用**主题型**而非事务型设计，每个主题（如"find-job-on-upwork"）对应一个持久的run目录。`/frago.run` 启动时自动发现现有run实例，通过交互式菜单让用户选择是复用现有主题还是创建新主题，避免工作目录积累大量重复的事务型run。

**Why this priority**: 主题型设计使信息在同一主题下持续积累和复用，避免重复探索。自动发现机制减少用户认知负担，交互式菜单确保用户明确控制信息的积累空间。这是实现"信息中心"价值的关键机制。

**Independent Test**: 可以通过运行 `/frago.run "在Upwork找工作"` 两次来测试，第二次应该自动发现第一次创建的run并提示用户选择。

**Acceptance Scenarios**:

1. **Given** `runs/` 目录下已存在多个主题run，**When** 用户运行 `/frago.run "在Upwork上搜索Python职位"`，**Then** 系统列出所有现有run实例及其主题描述，提供交互式菜单（"继续现有run" / "创建新run"）
2. **Given** 用户选择继续现有run "find-job-on-upwork"，**When** 确认选择，**Then** 系统调用 `uv run frago run set-context find-job-on-upwork` 固化工作环境配置
3. **Given** 工作环境已固化，**When** AI执行任何frago CLI命令（navigate、click、screenshot等），**Then** 所有操作自动在该run实例的目录空间中执行，日志追加到 `runs/find-job-on-upwork/logs/execution.jsonl`
4. **Given** 用户选择创建新run，**When** AI根据任务描述生成主题slug（如"analyze-github-langchain"），**Then** 系统创建 `runs/<主题slug>/` 目录及子目录（logs/、screenshots/、scripts/、outputs/），并调用 `set-context` 设置为当前工作空间

---

### User Story 3 - CLI run子命令组 (Priority: P2)

开发者或高级用户可以通过 `uv run frago run <subcommand>` 直接管理运行实例的生命周期，包括初始化、记录日志（含数据）、保存截图。这些命令提供统一的接口，避免AI的随机性导致的数据格式不一致。

**Why this priority**: 提供标准化的工具接口，确保日志和数据格式一致性，同时也让用户能够手动管理和调试运行实例。

**Independent Test**: 可以通过手动执行 `uv run frago run init "测试任务"`、`uv run frago run set-context <run_id>` 和 `uv run frago run log --step "测试" --status "success" --action-type "analysis" --execution-method "manual" --data '{}'` 来测试，验证命令能正确创建目录和记录数据。

**Acceptance Scenarios**:

1. **Given** 用户需要创建新run，**When** 执行 `uv run frago run init "任务描述"`，**Then** 系统根据任务描述生成主题slug，创建 `runs/<主题slug>/` 目录及子目录（logs/、screenshots/、scripts/、outputs/），返回run_id
2. **Given** 用户需要固化工作环境，**When** 执行 `uv run frago run set-context <run_id>`，**Then** 系统将该run_id写入配置文件（如`.frago/current_run`），后续所有frago命令自动在该run空间中执行
3. **Given** 工作环境已设置，**When** AI执行 `uv run frago run log --step "提取到5个职位" --status "success" --action-type "extraction" --execution-method "command" --data '{"command": "uv run frago recipe run ...", "jobs": [...], "total": 5}'`，**Then** 日志（包含所有字段和提取数据）以JSONL格式追加到当前run的execution.jsonl
4. **Given** 工作环境已设置，**When** 执行 `uv run frago run screenshot "搜索结果页面"`，**Then** 截图自动保存到当前run的screenshots目录，文件名自动编号
5. **Given** 用户需要导出数据，**When** 手动或通过脚本从execution.jsonl提取数据，**Then** 可以生成CSV、JSON等格式文件保存到outputs/目录（可选）

---

### User Story 4 - 清理过时的视频制作命令 (Priority: P3)

删除5个绑定特定场景的视频制作slash commands（/frago.start、/frago.storyboard、/frago.generate、/frago.evaluate、/frago.merge），将Frago的定位从"视频制作工具"转变为"AI驱动的多运行时自动化基建"（支持Chrome CDP、Python、Shell三种运行时）。

**Why this priority**: 这是架构清理工作，优先级较低但对项目定位很重要。删除这些命令后，未来如需视频制作功能可以基于Recipe系统重新实现。

**Independent Test**: 可以通过尝试执行这些已删除的命令来验证，确认它们不再可用。

**Acceptance Scenarios**:

1. **Given** 用户尝试使用旧命令，**When** 输入 `/frago.start`、`/frago.storyboard` 等，**Then** 系统提示命令不存在
2. **Given** 文档需要更新，**When** 查看用户文档和CLAUDE.md，**Then** 所有关于视频制作pipeline的描述已被移除

---

### Edge Cases

- 当AI生成的主题slug与现有run实例冲突时，系统如何处理？（这正是主题型设计的预期行为，系统应提示用户"发现相似主题，是否继续？"）
- 当用户任务描述模糊导致无法提取明确主题时，系统如何处理？（AI使用交互式菜单请求用户确认主题名称）
- 当执行日志文件过大时（超过100MB），系统如何处理？（自动轮转日志文件，按时间戳分段）
- 当AI执行调研失败或中途中断时，run实例的状态如何标记？（在logs中记录失败状态和原因，不影响run实例的持久性）
- 当用户同时运行多个 `/frago.run` 任务（不同主题）时，系统如何避免冲突？（每个run有独立目录和ID，且通过 `set-context` 明确当前工作空间）
- 当`projects/`目录积累过多历史运行实例时，如何清理？（提供 `uv run frago run archive <run_id>` 命令标记为archived状态，不在自动发现列表中显示）
- 当用户在不同AI会话中继续同一个run时，如何恢复上下文？（AI通过读取logs/execution.jsonl和已有的screenshots重建工作上下文）
- 当run实例中积累的信息用于创建Recipe后，原run实例如何标记？（可选在日志中添加recipe_created标记记录关联关系）
- 当`.frago/current_project`配置文件不存在或指向的run已删除时，命令如何处理？（提示用户使用 `set-context` 设置工作环境，或自动触发run选择菜单）

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统必须提供 `/frago.run` slash命令，接受纯语义任务描述作为输入
- **FR-002**: 系统必须在 `projects/` 目录下为每个主题创建运行实例目录，格式为 `projects/<主题slug>/`（主题型，如`projects/find-job-on-upwork/`），而非基于时间戳的事务型目录
- **FR-003**: 运行实例目录必须包含四个子目录：`logs/`（执行日志）、`screenshots/`（截图）、`scripts/`（AI生成的执行脚本）、`outputs/`（可选，用于手动导出文件或生成的衍生文件，如CSV、Recipe草稿）
- **FR-004**: 系统必须提供 `uv run frago run init <description>` 命令，根据任务描述智能生成主题slug，创建新run实例并返回run_id
- **FR-016**: `/frago.run` 启动时必须自动扫描 `projects/` 目录发现所有现有run实例，提取其主题和描述信息
- **FR-017**: 系统必须通过交互式菜单（AskUserQuestion）向用户展示现有run列表，提供"继续现有run"和"创建新run"选项
- **FR-018**: 系统必须提供 `uv run frago run set-context <run_id>` 命令，将run_id写入配置文件（如`.frago/current_project`），固化当前工作环境
- **FR-019**: 所有 `uv run frago run` 子命令（log、screenshot等）必须自动从配置文件读取当前run上下文，无需每次手动指定run_id
- **FR-005**: 系统必须提供 `uv run frago run log --step <step> --status <status> --action-type <type> --execution-method <method> --data <json>` 命令，以JSONL格式记录结构化日志。这是**唯一**的数据记录机制，--data字段支持任意复杂JSON（包括大段文本、提取结果、分析结论等）
- **FR-006**: 系统必须提供 `uv run frago run screenshot <description>` 命令，自动编号并保存截图到当前run的screenshots目录
- **FR-008**: `/frago.run` slash命令执行时必须使用 `uv run frago run` 子命令记录所有关键操作，避免直接修改文件
- **FR-009**: 系统必须删除以下5个slash命令文件：`/frago.start`、`/frago.storyboard`、`/frago.generate`、`/frago.evaluate`、`/frago.merge`
- **FR-010**: AI在执行 `/frago.run` 时必须能够调用 `uv run frago recipe list --format json` 发现可用Recipe，并使用 `recipe run` 加速高频操作
- **FR-014**: run实例必须支持跨多次AI会话的上下文持久化，允许用户在不同时间继续同一个run任务并访问之前积累的信息
- **FR-015**: 日志系统必须记录AI的探索过程和决策依据，包括页面结构分析、选择器测试结果等调研信息，便于后续创建Recipe时参考
- **FR-022**: `/frago.run` slash命令文档必须明确说明：1) 如何通过log命令的--data字段记录任意复杂数据；2) outputs/目录的可选性；3) 数据全部存储在execution.jsonl中的设计原理
- **FR-011**: 日志记录必须包含以下字段：
  - `timestamp`（ISO时间戳）
  - `step`（步骤描述）
  - `status`（枚举：success/error/warning）
  - `action_type`（操作类型，枚举：navigation/extraction/interaction/screenshot/recipe_execution/data_processing/analysis/user_interaction/other）
  - `execution_method`（执行方法，枚举：command/recipe/file/manual/analysis/tool）
  - `data`（JSON对象，包含操作详情）
- **FR-012**: 截图文件命名必须包含步骤编号（001、002...）和用户提供的描述（slug化）
- **FR-013**: 系统必须在run_id冲突时自动重新生成随机ID（最多重试3次）
- **FR-023**: AI在执行过程中需要运行代码时，必须先将代码保存为文件（存储在`scripts/`目录），禁止在日志的data字段中直接存储代码内容。日志中使用`file`字段记录相对路径（如`"file": "scripts/extract_jobs.py"`）

### Key Entities

- **Run实例**: 一个主题的完整信息中心，持久化存储该主题下所有任务的执行历史和积累的知识
  - 属性：run_id（字符串，主题slug，如"find-job-on-upwork"）、theme_description（主题描述）、created_at（首次创建时间戳）、last_accessed（最后访问时间戳）、status（枚举：active/archived）
  - 关系：包含多个日志条目（跨多次会话）、多个截图、可选的导出文件（outputs/目录）
  - 特点：主题型而非事务型，同一主题的信息持续积累，所有数据通过execution.jsonl记录

- **日志条目**: 单个执行步骤的结构化记录
  - 属性：
    - `timestamp`（ISO时间戳）
    - `step`（步骤描述）
    - `status`（枚举：success/error/warning）
    - `action_type`（操作类型）：navigation、extraction、interaction、screenshot、recipe_execution、data_processing、analysis、user_interaction、other
    - `execution_method`（执行方法）：command、recipe、file、manual、analysis、tool
    - `data`（JSON对象，包含操作详情、提取结果、分析结论等任意复杂数据）
  - 格式：JSONL（每行一个独立的JSON对象）
  - 说明：data字段是唯一的数据存储机制，支持大段文本、数组、嵌套对象等任意JSON结构
  - 约束：当`execution_method`为`file`时，必须在data中包含`file`字段记录脚本文件的相对路径，禁止在data中直接存储代码内容

- **截图记录**: 任务执行过程中捕获的页面快照
  - 属性：sequence_number（步骤编号）、description（用户描述）、file_path（相对路径）、timestamp（时间戳）

### 日志结构示例

以下是不同 `execution_method` 的日志记录示例：

#### command - CLI 命令执行
```json
{
  "timestamp": "2025-11-21T10:30:00Z",
  "step": "导航到Upwork搜索页",
  "status": "success",
  "action_type": "navigation",
  "execution_method": "command",
  "data": {
    "command": "uv run frago navigate https://upwork.com/search",
    "exit_code": 0,
    "output": "导航成功"
  }
}
```

#### recipe - Recipe 调用
```json
{
  "timestamp": "2025-11-21T10:32:00Z",
  "step": "提取YouTube视频字幕",
  "status": "success",
  "action_type": "recipe_execution",
  "execution_method": "recipe",
  "data": {
    "recipe_name": "youtube_extract_video_transcript",
    "params": {"url": "https://youtube.com/watch?v=xxx"},
    "output": {
      "title": "AI教育革命",
      "transcript": "..."
    }
  }
}
```

#### file - 执行脚本文件
```json
{
  "timestamp": "2025-11-21T10:35:00Z",
  "step": "过滤薪资大于$50的职位",
  "status": "success",
  "action_type": "data_processing",
  "execution_method": "file",
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

#### manual - 需要人工操作
```json
{
  "timestamp": "2025-11-21T10:40:00Z",
  "step": "等待用户登录Upwork",
  "status": "success",
  "action_type": "user_interaction",
  "execution_method": "manual",
  "data": {
    "instruction": "请手动登录Upwork账号并完成验证",
    "confirmed": true,
    "duration_seconds": 120
  }
}
```

#### analysis - AI 推理/分析
```json
{
  "timestamp": "2025-11-21T10:42:00Z",
  "step": "分析页面DOM结构",
  "status": "success",
  "action_type": "analysis",
  "execution_method": "analysis",
  "data": {
    "observation": "页面使用React框架，职位列表通过异步加载",
    "conclusion": "需要等待2秒后再提取数据，使用选择器：.job-tile-list > div",
    "confidence": "high"
  }
}
```

#### tool - AI 工具调用
```json
{
  "timestamp": "2025-11-21T10:45:00Z",
  "step": "请求用户选择目标职位",
  "status": "success",
  "action_type": "user_interaction",
  "execution_method": "tool",
  "data": {
    "tool_name": "AskUserQuestion",
    "question": "找到3个匹配的职位，选择哪个查看详情？",
    "options": ["Python后端开发", "全栈工程师", "数据工程师"],
    "answer": "Python后端开发"
  }
}
```

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 用户可以通过 `/frago.run` 命令在5分钟内完成中等复杂度的浏览器自动化任务（如搜索并提取前5个结果）
- **SC-002**: 每个run实例的所有日志、截图和结果文件都能被正确隔离，不同任务之间无数据污染
- **SC-003**: AI记录的日志必须是结构化的JSONL格式，100%可被程序解析（无格式错误）
- **SC-004**: 截图文件命名遵循统一规范（`<序号>_<描述slug>.png`），90%以上的截图描述清晰可读
- **SC-005**: 用户可以在 `runs/` 目录中轻松找到任意历史任务的完整执行记录（通过目录名和时间戳）
- **SC-006**: 系统删除旧的5个视频制作命令后，用户不再对Frago的定位产生"仅用于视频制作"的误解
- **SC-007**: AI在执行 `/frago.run` 时能够识别并使用现有Recipe，减少30%以上的重复LLM推理（相比完全手动执行）
- **SC-008**: 用户可以基于run实例中积累的调研信息（日志、截图、分析结果），在后续通过 `/frago.recipe create` 成功创建有效的Recipe，无需重新探索
- **SC-009**: 用户第二次执行相同主题任务时，系统自动发现现有run实例并通过交互式菜单提示，90%以上的情况下用户选择复用现有run而非创建重复run
- **SC-010**: 通过 `set-context` 机制，AI在单个run会话中执行的所有frago命令（20+次操作）100%正确地记录到同一个run实例目录中，无路径错误

## Assumptions

- 用户已经安装了frago CLI工具并配置了Chrome CDP连接
- `projects/` 目录默认位于项目根目录，用户对该目录有读写权限
- run_id采用主题slug格式（如"upwork-python-jobs"），由AI生成简洁的英文短句（3-5个词）
- JSONL日志文件在单个run实例中不会超过100MB（超过后需要日志轮转）
- 用户了解 `/frago.run` 的核心价值：作为信息中心支持探索、调研，为Recipe创建收集信息
- 截图格式默认为PNG，分辨率跟随浏览器窗口设置
- run实例是主题型的，同一主题的信息持续积累，用户在不同时间执行相同主题任务时应复用同一run实例
- `.frago/current_project` 配置文件用于存储当前工作环境，所有frago CLI命令从此文件读取当前run上下文

## Out of Scope

- 本功能不包括run实例的Web UI管理界面（仅提供CLI）
- 不包括run实例之间的依赖管理或编排功能（如"run B依赖run A的结果"）
- 不包括run实例的远程共享或协作功能（仅本地存储）
- 不包括自动清理或归档历史run实例的策略（需要用户手动管理或使用单独的clean命令）
- 不包括将视频制作功能迁移到Recipe系统的工作（仅删除旧命令）
- 不包括run实例的性能监控或资源使用统计

## Dependencies

- 依赖现有的 `uv run frago` CLI框架和CDP连接功能
- 依赖现有的Recipe系统（`uv run frago recipe list/run` 命令）
- 依赖Claude Code的slash command机制和AskUserQuestion工具
- `/frago.run` 命令需要读取现有的CDP工具清单和Recipe系统元数据
