# frago Guide Content Outline - 内容大纲

> **规划日期**: 2026-01-17
> **目标**: 定义5个核心章节的FAQ内容结构

---

## 章节1: 开始使用 (Getting Started)

**文件**: `01-getting-started.md`
**分类**: getting-started
**目标用户**: 首次使用frago的新手
**核心问题**: "我装完了，现在该干什么？"

### FAQ列表

#### Q1: 我刚装完frago，进入了Web UI，现在该从哪开始？

**关键词**: first time, start, begin, 新手
**回答要点**:
1. 先看Recipes（现成工具）
2. 尝试Console（让AI帮忙）
3. 查看Tasks（执行历史）

#### Q2: 左侧菜单这么多，每个是干什么的？

**关键词**: sidebar, menu, navigation
**回答要点**:
- Dashboard: 总览
- Console: 开发recipe专用
- Tasks: 任务历史
- Recipes: 自动化脚本库
- Skills: 方法论文档（进阶）
- Workspace: 项目文件浏览
- Sync: 跨设备同步
- Secrets: API密钥管理
- Settings: 配置中心

#### Q3: 我想试试frago，推荐一个最简单的任务？

**关键词**: demo, example, try, 试试
**回答要点**:
1. 推荐运行 `test_inspect_tab` recipe
2. 最简单，不会改变任何东西
3. 了解Recipe执行流程

#### Q4: 教程里提到的"Claude Code"是什么？

**关键词**: Claude Code, CLI, claude
**回答要点**:
- frago配合Claude Code CLI使用效果最佳
- CLI提供交互式模式（需要手动批准）
- Web UI提供可视化界面（自动批准）
- 可以单独使用frago Web UI

---

## 章节2: 界面功能FAQ (Interface FAQ)

**文件**: `02-interface-faq.md`
**分类**: interface
**目标用户**: 对界面功能有疑问的用户
**核心问题**: "Console和Tasks有什么区别？"

### FAQ列表

#### Q1: Console和Tasks有什么区别？我该用哪个？

**关键词**: console, tasks, difference
**回答要点**:
- Console: Recipe开发专用，自动批准
- Tasks: 正常任务，交互式
- 表格对比
- 使用建议

#### Q2: Recipe（配方）是什么意思？

**关键词**: recipe, automation, script
**回答要点**:
- 可重用的自动化脚本
- 附带元数据（描述、参数）
- 示例说明
- 类比：菜谱

#### Q3: Workspace是干什么的？

**关键词**: workspace, files, logs
**回答要点**:
- 项目文件浏览器
- 存放Run项目的所有文件
- 目录结构说明
- 何时使用

#### Q4: Skills和Recipes有什么区别？

**关键词**: skills, recipes, difference
**回答要点**:
- Recipe: 可执行脚本（代码）
- Skill: 方法论文档（文字）
- 新手可先忽略Skills

#### Q5: 为什么有些Recipe在"Local"，有些在"Community"？

**关键词**: local, community, source
**回答要点**:
- Local: 你本地的recipes
- Community: 社区分享的recipes
- 三级优先级：Project > User > Example

#### Q6: Dashboard的图表是什么意思？

**关键词**: dashboard, chart, statistics
**回答要点**:
- 最近6小时活动统计
- Sessions数量
- Tool calls数量
- 状态分布（完成/运行中/错误）

---

## 章节3: 配置相关 (Configuration)

**文件**: `03-configuration.md`
**分类**: config
**目标用户**: 需要配置frago的用户
**核心问题**: "API Key填在哪？Model Override是什么？"

### FAQ列表

#### Q1: 我在哪里填写Anthropic API Key？

**关键词**: API key, Anthropic, configuration
**回答要点**:
1. Settings → General → API Key
2. 如何获取API Key
3. 测试是否配置成功

#### Q2: Settings里的"Model Override"是什么？我该选哪个？

**关键词**: model, override, sonnet, opus, haiku
**回答要点**:
- Sonnet: 默认，平衡
- Opus: 最强，复杂任务
- Haiku: 最快，简单任务
- 新手建议保持默认

#### Q3: "Endpoint Type"有什么区别？

**关键词**: endpoint, official, custom
**回答要点**:
- Official Claude API: 默认，推荐
- Custom Endpoint: 高级用户，自建代理
- 切换风险提示

#### Q4: Sync是干什么的？什么时候需要？

**关键词**: sync, git, multiple devices
**回答要点**:
- 跨设备同步Recipes和Skills
- 使用场景
- 配置步骤
- 新手建议：单机使用不需要

#### Q5: Secrets页面是干什么的？

**关键词**: secrets, environment variables, API keys
**回答要点**:
- 存储敏感信息
- Recipe如何引用
- 示例：OPENAI_API_KEY
- 新手建议：暂时用不到

#### Q6: "Working Directory"是什么？可以改吗？

**关键词**: working directory, path, location
**回答要点**:
- AI执行任务的默认目录
- 何时需要修改
- 如何修改
- 注意事项

---

## 章节4: 使用技巧 (Usage Tips)

**文件**: `04-usage-tips.md`
**分类**: usage
**目标用户**: 已经会基本操作，想提高效率的用户
**核心问题**: "如何更好地使用frago？"

### FAQ列表

#### Q1: 我想让AI帮我提取网页数据，怎么说？

**关键词**: web scraping, extract, data
**回答要点**:
- 好的描述示例（具体、清晰）
- 不好的描述示例（模糊）
- 原则：URL、提取内容、输出格式

#### Q2: 如何判断该用Run还是Recipe？

**关键词**: run, recipe, when to use
**回答要点**:
- 用Run：探索未知、调试、记录过程
- 用Recipe：重复任务、已知流程
- 决策流程图

#### Q3: 为什么有些任务很慢？如何提速？

**关键词**: slow, performance, speed up
**回答要点**:
- 可能原因（探索、网页加载、复杂任务）
- 提速方法（用Recipe、拆分任务、换模型）

#### Q4: Console的"自动批准"是什么意思？有什么风险？

**关键词**: auto-approve, risk, danger
**回答要点**:
- 什么是自动批准
- 风险说明
- 安全使用建议
- 何时用交互式模式

#### Q5: 如何分享我的Recipe给别人？

**关键词**: share, recipe, community
**回答要点**:
- `frago recipe share` 命令
- 社区贡献流程
- Recipe命名规范

#### Q6: 我想在Console和Tasks之间切换，会丢失内容吗？

**关键词**: switch, lose, session
**回答要点**:
- Console会保持Session
- Tasks显示所有历史
- 数据持久化保证

#### Q7: Recipe参数怎么填？JSON格式不会写怎么办？

**关键词**: parameters, JSON, format
**回答要点**:
- Web UI提供表单输入（自动生成JSON）
- JSON格式基础
- 常见错误示例
- 验证工具

---

## 章节5: 故障排查 (Troubleshooting)

**文件**: `05-troubleshooting.md`
**分类**: troubleshooting
**目标用户**: 遇到错误的用户
**核心问题**: "为什么不工作？如何调试？"

### FAQ列表

#### Q1: 为什么我在Console里发送消息，没有任何输出？

**关键词**: no output, console, not working
**回答要点**:
1. API Key未配置
2. 任务还在执行
3. Chrome未启动
4. 任务描述不清楚

#### Q2: Console显示"Chrome not connected"怎么办？

**关键词**: chrome, not connected, CDP
**回答要点**:
- 启动Chrome
- 检查CDP配置
- 端口占用问题
- Settings → Init → Chrome Setup

#### Q3: Recipe运行失败，显示"selector not found"？

**关键词**: selector not found, recipe failed
**回答要点**:
- 网页结构改变
- URL不对
- 解决方法：重新让AI探索

#### Q4: 我在Tasks里看到任务"Error"了，怎么调试？

**关键词**: error, debug, failed task
**回答要点**:
1. 查看执行日志
2. 常见错误类型
3. 复制错误信息问AI

#### Q5: API Key配置了，但还是报错"Authentication failed"？

**关键词**: authentication, API key, failed
**回答要点**:
- 检查Key是否正确（复制粘贴完整）
- 检查配额（是否用完）
- 检查网络（能否访问Anthropic API）
- 测试方法

#### Q6: 安装Recipe后找不到怎么办？

**关键词**: recipe not found, installation
**回答要点**:
- `frago recipe list` 确认安装
- 检查拼写
- 刷新页面
- 查看Recipes页面Tab（Local vs Community）

#### Q7: Session一直显示"Running"，卡住了？

**关键词**: stuck, running, hang
**回答要点**:
- 可能在等待网页加载
- 可能在等待用户确认（CLI模式）
- 如何停止
- 如何查看日志

#### Q8: 浏览器Console报错（开发者工具）？

**关键词**: browser console, JavaScript error
**回答要点**:
- 如何打开浏览器Console
- 常见错误类型
- 何时需要报告给开发者

#### Q9: 为什么Dashboard显示"Offline"？

**关键词**: offline, server, not running
**回答要点**:
- 检查server是否运行
- `frago server status`
- 重启server
- 检查端口占用

#### Q10: Windows上遇到路径问题？

**关键词**: Windows, path, encoding
**回答要点**:
- Windows路径特殊字符
- 使用正斜杠 `/` 或双反斜杠 `\\`
- 避免中文路径
- 示例

---

## 附加章节（未来扩展）

### 章节6: 进阶技巧 (Advanced)
- 创建自定义Recipe
- Workflow Recipe编排
- 与Claude Code CLI集成
- 贡献社区Recipe

### 章节7: 视频教程 (Video Tutorials)
- 快速开始（5分钟）
- 第一个任务（10分钟）
- Recipe开发（15分钟）

---

## 内容编写原则

### 1. 语气
- 友好、耐心
- 避免技术术语（或解释清楚）
- 使用类比和例子

### 2. 格式
- Q&A格式
- 关键信息加粗
- 代码示例完整可复制
- 截图辅助（可选）

### 3. 长度
- 每个回答控制在200-400字
- 复杂问题分步骤
- 提供"快速答案" + "详细说明"

### 4. 链接
- 相关FAQ交叉引用
- 链接到官方文档
- 链接到GitHub Issues（报告问题）

### 5. 更新
- 标注最后更新日期
- 版本兼容性说明
- 废弃功能警告

---

## FAQ优先级

### P0（必须有，Phase 1）
- Q: 我刚装完frago，现在该从哪开始？
- Q: Console和Tasks有什么区别？
- Q: Recipe是什么意思？
- Q: 在哪里填写API Key？
- Q: 为什么Console没有输出？
- Q: 如何提取网页数据？
- Q: 任务报错怎么调试？

### P1（重要，Phase 1）
- Q: 左侧菜单每个是干什么的？
- Q: Workspace是干什么的？
- Q: Model Override是什么？
- Q: Sync是干什么的？
- Q: 为什么任务很慢？
- Q: Chrome not connected怎么办？

### P2（有用，Phase 2）
- Q: Skills和Recipes的区别？
- Q: Secrets是干什么的？
- Q: 如何分享Recipe？
- Q: Recipe参数怎么填？
- Q: selector not found怎么办？

---

## 示例FAQ模板

```markdown
## Q: [问题标题]

**A**: [简短答案，1-2句话]

[详细说明]

**[子标题1]**:
- 要点1
- 要点2

**[子标题2]**:
```
[代码示例]
```

**[注意/提示]**:
⚠️ [警告信息]
或
💡 [提示信息]

**相关问题**: [链接到其他FAQ]
```

---

**内容大纲完成日期**: 2026-01-17
**预计FAQ总数**: ~30个（5章节）
**预计总字数**: ~8000字（中文） + 8000字（英文）
