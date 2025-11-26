# Frago 项目进展

## 项目状态

📍 **当前阶段**：三系统架构完成（Run + Recipe + CDP），进入生态建设阶段

**已完成**：
- ✅ 原生 CDP 协议层（~3,763 行 Python）
- ✅ CLI 工具和命令系统
- ✅ Recipe 元数据驱动架构（多运行时支持）
- ✅ Run 命令系统（主题型任务管理）
- ✅ Init 命令（依赖检查、资源安装）
- ✅ 环境变量支持（三级配置优先级）

**技术亮点**：
- 🏆 原生 CDP（无 Playwright/Selenium 依赖，~2MB）
- 🏆 AI-First 设计（Claude AI 主持任务执行和工作流编排）
- 🏆 Recipe 加速系统（固化高频操作，避免重复 AI 推理）
- 🏆 Run 系统（AI 的工作记忆，持久化上下文）
- 🏆 环境变量系统（敏感信息管理 + Workflow 上下文共享）

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

---

## 版本历史

### v0.1.0（当前）
- 核心 CDP 实现（~3,763 行）
- Recipe 元数据驱动架构
- Run 命令系统
- Init 命令和资源安装
- 环境变量支持
- Claude Code slash 命令（/frago.run, /frago.recipe, /frago.exec）

### v0.2.0（规划中）
- Chrome-JS 参数注入
- Workflow 编排增强
- Run 系统增强（模板、导出）
- 更多平台 Recipe

### v0.3.0（规划中）
- Recipe 生态建设
- 开发者工具（测试框架、调试器）
- VS Code 扩展
- 性能优化

### v1.0.0（远期目标）
- 稳定公共 API
- 完善文档和教程
- 社区 Recipe 市场
- 多浏览器支持
- 企业功能
