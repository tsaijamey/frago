---
id: interface-faq
title: 界面功能FAQ
category: interface
order: 2
version: 0.38.1
last_updated: 2026-01-17
tags:
  - interface
  - console
  - tasks
  - recipes
  - workspace
---

# 界面功能FAQ

## Q: Console和Tasks有什么区别？我该用哪个？

**A**: Console是Recipe开发专用环境，Tasks是确定性任务执行环境。两者都自动批准所有操作。

| 特性 | Console | Tasks |
|------|---------|-------|
| **用途** | 开发和测试Recipe | 执行确定性任务 |
| **会话显示** | 当前开发会话 | 所有任务列表 |
| **使用场景** | 探索网页、调试Recipe、快速实验 | 运行已有配方、执行标准化任务 |

**使用建议**：

- **用Console开发**：当你想让AI帮你探索如何完成某个任务时（比如"帮我研究如何从这个网页提取数据"）
- **用Tasks执行**：当你要运行已有的Recipe或执行不需要中途调整的任务时

**重要提示**：
⚠️ Console会自动执行所有操作（文件修改、命令执行等），在敏感项目上使用时要小心。如需完全手动控制，建议使用命令行的 `claude -p "your task"` 模式。

**相关问题**: Console的"自动批准"有什么风险？（见使用技巧章节）

---

## Q: Recipe（配方）是什么意思？

**A**: Recipe（配方）是frago定义的标准化自动化任务，包含完整的任务描述、参数定义和执行逻辑。可以把它理解为"保存好的菜谱"。

**为什么叫Recipe？**

就像烹饪菜谱一样：
- 📝 **有明确的步骤**：Recipe定义了完成任务的具体流程
- 🔧 **可以调整参数**：就像做菜可以调整盐量，Recipe可以传入不同的URL、关键词等
- ♻️ **可以重复使用**：做好一次，以后随时可以用相同方法再做

**Recipe的类型**：

1. **Atomic Recipe（原子配方）**
   - 解决单一问题
   - 例如：`screenshot_tab` - 截图当前网页
   - 特点：简单、可组合

2. **Workflow Recipe（工作流配方）**
   - 串联多个步骤
   - 例如：抓取网页 → 提取数据 → 保存到文件
   - 特点：复杂、自动化程度高

**在哪里找Recipe？**

- **Local Recipes**：你本地的配方（包括自己创建的和从社区安装的）
- **Community Recipes**：frago官方和社区贡献的配方库

**如何使用Recipe？**

1. 进入 Recipes 页面
2. 找到需要的Recipe
3. 点击"Run"按钮
4. 填写必需的参数（如果有）
5. 执行并查看结果

**示例**：
```
Recipe: web_extract_to_json
参数:
  - url: https://example.com/products
  - selectors: {"title": "h1", "price": ".price"}
  - output_file: products.json

执行后会自动访问网页，提取数据，保存为JSON文件
```

**相关问题**: 如何判断该用Run还是Recipe？（见使用技巧章节）

---

## Q: Workspace是干什么的？

**A**: Workspace是frago的项目文件浏览器，用于查看和管理Run项目中的所有文件（代码、日志、截图等）。

**为什么需要Workspace？**

当你使用frago执行任务时，frago会创建一个"Run项目"来存储所有相关文件：
- 📁 生成的代码文件
- 📸 网页截图
- 📝 执行日志
- 💾 下载的数据

Workspace让你可以直接在Web UI中浏览这些文件，不需要打开文件管理器。

**目录结构**：

```
~/.frago/projects/
└── run-20260117-143022/          # Run项目目录
    ├── recipes/                   # Recipe执行产生的文件
    │   ├── screenshot.png
    │   └── data.json
    ├── workspace/                 # 工作区文件
    │   └── script.py
    └── .frago/                    # frago内部文件
        └── session.json
```

**何时使用Workspace？**

- ✅ 查看AI生成的代码
- ✅ 下载Recipe执行结果
- ✅ 检查网页截图
- ✅ 查看日志文件
- ✅ 确认文件是否正确生成

**提示**：
💡 你也可以点击"Open in file manager"按钮直接在系统文件管理器中打开项目目录。

---

## Q: Skills和Recipes有什么区别？

**A**: Recipe是可执行的标准化配方（代码），Skill是指导Claude工作的方法论文档（文字）。新手可以先忽略Skills。

**简单类比**：

- **Recipe**：标准化的做菜步骤，机器可以直接执行
- **Skill**：做菜的技巧心得，教会厨师如何思考

**详细对比**：

| 特性 | Recipe | Skill |
|------|--------|-------|
| **本质** | 标准化配方定义 | Markdown文档 |
| **执行** | 可直接运行 | 不可执行，仅供阅读 |
| **作用** | 自动化重复任务 | 指导AI的决策过程 |
| **示例** | screenshot_tab.py | frago-chrome-navigation.md |
| **用户** | 所有用户 | 进阶用户 |

**什么时候需要Skill？**

当你使用Claude Code CLI时，Skill文档会被自动加载，帮助Claude理解frago的最佳实践。例如：
- `frago-chrome` skill教Claude如何操作Chrome
- `frago-recipe` skill教Claude如何编写Recipe

**新手建议**：
💡 刚开始使用frago时，专注于使用Recipes即可。Skill是给Claude看的，不是给人用的。

---

## Q: 为什么有些Recipe在"Local"，有些在"Community"？

**A**: Local显示你本地已安装的Recipes，Community显示可以从官方仓库安装的Recipes。

**三级优先级**：

frago会按以下顺序查找Recipes：

1. **Project级别** (`~/.frago/projects/[run_id]/recipes/`)
   - 当前Run项目专用的Recipes
   - 优先级最高

2. **User级别** (`~/.frago/recipes/`)
   - 你自己创建或安装的Recipes
   - 跨项目共享

3. **Example级别** (frago安装包内置)
   - 官方示例Recipes
   - 用于学习和参考

**Local Recipes包含**：
- User级别的Recipes（你安装的）
- 从Community安装的Recipes
- 你自己创建的Recipes

**Community Recipes**：
- frago官方提供的配方库
- 托管在GitHub上
- 点击"Install"后会安装到User级别

**示例**：
```
你看到: Local (5个) | Community (15个)

Local的5个 = 你之前安装的3个 + 你自己写的2个
Community的15个 = 官方库中可安装的配方（不包括已安装的）
```

**提示**：
💡 安装Community Recipe需要配置GitHub CLI，或者会受到GitHub API速率限制。

**相关问题**: 安装Recipe后找不到怎么办？（见故障排查章节）

---

## Q: Dashboard的图表是什么意思？

**A**: Dashboard显示最近12小时的frago活动统计，包括会话数量、工具调用次数和执行状态分布。

**图表解读**：

**1. 系统概览卡片**：
- **Server**: 服务器状态（Online/Offline）
- **Uptime**: 服务器运行时间
- **Tasks/Recipes/Skills**: 各类资源数量

**2. 活动统计**：
- **Sessions（会话）**: 最近12小时启动的任务/会话数量
- **Tool Calls（工具调用）**: AI执行的操作次数（读文件、运行命令等）
- **Completed/Running/Errors**: 任务状态分布
  - ✅ Completed: 成功完成
  - 🔄 Running: 正在运行
  - ❌ Errors: 执行出错

**什么是Tool Call？**

每当AI执行一个操作就算一次Tool Call，例如：
- 读取文件
- 执行Shell命令
- 截图网页
- 点击按钮

一个任务通常包含多次Tool Calls。

**如何理解数据？**

```
Sessions: 5       → 你今天运行了5个任务
Tool Calls: 127   → AI总共执行了127次操作
Completed: 4      → 4个任务成功
Running: 1        → 1个任务还在执行
Errors: 0         → 没有失败的任务
```

**提示**：
💡 如果Tool Calls数量很高但没有对应成果，可能任务描述不够清晰，导致AI在重复探索。

**相关问题**: 为什么有些任务很慢？（见使用技巧章节）
