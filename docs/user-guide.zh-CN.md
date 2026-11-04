# 使用指南

[English](user-guide.md)

## 浏览器命令

所有浏览器控制通过 `frago browser <command>`：

```bash
# 导航
frago browser navigate <url>
frago browser status

# 交互
frago browser click <selector>
frago browser scroll <distance>
frago browser wait <seconds>

# JavaScript
frago browser exec-js <expression> --return-value

# 截图
frago browser screenshot <output_file>

# 视觉效果
frago browser spotlight <selector> --life-time 3
frago browser highlight <selector> --color "#FF6B6B"
frago browser annotate <selector> "text" --position top
```

每条页面命令都作用于一个**标签组**：显式传 `--group <name>`，或让它默认取
`$FRAGO_CURRENT_RUN`。组是浏览器里真实的标签组——`navigate` 默认替换组内
当前标签，`--new` 才是新开一页的唯一方式。

有两个后端。默认 **extension** 后端驱动浏览器自己的真实 profile，不需要任何
flag——浏览器是 Chrome for Testing，frago 自己取，取不到才退回你装过的那个。
扩展没连上时的正确动作是 `frago browser start`，不是换后端：这时候弹出一个浏览器
窗口是预期行为。**CDP** 后端（`-b cdp`）只留给虚拟桌面舞台和它的录制机位——一个
真无头的舞台浏览器、一个独立的录制实例——不是常规页面操作的备用方案，详见
[浏览器支持](browser-support.zh-CN.md)。

### 代理配置

```bash
# 环境变量
export HTTP_PROXY=http://proxy.example.com:8080
export HTTPS_PROXY=http://proxy.example.com:8080

# CLI 参数（全局标志放在子命令之前）
frago --proxy-host proxy.example.com --proxy-port 8080 browser navigate https://example.com
frago --no-proxy browser navigate https://example.com
```

## Recipe 管理

```bash
# 发现
frago recipe list                    # 列出所有配方
frago recipe list --format json      # JSON 格式（供 AI 使用）
frago recipe list --source user      # 按来源过滤
frago recipe list --type atomic      # 按类型过滤

# 信息
frago recipe info <name>             # 查看详情
frago recipe info <name> --format json

# 执行
frago recipe run <name> --params '{"url": "..."}'
frago recipe run <name> --params-file params.json
frago recipe run <name> --output-file result.txt
frago recipe run <name> --output-clipboard
frago recipe run <name> --timeout 300
```

### Recipe 优先级

```
1. User (~/.frago/recipes/)                 ← 较高（个人写的）
2. Community (~/.frago/community-recipes/)  ← 较低（装来的）
```

### 配方从哪来

**安装包一个都不带。** 刚装完的 frago 跑不了任何配方，要先自己写一个或装一个——
这是有意的：这台机器能干什么，看得见地写在「谁往上面放了什么」里，
而不是藏在安装包里。

公开配方（YouTube、Bilibili、arXiv、飞书/Lark、微信、TTS、视觉识别……）
住在 [frago-recipe-community](https://github.com/tsaijamey/frago-recipe-community)，按需安装：

```bash
frago recipe search <关键词>
frago recipe install community:<recipe-name>
frago recipe list --source community
```

自己写的配方想让别人也能用，`frago recipe share <name>` 会替你把 PR 提过去。

recipe 命令组还有 `plan`、`create`、`schedule`、`publish`、`search`、
`update`、`uninstall` 等子命令，见 [Recipe 系统指南](recipes.zh-CN.md)。

## 产出落盘与经验沉淀

> 旧的 Run 系统（`run init` / `set-context` / `archive` / `insights`）已退役，
> `~/.frago/projects/` 现在是 frago 自己的会话账本，agent 不写。

```bash
# 先找现成落点，别另起炉灶
frago context data:<关键词>

# 经验当场存进知识域
frago def list                       # 有哪些域
frago <域名> find                    # 域里已有什么
frago <域名> save --name=<文档名> \
  --data='{"tags":["..."]}' --content='[...]'

# 想翻从前干过的事
frago session search "<一句话>"      # 按意思搜，跨 Claude Code、codex、opencode
```

### 产出目录结构

产出一律落在 `~/.frago/data/<主体>/<YYYYMMDD>-<slug>/`，两层缺一不可：

```
~/.frago/data/research/20260812-youtube-transcript/
├── scripts/                  # 已验证的脚本
├── outputs/                  # 结果文件
└── screenshots/              # 带时间戳的截图
```

## 会话监控

```bash
frago session list                   # 列出会话（全部 agent 类型）
frago session list --status running  # 按状态过滤
frago session list --agent-type opencode  # 按 agent 过滤（claude|opencode|coreagent|cursor|cline）
frago session show <session_id>      # 显示详情
frago session search "关键字"        # 搜索会话记录
frago session watch                  # 监控最新会话
frago session watch <session_id>     # 监控指定会话
frago session sync --all             # 同步全部项目的 Claude Code / opencode 会话
frago session clean                  # 清理过期记录
frago session delete <session_id>    # 删除一个会话
```

来自多种 agent 运行时（Claude Code、codex、opencode、Cursor、Cline）的会话会被
统一规整到 `~/.frago/sessions/`；frago 自己跑起来的 agent 会话也落在那里，标为
`coreagent`。

## Web 服务

```bash
frago start             # 启动服务并在浏览器里打开界面
frago server start      # 在端口 8093 启动
frago server stop       # 停止服务
frago server status     # 检查状态
frago server --debug    # 前台运行带日志
```

访问：`http://127.0.0.1:8093`

### 功能

- **会话**：agent 会话与其记录的实时时间线
- **桌面**：agent 驱动录制与演示用的虚拟桌面舞台
- **结对**：两个人的会话并排摆着
- **配方**：浏览本地与社区配方、查看参数、一键运行
- **事务**：本地待办清单，一条一个 JSON 文件
- **定时任务**：由 frago 服务按排定时间运行配方、命令或一段自然语言
- **数据**：把 `~/.frago` 备份到你自己的 git 远端
- **文件**：浏览本机的目录树
- **任务**：发起一个新 agent 任务并观看执行
- **技能**：管理已安装技能（配方页上的「技能」标签）
- **工作空间**：发现的项目，以及从项目里收集上来的 agent 资源
- **指南**：内置文档
- **设置**：提示能力（静态规则 + LightAgent）、模型 profile、CLI 客户端、任务通道、官方资源同步（命令与技能）、外观、关于

## 资源与同步

配方和技能通过三条独立路径在设备间流转。

### 项目资源（workspace）

```bash
frago workspace set-scan-roots ~/repos/ ~/work/   # 指定扫描哪些目录
frago workspace list                              # 列出发现的项目
frago workspace collect --dry-run                 # 预览将要收集的内容
frago workspace pending                           # 等待从其他设备部署的变更
```

`workspace` 从扫描根目录收集 agent 资源——技能、`CLAUDE.md`、项目记忆。

### 会话记录

```bash
frago session sync           # 把 Claude Code / opencode 会话同步进 ~/.frago/sessions/
frago session sync --all     # 同步全部项目
frago session sync --force   # 已存在的会话也重新同步
```

### 官方资源

**设置 → 官方资源** 可开启官方命令与技能的定时同步。配方不在其中——配方来自社区
仓库，什么时候更新由你自己敲 `frago recipe update` 决定。密钥（Secrets）在任何
路径下都不会被同步。

## 故障排除

### CDP 连接

CDP 后端服务的是虚拟桌面舞台和它的录制机位：frago 管理的浏览器实例，永远不要
自己手起 Chrome。常规页面操作留在默认的 extension 后端。

```bash
frago browser -b cdp start --headless   # 独立无头实例（端口 9222）
frago browser status                    # 健康检查
frago browser -b cdp stop               # 拆除实例
```

- 端口是白名单制：**9222**（默认）与 **9223**（agent_os 录制机位）。传别的值会被拒绝。
- 虚拟桌面舞台在跑时，它的演员常驻在 **9222** 上——`-b cdp start` 会顶掉该端口已有实例，所以先 `frago desktop status` 确认舞台没在跑。
- 永远不要用裸 `--remote-debugging-port` 手起浏览器；常规页面操作由 extension 后端覆盖，舞台要的无头与独立实例由 `-b cdp` 覆盖。

### 常见问题

| 问题 | 解决方案 |
|------|----------|
| CDP 超时 | 确认 CDP 实例在运行：`frago browser -b cdp start`（舞台在跑时先 `frago desktop status`） |
| Recipe 未找到 | 用 `frago recipe list` 检查名称拼写 |
| 截图失败 | 使用绝对路径，确保目录存在 |
| Node.js 版本 | 使用 nvm：`nvm install 20 && nvm use 20` |

---

**下一步**：[概念](concepts.zh-CN.md) · [Recipe 系统](recipes.zh-CN.md)
