// frago CLI 命令数据(双语)
// 英文取自 `frago --help` 原文,中文为对照译文。version 0.49.1,核实日期 2026-05-24。
// 结构:每个命令 { name, zh, en, leaf?, note?, sub?[[name,zh,en]...], subgroups?[{zh,en,items}] }
const DATA = [
  {
    id: "daily", zh: "日常使用", en: "Daily Use",
    cmds: [
      { name: "start", zh: "启动 frago 并在浏览器中打开 Web UI。", en: "Start frago and open the Web UI in your browser." },
      { name: "client", zh: "管理 frago 桌面客户端。", en: "Manage the frago desktop client.", sub: [
        ["start", "启动桌面客户端(未安装则自动下载)。", "Start the desktop client (downloads if not installed)."],
        ["status", "显示桌面客户端的安装状态。", "Show the desktop client installation status."],
        ["uninstall", "卸载已安装的桌面客户端。", "Remove the installed desktop client."],
        ["update", "将桌面客户端更新到最新版本。", "Update the desktop client to the latest version."],
      ]},
      { name: "chrome", zh: "Chrome CDP 浏览器自动化。", en: "Chrome CDP browser automation.", subgroups: [
        { zh: "生命周期", en: "Lifecycle", items: [
          ["start", "启动带 CDP 调试支持的浏览器。", "Launch browser with CDP debugging support."],
          ["stop", "停止 Chrome CDP 进程。", "Stop Chrome CDP process."],
          ["status", "检查 CDP 连接状态。", "Check CDP connection status."],
        ]},
        { zh: "标签管理", en: "Tab Management", items: [
          ["list-tabs", "列出所有打开的浏览器标签。", "List all open browser tabs."],
          ["switch-tab", "切换到指定浏览器标签。", "Switch to specified browser tab."],
          ["close-tab", "按 ID 关闭浏览器标签。", "Close a browser tab by ID."],
        ]},
        { zh: "标签分组", en: "Tab Groups", items: [
          ["groups", "列出所有标签分组及其标签数。", "List all tab groups and their tab counts."],
          ["group-info", "显示某个标签分组的详情。", "Show details of a tab group."],
          ["group-close", "关闭某个标签分组及其全部标签。", "Close a tab group and all its tabs."],
          ["group-cleanup", "清除标签已不存在的失效分组。", "Remove stale groups whose tabs no longer exist."],
          ["reset", "关闭除着陆页外的所有标签。", "Close all tabs except the landing page."],
        ]},
        { zh: "页面控制", en: "Page Control", items: [
          ["navigate", "导航到 URL 并在加载后获取页面特征。", "Navigate to URL and get page features after loading."],
          ["scroll", "滚动页面并自动捕获页面特征。", "Scroll page and automatically capture page features."],
          ["scroll-to", "滚动到指定元素。", "Scroll to specified element."],
          ["zoom", "设置页面缩放级别并自动捕获页面特征。", "Set page zoom level and automatically capture page features."],
          ["wait", "等待指定秒数(支持小数)。", "Wait for specified seconds (supports decimals)."],
        ]},
        { zh: "元素交互", en: "Element Interaction", items: [
          ["click", "按选择器点击元素并获取页面特征。", "Click element by selector and get page features."],
          ["exec-js", "执行 JavaScript 代码并自动捕获页面特征。", "Execute JavaScript code and automatically capture page features."],
          ["get-title", "获取页面标题。", "Get page title."],
          ["get-content", "从页面或元素获取文本内容。", "Get text content from page or element."],
        ]},
        { zh: "视觉效果", en: "Visual Effects", items: [
          ["screenshot", "截取页面截图。", "Capture page screenshot."],
          ["highlight", "高亮指定元素。", "Highlight specified element."],
          ["pointer", "在元素上显示鼠标指针。", "Show mouse pointer on element."],
          ["spotlight", "以聚光灯效果展示元素。", "Show element with spotlight effect."],
          ["annotate", "在元素上添加标注。", "Add annotation on element."],
          ["underline", "逐行在元素文本下绘制下划线动画。", "Draw line animation under element text line by line."],
          ["clear-effects", "清除所有视觉效果。", "Clear all visual effects."],
        ]},
      ]},
      { name: "recipe", zh: "Recipe 管理命令组。", en: "Recipe management command group.", sub: [
        ["cancel", "取消正在运行的执行。", "Cancel a running execution."],
        ["create", "通过 agent 从 spec 或 prompt 创建 recipe。", "Create a recipe via agent from spec or prompt."],
        ["execution", "显示某次执行的详情。", "Show details of a specific execution."],
        ["executions", "列出最近的 recipe 执行记录。", "List recent recipe executions."],
        ["info", "显示某个 recipe 的详细信息。", "Display detailed information about a specific recipe."],
        ["install", "从多种来源安装 recipe。", "Install a recipe from various sources."],
        ["list", "列出所有可用的 recipe。", "List all available recipes."],
        ["plan", "通过 agent 生成 recipe spec。", "Generate a recipe spec via agent."],
        ["run", "执行指定 recipe。", "Execute specified recipe."],
        ["schedule", "按固定间隔重复运行 recipe。", "Run a recipe repeatedly at fixed intervals."],
        ["search", "在社区仓库中搜索 recipe。", "Search for recipes in community repository."],
        ["share", "通过 GitHub PR 将 recipe 分享到社区仓库。", "Share a recipe to the community repository via GitHub PR."],
        ["uninstall", "卸载 recipe(用户或社区)。", "Uninstall a recipe (User or Community)."],
        ["update", "通过从原始来源重新拉取来更新已安装的 recipe。", "Update installed recipes by re-fetching from original source."],
        ["validate", "校验 recipe 元数据的字段完整性与正确性。", "Validate field completeness and correctness of recipe metadata."],
      ]},
      { name: "skill", zh: "Skill 管理命令组。", en: "Skill management command group.", sub: [
        ["list", "列出所有可用的 Skill。", "List all available Skills."],
      ]},
      { name: "run", zh: "Run 命令系统 —— 管理 AI 驱动的任务执行。", en: "Run command system — manage AI-driven task execution.", sub: [
        ["archive", "归档一个 run 实例。", "Archive a run instance."],
        ["find", "按关键词搜索 run 实例。", "Search run instances by keyword."],
        ["info", "显示 run 实例 / 领域的详情。", "Show run instance / domain details."],
        ["init", "初始化 / 确保一个领域(支持词典聚类)。", "Initialize / ensure a domain (dictionary-aware)."],
        ["insights", "领域级洞察 —— 统一的增删改查入口。", "Domain-level insights — unified CRUD entry point."],
        ["list", "列出所有 run 实例 / 领域。", "List all run instances / domains."],
        ["log", "记录结构化日志条目。", "Record structured log entry."],
        ["release", "释放当前 run 上下文(互斥锁)。", "Release the current run context (mutual exclusion lock)."],
        ["screenshot", "保存截图(自动编号)。", "Save screenshot (auto-numbered)."],
        ["set-context", "设置当前工作的 run。", "Set the current working run."],
      ]},
      { name: "book", zh: "frago 内置知识手册。", en: "frago built-in knowledge book.", note: "用法 frago book [TOPIC] · --brief 每条一行摘要 · book scenes 查看场景索引" },
      { name: "def", zh: "管理结构化知识领域。", en: "Manage structured knowledge domains.", sub: [
        ["add", "注册一个新的知识领域。", "Register a new knowledge domain."],
        ["list", "列出所有已注册的领域。", "List all registered domains."],
        ["remove", "注销一个领域(文件保留)。", "Unregister a domain (files are kept)."],
      ]},
      { name: "view", zh: "内容查看器:Markdown / PDF / 代码高亮。", en: "Content viewer: Markdown / PDF / Code highlighting.", leaf: true },
      { name: "server", zh: "管理 frago Web 服务。", en: "Manage the Frago web service.", sub: [
        ["restart", "重启 frago Web 服务。", "Restart the Frago web service."],
        ["start", "启动 frago Web 服务。", "Start the Frago web service."],
        ["status", "检查 frago Web 服务是否在运行。", "Check if the Frago web service is running."],
        ["stop", "停止正在运行的 frago Web 服务。", "Stop the running Frago web service."],
      ]},
      { name: "serve", zh: "启动 frago Web 服务 GUI。", en: "Start the Frago web service GUI.", leaf: true },
    ]
  },
  {
    id: "session", zh: "会话与智能", en: "Session & Intelligence",
    cmds: [
      { name: "session", zh: "会话管理命令组。", en: "Session Management Command Group.", sub: [
        ["clean", "清理过期会话。", "Clean up expired sessions."],
        ["delete", "删除指定会话。", "Delete specified session."],
        ["list", "列出最近的会话。", "List recent sessions."],
        ["show", "查看会话详情。", "View session details."],
        ["sync", "从 Claude 会话文件同步数据。", "Sync data from Claude session files."],
        ["watch", "实时监控会话。", "Monitor sessions in real-time."],
      ]},
      { name: "agent", zh: "智能 Agent:通过 Claude Code 会话执行任务。", en: "Intelligent Agent: Execute tasks via Claude Code session.", leaf: true },
      { name: "agent-status", zh: "检查 Claude CLI 认证状态。", en: "Check Claude CLI authentication status.", leaf: true },
      { name: "reply", zh: "通过某个 ingestion 渠道的 notify recipe 发送回复。", en: "Send a reply through an ingestion channel's notify recipe.", leaf: true },
      { name: "channel", zh: "管理任务 ingestion 渠道(外部任务来源)。", en: "Manage task ingestion channels (external task sources).", sub: [
        ["add", "添加一个新的 ingestion 渠道。", "Add a new ingestion channel."],
        ["disable", "全局禁用任务 ingestion(渠道配置保留)。", "Disable task ingestion globally (channels remain configured)."],
        ["edit", "编辑已有渠道。", "Edit an existing channel."],
        ["enable", "全局启用任务 ingestion。", "Enable task ingestion globally."],
        ["list", "列出已配置的 ingestion 渠道及全局启用状态。", "List configured ingestion channels and global enabled state."],
        ["recipes", "列出已安装的 recipe 名(可作 --poll / --notify 候选)。", "List installed recipe names (candidates for --poll / --notify)."],
        ["rm", "移除一个 ingestion 渠道。", "Remove an ingestion channel."],
      ]},
    ]
  },
  {
    id: "cloud", zh: "云端", en: "Cloud",
    cmds: [
      { name: "login", zh: "登录到 frago Cloud。", en: "Log in to frago Cloud.", leaf: true },
      { name: "logout", zh: "退出登录。", en: "Log out.", leaf: true },
      { name: "whoami", zh: "显示当前登录用户信息。", en: "Show the current logged-in user.", leaf: true },
      { name: "config", zh: "配置管理。", en: "Configuration management.", sub: [
        ["get", "获取配置项。", "Get a config item."],
        ["list", "列出所有配置项。", "List all config items."],
        ["set", "设置配置项。", "Set a config item."],
      ]},
      { name: "market", zh: "Recipe 市场。", en: "Recipe marketplace.", sub: [
        ["info", "查看 Recipe 详情。", "View recipe details."],
        ["install", "下载并安装 Recipe。", "Download and install a recipe."],
        ["list", "列出已安装的 Recipe。", "List installed recipes."],
        ["search", "搜索 Recipe。", "Search recipes."],
        ["uninstall", "卸载 Recipe。", "Uninstall a recipe."],
      ]},
      { name: "install", zh: "安装工具。", en: "Install tools.", leaf: true },
    ]
  },
  {
    id: "env", zh: "环境", en: "Environment",
    cmds: [
      { name: "init", zh: "初始化 frago 开发环境。", en: "Initialize Frago development environment.", leaf: true },
      { name: "status", zh: "检查 CDP 连接状态。", en: "Check CDP connection status.", leaf: true },
      { name: "workspace", zh: "管理 workspace 资源。", en: "Manage workspace resources.", sub: [
        ["collect", "仅收集 workspace 资源,不执行同步。", "Collect workspace resources without syncing."],
        ["list", "列出已发现的项目与 workspace 状态。", "List discovered projects and workspace status."],
        ["pending", "查看上次同步遗留的待部署动作。", "View pending deployment actions from last sync."],
        ["set-scan-roots", "设置用于扫描项目的目录。", "Set directories to scan for projects."],
      ]},
      { name: "update", zh: "将 frago 更新到最新版本。", en: "Update frago to the latest version.", leaf: true },
      { name: "autostart", zh: "管理 frago server 开机自启。", en: "Manage frago server autostart on system boot.", sub: [
        ["disable", "禁用 frago server 开机自启。", "Disable frago server autostart on system boot."],
        ["enable", "启用 frago server 开机自启。", "Enable frago server autostart on system boot."],
        ["status", "显示当前自启配置状态。", "Show current autostart configuration status."],
      ]},
    ]
  },
  {
    id: "dev", zh: "开发者", en: "Developer",
    cmds: [
      { name: "init-dirs", zh: "初始化 frago 用户级目录结构。", en: "Initialize Frago user-level directory structure.", leaf: true },
    ]
  },
  {
    id: "other", zh: "其他", en: "Other",
    cmds: [
      { name: "extension", zh: "浏览器扩展桥接管理。", en: "Browser extension bridge management.", sub: [
        ["click", "通过扩展后端点击元素。", "Click element via the extension backend."],
        ["daemon", "运行 native messaging 守护进程(单例)。", "Run the native messaging daemon (singleton)."],
        ["exec-js", "通过扩展后端执行 JavaScript。", "Execute JavaScript via the extension backend."],
        ["get-content", "通过扩展后端获取页面内容。", "Get page content via the extension backend."],
        ["install", "安装 native messaging manifest。", "Install the native messaging manifest."],
        ["native-host", "由 Chrome 调用的 stdio 中继。", "Stdio relay invoked by Chrome."],
        ["navigate", "通过扩展后端导航。", "Navigate via the extension backend."],
        ["screenshot", "通过扩展后端截图。", "Capture screenshot via the extension backend."],
        ["status", "探测守护进程 + 桥接连通性。", "Ping the daemon + bridge."],
      ]},
      { name: "hook-rules", zh: "管理 frago-hook 引擎的数据化路由规则。", en: "Manage data-driven routing rules for the frago-hook engine.", sub: [
        ["add", "向用户规则文件追加一条新规则。", "Append a new rule to the user rules file."],
        ["disable", "标记规则为禁用而不删除。", "Mark a rule as disabled without deleting it."],
        ["enable", "重新启用先前禁用的规则。", "Re-enable a previously disabled rule."],
        ["list", "列出路由规则(内置 + 用户合并视图)。", "List routing rules (merged builtin + user)."],
        ["prune", "归档超过 TTL 且近期零命中的 agent 规则。", "Archive stale agent rules past their TTL with zero recent hits."],
        ["remove", "从用户文件中删除一条规则。", "Delete a rule from the user file."],
        ["show", "显示单条规则的完整 JSON(合并视图)。", "Show a single rule's full JSON (merged view)."],
        ["stats", "显示每条规则的命中次数与最近命中时间。", "Show hit counts and last-hit timestamps per rule."],
        ["validate", "对 ~/.frago/hook-rules.json 做结构校验。", "Structural validation of ~/.frago/hook-rules.json."],
      ]},
      { name: "schedule", zh: "管理定时任务。", en: "Manage scheduled tasks.", sub: [
        ["add", "添加一个定时任务。", "Add a scheduled task."],
        ["history", "显示某个定时任务的执行历史。", "Show execution history for a schedule."],
        ["list", "列出所有定时任务。", "List all scheduled tasks."],
        ["remove", "按 ID 移除一个定时任务。", "Remove a schedule by ID."],
        ["run", "手动触发一次定时任务(不影响常规节奏)。", "Manually trigger a schedule once (does not affect regular cadence)."],
        ["toggle", "启用或禁用一个定时任务。", "Enable or disable a schedule."],
      ]},
      { name: "task", zh: "任务状态管理(发出 timeline task_state 条目)。", en: "Task state management (emits timeline task_state entry).", sub: [
        ["active", "列出状态为 {queued, executing} 的任务。", "List Tasks in status in {queued, executing}."],
        ["awaiting", "列出状态为 awaiting_decision 的消息(PA 尚未决策)。", "List Msgs in status=awaiting_decision (PA has not decided yet)."],
        ["history", "显示某任务跨 resume / restart 的完整时间线。", "Show the full timeline of a task across resume / restart."],
        ["list", "列出当前看板快照 —— threads、msgs、tasks。", "List the current board snapshot — threads, msgs, tasks."],
        ["mark", "覆盖任务状态并发出一条 task_state 时间线条目。", "Override a task's status and emit a task_state timeline entry."],
        ["stats", "看板的长期健康统计。", "Long-running health stats for the board."],
        ["vacuum", "frago timeline vacuum 的别名:归档已退役的 thread。", "Alias for `frago timeline vacuum`: archive retired threads."],
      ]},
      { name: "timeline", zh: "查询统一时间线并向其追加。", en: "Query and append to the unified timeline.", sub: [
        ["append", "向时间线追加一条条目(agent 发起)。", "Append an entry to the timeline (agent-initiated)."],
        ["fold", "将 thread 内冗余条目折叠为单条摘要。", "Fold redundant entries inside a thread into a single summary."],
        ["search", "按结构化过滤条件搜索时间线条目。", "Search timeline entries by structured filters."],
        ["tail", "显示最近的时间线条目(最新在前)。", "Show the most recent timeline entries (newest first)."],
        ["task-status", "显示某任务的当前状态(从条目重建)。", "Show the current status of a task (reconstructed from entries)."],
        ["trace", "从给定条目沿 parent_id 链上溯到 thread 根。", "Walk parent_id chain from the given entry up to its thread root."],
        ["vacuum", "运行有界推进的 vacuum:将退役 thread 归档到冷存储。", "Run bounded-progress vacuum: archive retired threads into cold storage."],
        ["view", "给定时间窗口的高层时间线视图。", "High-level timeline view for the given window."],
      ]},
    ]
  },
];

// 动态领域命令:具体领域名属用户本地私有数据(~/.frago/books/),本公开手册不收录清单,
// 仅说明机制。本地用 `frago def list` 查看自己的领域。
