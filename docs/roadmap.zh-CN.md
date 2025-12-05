# Frago 项目进展

## 项目状态

📍 **当前阶段**：GUI 和会话监控完成，进入开发者体验增强阶段

**已完成**：
- ✅ 原生 CDP 协议层（~3,763 行 Python）
- ✅ CLI 工具和分组命令系统
- ✅ Recipe 元数据驱动架构（多运行时支持）
- ✅ Run 命令系统（主题型任务管理）
- ✅ Init 命令（依赖检查、资源安装）
- ✅ 环境变量支持（三级配置优先级）
- ✅ GUI 应用模式（pywebview 桌面界面）
- ✅ Agent 会话监控（Claude Code 会话解析和持久化）

**技术亮点**：
- 🏆 原生 CDP（无 Playwright/Selenium 依赖，~2MB）
- 🏆 AI-First 设计（Claude AI 主持任务执行和工作流编排）
- 🏆 Recipe 加速系统（固化高频操作，避免重复 AI 推理）
- 🏆 Run 系统（AI 的工作记忆，持久化上下文）
- 🏆 环境变量系统（敏感信息管理 + Workflow 上下文共享）
- 🏆 会话监控（使用 watchdog 实时跟踪 Claude Code 会话）

---

## 已完成功能 ✅

### Feature 001-002: 核心 CDP 实现

- [x] **原生 CDP 协议层**（~3,763 行 Python 代码）
  - WebSocket 直连 Chrome（无 Node.js 中继）
  - 智能重试机制（代理环境优化）
  - 完整命令模块（page/screenshot/runtime/input/scroll/wait/zoom/status/visual_effects）
  - 类型安全配置系统

- [x] **CLI 工具**（Click 框架）
  - `uv run frago <command>` - 所有 CDP 功能统一接口
  - 代理配置支持（环境变量 + CLI 参数）
  - 功能映射验证工具

- [x] **跨平台 Chrome 启动器**
  - macOS/Linux 支持
  - 自动 profile 初始化
  - 窗口尺寸控制

### Feature 003-004: Recipe 系统

- [x] **Recipe 元数据驱动架构**
  - 元数据解析器（YAML frontmatter）
  - Recipe 注册表（三级查找路径：项目 > 用户 > 示例）
  - Recipe 执行器（chrome-js/python/shell 运行时）
  - 输出处理器（stdout/file/clipboard）
  - CLI 命令组（list/info/run/copy）

- [x] **AI 可理解字段设计**
  - `description`: 功能描述
  - `use_cases`: 使用场景
  - `tags`: 分类标签
  - `output_targets`: 输出目标

- [x] **Recipe 存储结构**
  - 代码与资源分离
  - 示例 Recipe 位于 `examples/`
  - 描述性命名规范
  - 配套元数据文档

### Feature 005: Run 命令系统

- [x] **主题型任务管理**
  - Run 实例创建和发现
  - RapidFuzz 模糊匹配（80% 阈值）
  - 跨会话上下文持久化
  - 生命周期：init → execute → log → archive

- [x] **结构化 JSONL 日志**
  - 100% 可程序解析
  - 完整操作历史追踪
  - 错误日志含堆栈信息
  - 可审计执行记录

- [x] **持久化上下文存储**
  - `projects/<run_id>/` 目录结构
  - `logs/execution.jsonl` - 完整操作历史
  - `screenshots/` - 带时间戳截图
  - `scripts/` - 已验证脚本
  - `outputs/` - 结果文件

- [x] **AI 主持任务执行**
  - `/frago.run` slash 命令集成
  - Run 实例自动发现
  - Recipe 选择和编排

### Feature 006-007: Init 命令系统

- [x] **依赖检查和安装**
  - 并行检测 Node.js 和 Claude Code
  - 智能安装缺失组件
  - 安装验证机制

- [x] **认证配置**
  - 官方 Claude Code 登录
  - 自定义 API 端点（DeepSeek、阿里云、Kimi、MiniMax）
  - 互斥选择设计

- [x] **资源安装**
  - Slash 命令安装到 `~/.claude/commands/`
  - 用户级 Recipe 目录创建 `~/.frago/recipes/`
  - 示例 Recipe 复制

- [x] **配置持久化**
  - `~/.frago/config.json` 配置文件
  - 配置状态查看 `--show-config`
  - 重置功能 `--reset`

### 环境变量支持（2025-11-26）

- [x] **三级配置优先级**
  - CLI `--env` 参数（最高）
  - 项目级 `.frago/.env`
  - 用户级 `~/.frago/.env`
  - 系统环境变量
  - Recipe 默认值（最低）

- [x] **Recipe 元数据扩展**
  - `env` 字段声明所需环境变量
  - `required`/`default`/`description` 属性
  - 执行时验证和默认值应用

- [x] **Workflow 上下文共享**
  - `WorkflowContext` 类支持跨 Recipe 共享
  - 完整系统环境继承
  - CLI `-e KEY=VALUE` 覆盖

### Feature 008: GUI 应用模式

- [x] **桌面 GUI 应用**
  - `frago gui` 命令启动桌面界面
  - pywebview 后端（Linux 用 WebKit2GTK，Windows 用 WebView2，macOS 用 WKWebView）
  - 跨平台支持（Linux、macOS、Windows）
  - 动态窗口尺寸（屏幕高度的 80%，保持宽高比）

- [x] **GUI 功能**
  - Recipe 列表和详情查看
  - Recipe 执行与参数输入
  - 命令输入和输出显示
  - 连接状态指示器

- [x] **安装方式**
  - 可选 GUI 依赖：`pip install frago-cli[gui]`
  - 平台特定后端自动检测
  - 优雅降级并提供安装说明

### Feature 009: GUI 设计重构

- [x] **配色方案优化**
  - GitHub Dark 配色（`--bg-base: #0d1117`）
  - 柔和蓝色强调色（`--accent-primary: #58a6ff`）
  - 协调的文本和边框颜色
  - 减少长时间使用的眼睛疲劳

- [x] **布局改进**
  - 清晰的视觉层次（输入 > 内容 > 导航）
  - Recipe 卡片设计带操作按钮
  - 空状态引导
  - 响应式布局（600-1600px 宽度）

- [x] **交互反馈**
  - 加载状态与平滑过渡
  - 消息气泡动画
  - 状态指示器更新
  - 原生窗口标题栏（解决 macOS 关闭挂起问题）

### Feature 010: Agent 会话监控

- [x] **会话文件监控**
  - 基于 watchdog 的文件系统监控
  - 从 `~/.claude/projects/` 实时解析 JSONL
  - 增量解析（仅处理新记录）
  - 通过时间戳匹配关联会话（10秒窗口）

- [x] **会话数据持久化**
  - 结构化存储：`~/.frago/sessions/{agent_type}/{session_id}/`
  - `metadata.json` - 会话元数据（项目、开始时间、状态）
  - `steps.jsonl` - 执行步骤（消息、工具调用）
  - `summary.json` - 会话摘要（工具调用统计）

- [x] **多 Agent 支持**
  - `AgentType` 枚举（CLAUDE、CURSOR、CLINE、OTHER）
  - `AgentAdapter` 抽象基类用于扩展
  - `ClaudeCodeAdapter` Claude Code 实现
  - 适配器注册表支持未来 Agent

- [x] **CLI 命令**
  - `frago session list` - 列出会话
  - `frago session show <id>` - 显示会话详情
  - `frago session watch` - 实时会话监控

---

## 待完成功能 📝

### 高优先级

- [ ] **Chrome-JS 参数注入**
  - 当前 chrome-js 运行时不支持参数传递
  - 需要通过全局变量或脚本包装注入参数
  - 支持 Recipe 声明的 `inputs` 传递到 JS 脚本

- [ ] **Workflow 编排增强**
  - 原子 Recipe 组合为复杂工作流
  - 条件分支和循环支持
  - 错误处理和回滚机制
  - 并行执行支持

- [ ] **Recipe 生态建设**
  - 常用平台 Recipe 库（YouTube、GitHub、X、Upwork、LinkedIn）
  - Recipe 分享和导入机制
  - 社区 Recipe 贡献流程
  - Recipe 性能基准测试

### 中优先级

- [ ] **Run 系统增强**
  - Run 模板支持常见工作流
  - Run 指标和分析报告
  - 多格式日志导出（CSV、Excel）
  - Run 对比和差异工具

- [ ] **开发者体验**
  - Recipe 测试框架
  - Recipe 调试工具
  - 更友好的错误信息
  - VS Code 扩展（语法高亮、智能提示）

- [ ] **文档和示例**
  - 关键工作流视频教程
  - 交互式文档
  - 更多真实场景 Recipe 示例
  - 最佳实践指南

### 低优先级

- [ ] **高级功能**
  - Recipe 版本管理系统
  - 多浏览器支持（Firefox、Safari）
  - 分布式 Recipe 执行
  - Recipe 市场
  - AI 驱动的 Recipe 优化建议

- [ ] **企业功能**
  - 团队 Recipe 共享
  - 执行审计日志
  - 权限控制
  - API 调用统计

---

## 迭代详情

### 001: CDP 脚本标准化
**目标**：统一 websocat 方法，建立基础 CDP 操作模式

**成果**：
- 标准化 CDP 脚本模板
- websocat 统一接口
- 基础操作命令集

### 002: CDP 集成重构
**目标**：用 Python 原生实现替代 Shell 脚本，支持代理

**成果**：
- ~3,763 行 Python CDP 实现
- 原生 WebSocket 连接
- 代理配置支持
- 智能重试机制
- CLI 工具（Click 框架）

### 003: Recipe 自动化系统设计
**目标**：设计 Recipe 系统，固化高频操作，加速 AI 推理

**成果**：
- Recipe 系统架构设计
- `/frago.recipe` 命令设计
- Recipe 创建和更新流程
- Recipe 存储和命名规范

### 004: Recipe 架构重构
**目标**：元数据驱动 + AI-First 设计

**成果**：
- 元数据解析器（YAML frontmatter）
- Recipe 注册表（三级查找路径）
- Recipe 执行器（多运行时）
- CLI 命令组（list/info/run/copy）
- AI 可理解字段设计

### 005: Run 命令系统
**目标**：为 AI agent 提供持久化上下文管理

**成果**：
- 主题型 Run 实例创建和管理
- RapidFuzz 模糊匹配自动发现
- JSONL 结构化日志（100% 可解析）
- 持久化上下文存储
- `/frago.run` slash 命令集成
- 完整测试覆盖

**关键特性**：
- **知识积累**：已验证脚本跨会话持久化
- **可审计性**：完整操作历史 JSONL 格式
- **可恢复性**：AI 可在数天后恢复探索
- **Token 效率**：相比重复探索节省 93.5% token

### 006: Init 命令
**目标**：用户安装后一键初始化环境

**成果**：
- 并行依赖检查（Node.js、Claude Code）
- 智能安装缺失组件
- 认证配置（官方/自定义端点）
- 配置持久化

### 007: Init 资源安装
**目标**：自动安装 slash 命令和示例 Recipe

**成果**：
- Slash 命令安装到 `~/.claude/commands/`
- 用户级 Recipe 目录创建
- 示例 Recipe 复制
- 资源状态查看

### 008: GUI 应用模式
**目标**：为非 CLI 用户提供桌面 GUI 界面

**成果**：
- 基于 pywebview 的桌面应用
- 跨平台支持（Linux、macOS、Windows）
- Recipe 管理界面
- 命令执行界面
- 基于屏幕的动态窗口尺寸

### 009: GUI 设计重构
**目标**：改善视觉体验和用户认知

**成果**：
- GitHub Dark 配色方案（专业、低眼疲劳）
- 清晰的视觉层次（输入 > 内容 > 导航）
- 交互反馈（加载状态、动画）
- 原生窗口标题栏（解决 macOS 关闭挂起问题）

### 010: Agent 会话监控
**目标**：实时监控和持久化 Claude Code 会话数据

**成果**：
- 基于 watchdog 的文件系统监控
- JSONL 增量解析
- 会话数据持久化（`~/.frago/sessions/`）
- 多 Agent 架构（可扩展到 Cursor、Cline）
- CLI 命令（list、show、watch）

**关键特性**：
- **实时显示**：实时查看 Agent 执行状态
- **数据持久化**：所有会话数据保存供后续分析
- **并发隔离**：多会话互不干扰
- **可扩展性**：适配器模式支持未来 Agent

---

## 版本历史

### v0.1.0（已发布 - 2025-11-26）

首个正式版本，核心基础设施完成。

**包含功能**：
- 原生 CDP 协议层（~3,763 行 Python，直连 Chrome）
- Recipe 元数据驱动架构（chrome-js/python/shell 运行时）
- Run 命令系统（持久化任务上下文，JSONL 结构化日志）
- Init 命令（依赖检查、资源安装）
- 环境变量支持（三级配置优先级）
- Claude Code slash 命令（/frago.run, /frago.recipe, /frago.exec）

### v0.2.0（已发布 - 2025-11-26）

**里程碑**：架构增强与工作空间隔离

**重大变更**：

1. **Recipe 目录化结构**
   - Recipe 从文件形式改为目录形式
   - 每个配方现在是一个目录：`配方名/recipe.md + recipe.py + examples/`
   - Schema 和示例数据随配方传播，便于分享
   - 明确两种配方类型：Type A（外部结构如 DOM）vs Type B（自定义结构如 VideoScript）

2. **单一运行互斥机制**
   - 系统仅允许一个活跃的 Run 上下文
   - 新增 `uv run frago run release` 命令释放上下文
   - `set-context` 在已有其他活跃 run 时拒绝执行（同一 run 除外）
   - 设计约束确保工作聚焦

3. **工作空间隔离原则**
   - 所有产出物必须放在 `projects/<run_id>/` 目录
   - 配方执行必须明确指定 `output_dir` 参数
   - 已在 `/frago.run` 和 `/frago.exec` 命令文档中说明

4. **工具优先级原则**
   - 优先级：Recipe > frago 命令 > Claude Code 工具
   - frago CDP 命令跨 agent 通用
   - 文档化搜索/浏览操作指南

5. **依赖变更**
   - `pyperclip` 从可选依赖移至基础依赖
   - 剪贴板支持现默认包含

6. **版本管理**
   - `__version__` 现通过 `importlib.metadata` 从 `pyproject.toml` 读取
   - 版本号单一来源

### v0.3.0（已发布 - 2025-12-01）

**里程碑**：CLI 命令分组与资源同步

**重大变更**：

1. **CLI 命令分组**
   - 命令按组织织：`chrome`、`recipe`、`run`、`session`
   - `frago chrome navigate` 替代 `frago navigate`
   - `frago recipe list` 替代 `frago list`
   - 通过 `--help` 改善可发现性

2. **资源同步命令**
   - `frago publish` - 推送项目资源到系统目录
   - `frago sync` - 推送系统资源到远程 Git 仓库
   - `frago deploy` - 从远程 Git 仓库拉取到系统
   - `frago dev-load` - 加载系统资源到项目（仅开发）

3. **Agent 命令**
   - `frago agent "任务"` - 执行 AI 驱动的任务
   - 与会话监控集成

### v0.4.0（已发布 - 2025-12-05）

**里程碑**：GUI 应用模式与会话监控

**重大变更**：

1. **GUI 应用模式（Feature 008）**
   - `frago gui` 命令启动桌面界面
   - pywebview 后端（跨平台）
   - Recipe 管理和执行
   - 可选依赖：`pip install frago-cli[gui]`

2. **GUI 设计重构（Feature 009）**
   - GitHub Dark 配色方案
   - 改善视觉层次
   - 原生窗口标题栏（解决 macOS 挂起）

3. **Agent 会话监控（Feature 010）**
   - 实时 Claude Code 会话跟踪
   - 使用 watchdog 解析 JSONL
   - 会话数据持久化
   - `frago session list/show/watch` 命令

### v0.5.0（规划中）

**里程碑**：Recipe 系统增强

**核心目标**：
- Chrome-JS 参数注入（解决当前 JS 脚本无法接收参数的问题）
- Workflow 编排增强（条件分支、循环、错误处理）
- 常用平台 Recipe 库扩展（YouTube、GitHub、Upwork）

**次要目标**：
- Run 系统模板支持
- 日志导出（CSV/Excel）

### v1.0.0（远期目标）

**里程碑**：生产就绪

**核心目标**：
- 稳定公共 API
- 完善文档和教程
- 社区 Recipe 市场

**次要目标**：
- 多浏览器支持（Firefox、Safari）
- 企业功能（团队共享、审计日志、权限控制）
