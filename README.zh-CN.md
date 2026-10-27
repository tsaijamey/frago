<div align="center">

<img src="docs/images/logo.png" width="72" alt="frago" />

# frago

**面向 CLI 代理的本地控制中心与运行时**

不止于编程——把 **Claude Code**、**codex**、**opencode**、**agy** 收进同一个千级会话工作台，用真机 Chrome 操控、零 Token 配方固化与事件级护栏接管你的日常与工程任务。

简体中文 · [English](README.md) · [**安装**](#安装) · [使用指南](docs/user-guide.zh-CN.md) · [配方系统](docs/recipes.zh-CN.md) · [讨论区](https://github.com/tsaijamey/frago/discussions)

[![PyPI](https://img.shields.io/pypi/v/frago-cli?style=flat-square&color=12a150)](https://pypi.org/project/frago-cli/)
[![License](https://img.shields.io/badge/license-MIT-12a150?style=flat-square)](LICENSE)
[![Stars](https://img.shields.io/github/stars/tsaijamey/frago?style=flat-square&color=12a150)](https://github.com/tsaijamey/frago/stargazers)
[![Platform](https://img.shields.io/badge/macOS%20·%20Windows%20·%20Linux-12a150?style=flat-square)](docs/installation.zh-CN.md)

<img src="docs/images/hero-workbench.png" width="880" alt="frago 控制台：统一管理千级会话，实时查看 Agent 执行日志与动作流" />

</div>

> frago 与 OpenClaw（龙虾）无关。frago 的启动时间早于 OpenClaw 约一个月。

## 一句话理解 frago

**frago = 面向 CLI 代理的本地开发者控制中心与 AI 操作系统（Agent OS）。**

frago 不制造封闭大模型，也不把你的数据搬去云端沙箱。它直接接管你本机的 **Claude Code**、**codex**、**opencode** 与 **agy**——把散落在终端窗口里的会话收进统一网页工作台，并为所有代理装上真机浏览器手脚、持久记忆与零 Token 可复用配方：

- **千级会话统一网页看板**（`frago start`）：将 Claude Code、codex、opencode、agy 的本地会话归一到 `http://127.0.0.1:8093`，按标题、目录或关键词全局检索，逐卡回看工具调用时间线并在网页端直接续聊。
- **真机 Chrome 操控与虚拟桌面舞台**（`frago browser` · `frago desktop`）：直接驱动带真实登录态的本地浏览器（天然通过反爬校验，按标签组隔离并发），或在无头虚拟桌面舞台上驱动演示并自动录制成片。
- **探索一次，固化为零 Token 配方**（`frago recipe`）：代理跑通一次的多步网页或系统操作，直接冻结为确定性的 Python、Shell 或 `chrome-js` 配方脚本，二次执行 **0 Token 消耗**、秒级复跑且不漂移。

## 为什么需要 frago

命令行代理（CLI Agent）具备强大的系统操控潜力，但在日常真实工程落地中，普遍面临三道阻碍：

- **单次会话孤岛**：能力与状态被锁死在单个终端窗口里。会话一旦关闭或换个目录，登录态、上下文与调用链路全部断裂，既难检索过往记录，也无法直接挂上凌晨三点的定时任务。
- **开场全量倾倒上下文**：为了让代理记住规范，常见做法是开场将成百上千行的规则文件全量塞进提示词，既消耗词元预算又稀释注意力；换个仓库或机器，立刻退回零记忆。
- **试错成果无法固化为确定性资产**：代理耗费大量推理试错跑通的自动化流程，往往只存为一段自然语言提示词；下次重跑依然靠模型从头推演，重复烧算力且面临输出漂移。

开发者缺少的不是又一个封闭的云端个人秘书，而是**一个跑在本机的控制中心与 Agent OS**——让任何主流 CLI 代理都能按纪律运行，并把跑通的经验沉淀为确定性代码。

## 核心理念：从使用 AI 到驾驭 AI（Harness Engineering）

AI 工程正在经历三次关键范式演进：
1. **提示词工程（Prompt Engineering）**：学会面对大模型；
2. **上下文工程（Context Engineering）**：学会使用大模型；
3. **套件工程（Harness Engineering）**：学会驾驭代理。

frago 通过三层技术基础设施实现这一范式：
- **规则（hook）决定代理知道什么**：事件触发时精准注入静态规范与情境提醒，零标记常驻开销；
- **配方（recipe）决定代理不用重复做什么**：代理跑通的试错流程直接固化为确定性代码，脱离模型推理运行；
- **技能（skills）决定代理具体怎么做**：向代理提供规范化的工程实践与场景标准。

## agent 面：核心能力支撑

这一层面向代理，提供标准的操作环境与系统级支撑：

| 核心能力 | 定义与核心职责 | 对应指令与机制 |
|---|---|---|
| **1. 实时护栏与运行纪律**<br>规则把关 | 静态规则基于关键事件精准注入，零模型常驻开销；LightAgent 在提交前、收尾时精准把关，防止行为跑偏 | `frago hook-rules`<br>`frago book`<br>`~/.frago/hook/*` |
| **2. 浏览器与桌面自动化操控**<br>真实环境操作 | 接管真实登录态的浏览器与可脚本驱动、可录制的虚拟桌面，操作步骤清晰可见可留存 | `frago browser`<br>`frago desktop`<br>`frago apps`<br>`frago view` |
| **3. 长短期持久记忆**<br>结构化检索 | 将记忆分拆为决策层、产物层、过程层与任务交接层，按需精准检索，杜绝上下文盲目堆叠 | `frago def`（决策）<br>`frago context`（产物）<br>`frago session search`（过程）<br>`frago todo`（交接） |
| **4. Recipes 配方**<br>可复用工作流 | 代理摸索跑通的流程直接固化为独立脚本工具；支持模块化调用、后台常驻守护与市场共享 | `frago recipe`<br>`frago daemon`<br>`frago market` |
| **5. 多 Agent 协同与任务调度**<br>多任务派发与协同 | 驱动独立工作子会话、接收即时通信渠道进件并处理、支持远程任务下发与定时调度常驻 | `frago agent`<br>`frago channel` · `frago reply`<br>`frago remote`<br>`frago schedule` |

## 人面一层：统一可视化控制台

面向用户提供透明可视的运维与管理入口，与代理底层执行逻辑清晰解耦：

| 模块 / 指令 | 它带来什么 |
|---|---|
| **统一控制台**<br>`frago start` · `frago server` | 归一主流命令行 Agent 的记录格式，在统一的 Web 界面中集中查看执行日志与动作时间线 |
| **模型配置管理**<br>`frago profile` | 集中管理多家模型供应商的凭证与接入点，代理按需索取，免去命令行繁琐配置 |
| **配方市场**<br>`frago market` | 浏览并一键安装社区验证的可复用工作流方案，将个人工具一键发布共享 |
| **环境与维护**<br>`frago init` · `frago update` · `frago autostart` | 提供一键环境就绪、开机常驻守护与无缝版本升级机制 |

## 能拿它做什么

上面是指令，这里是场景——都由配方承载，配方由你的 Agent 现写：

- **让你不再需要 Office**，因为你完全可以让 Agent 按照配方规格帮你做一个
- **让你不再需要为一段教学视频重录第七遍**，在虚拟舞台上演一次，录完就是成片
- **让你不再需要把会议录音交给第三方**，转写、提要点、列行动项都在你自己机器上
- **让你不再需要在几个网站之间来回复制粘贴**，Agent 用你已登录的浏览器一趟走完
- **让你不再需要手动整理调研资料**，抓回来、去重、成文、落到固定位置，一条配方到底
- **让你不再需要记住上次那件事怎么做的**，走通过一次，它就是一段随时能重跑的代码

### 🖥 把终端里的 agent，搬进网页

#### 任务：「打开这个网站，把标题和正文第一句读给我」

<p align="center"><img src="docs/images/feedback-detail.png" width="780" alt="一次工具调用的完整回执：命令、成功标记、时间戳、返回值" /></p>

先说清楚哪部分不是 frago 干的：命令、`成功`、时间戳、返回值，
**是你用的那个 cli-agent 自己产生的**——这台机器上同时跑着 Claude Code 和 opencode，
上图这场恰好是前者。回执它们本来就有，只是各自滚在各自的终端窗口里，管理不方便。

frago 不生产回执，**也不挑边**。它做的是把**每一家**的记录读进来、
归一成同一种形状、变成同一张网页。

|  | 终端里 | frago 网页 |
|---|---|---|
| **翻历史会话** | 类似 resume 的选择器不好用 | 1299 场排成一张列表，可按标题、目录、会话编号搜 |
| **换一个 cli-agent** | 每家一套自己的记录、自己的翻法 | 归一成同一种形状，合成一份清单（图中 Claude Code 1201 场 + opencode 98 场） |
| **一场会话的经过** | 一屏一屏往回翻 | 逐条卡片摊开，按 `在跑 / 已完成 / 停着 / 出错` 分档 |
| **接着往下说** | 得找回那个终端窗口 | 在网页上直接说 |
| **用了多少** | 自己数 | 用量月历 |

对天天泡在 CLI 里的人，这是个方便；
对不用 CLI 的人，这是**能不能用上 agent 的分界线**。

（上图中间那两条 `PreToolUse:Bash` 是会话伴侣插进来的——一条报回执，一条补上下文，见下。）

下面这一层才是 frago 自己干的活：

| 这一层 | frago 的做法 | 你得到的结果 |
|---|---|---|
| **登录态** | 默认驱动你浏览器**自己的真实 profile** | 已经登录的网站直接可用，不用重新扫码 |
| **反爬** | 它**就是**一台真实浏览器，不是模拟器 | 检测天然通过 |
| **并发** | 每个 agent 待在自己的真实标签组里 | 两个 agent 同时干活不打架，扫一眼标签栏就知道哪些页是谁的 |

### 🛠 走通一次之后，agent 会给自己造一个工具

#### 任务：「这套回测以后我要能自己反复调参数」

<p align="center"><img src="docs/images/etf-dashboard.png" width="800" alt="ETF 回测仪表盘：参数面板、净值曲线、逐笔盈亏" /></p>

<p align="center"><sub>图为 ¥100,000 虚拟本金的<b>模拟回测</b>，用于展示界面，不构成任何投资建议。</sub></p>

> **这只是其中一个。** 上面这张图来自一台开发机上的 **317 个个人配方**中的一个，
> 挑它出来只是因为它好看。frago 不是炒股工具——同一台机器上的其他配方在做：
> 剪视频、写文章、转写会议、抓 arXiv 论文、扒公开神经科学数据集、
> 合成语音、生成分镜图、整理会话账本、填高考志愿。
> **配方长成什么样，取决于你让 agent 反复做什么。**

这是 frago 和「一个很能干的 agent」最大的区别：走通的路不会烂在聊天记录里，
它被固化成一份 **Recipe**——真正的、确定性的 Python/Shell 代码。

|  | 第一次 | 之后每一次 |
|---|---|---|
| **谁在干** | agent 一步步试 | 一段确定性代码 |
| **过模型吗** | 过 | **不过** |
| **结果** | 这次这样，下次可能那样 | 和上次一模一样 |
| **token** | 烧 | **不烧** |

**Recipe 是 agent 给自己造的工具，不是给人看的文档。**

|  | 给 agent 的那一面 | 给人的那一面 |
|---|---|---|
| **形态** | `recipe.md` + 确定性代码 | `/app/<配方名>` 上的一个网页 |
| **怎么用** | `recipe list --format json` 发现 · `run` 执行 · `schedule` 定时 | 点开，调参数，看结果 |
| **必须有吗** | 是，这是配方本体 | **否**——很多配方从头到尾没有界面，照样是完整的软件 |

只有当一件事**人也需要看一眼**的时候——比如上面这个回测，参数得由人来调、
曲线得由人来判断——配方才顺手挂一个界面上去。界面是可选的那一层，不是终点。

### 🎬 需要演示的时候，它还有一块舞台

#### 任务：「把刚才那套操作录成教学视频」

<p align="center"><img src="docs/images/agent-os-stage.png" width="760" alt="agent_os 虚拟桌面舞台：浏览器里的一块假 macOS 桌面，终端和网页底下都是真的" /></p>

看着是一块 macOS 桌面，其实底下全是真的：那个终端是真实 tmux 会话，
那个浏览器窗口是真实标签页，鼠标移动和点击可复现。
一次表演，录成视频，随时重放——不用再对着屏幕重录第七遍。

## 工作原理

<p align="center"><img src="docs/images/how-it-works.svg" width="860" alt="frago 工作原理：你说一句话 → agent 在真实浏览器/文件/屏幕上干活并当场回执 → 走通了固化成 Recipe → 顺手一扇窗；全程有会话伴侣在线" /></p>

图里最下面那条是**会话伴侣**，也是最容易被低估的一层。它由两层叠成：

| 层 | 是什么 | 过模型吗 | 命中速度 | 费用 |
|---|---|---|---|---|
| **frago-core** | 静态规则编译进一个 3 MB 的原生二进制 | **否** | 本机实测 34–961 ms，随注入体积走 | **零** |
| **轻量 AI** | 按你自己的标准，在恰当时机补一句上下文 | 是，但只跑很短的提示 | 一次调用 | 极低 |

它做的事只有一件——盯着 agent 别跑偏：

| 常见的跑偏 | 伴侣做的事 |
|---|---|
| 该用浏览器时凭记忆瞎猜 | 当场按住，指回真实浏览器 |
| 产出乱建目录 | 指到已有的落点上 |
| 你纠正过一次的毛病又犯 | 下次同样场景自动提醒 |

因为静态那层根本不花钱、AI 那层只跑很短的提示，**它便宜到可以一直开着**。
设置页实时展示这两层此刻的状态，没有黑话。

## 示例：我个人创建的配方

**仅作示例。** 下面这些**不是 frago 内置的，也不随安装包分发**，更不是什么推荐清单——
它们是我自己机器上的私人配方，围着我自己的生活和工作长出来的，
放在这里只为回答一个问题：配方能长成什么样。

你装完 frago 是一张白纸。配方由**你的** agent 在**你的**重复劳动里长出来，
大概率和下面这几个毫无关系。

| 配方 | agent 做的事 | 人看到的 |
|------|-------------|---------|
| `agent_os` | 把真实 tmux 会话和真实浏览器标签页，重构成一块可脚本操控的虚拟 macOS 桌面 | `/app/agent_os` 上的实时舞台 |
| `etf_backtest_dashboard_v5` | 零参数跑 A股 / 跨境 ETF 策略回测，一组接一组 | 参数滑杆、净值曲线、逐笔盈亏 |
| `etf_kdj_ths_auto_trade` | 盯 5 分钟 KDJ 信号，直接在同花顺客户端下单 | 成交回执和持仓核对（链路里没有 LLM） |
| `gaokao_henan_volunteer_analysis` | 分数换算全省位次，按家庭学费预算与地域匹配院校，主动揭穿民办伪装公办、天价中外合作这类套路 | 一份带可核实清单的报告，另有网页版 |
| `meeting_copilot` | 实时转写会议全程，结合本地材料提炼要点、疑问、行动项，还能克隆音色替你开口 | 滚动的转写稿和提问列表 |
| `article_studio` | 一文一常驻编辑 agent——访谈你、按你的语气顺句、写回 HTML | 左栏文章列表，右栏阅读 + 写作/访谈区 |

## 安装

**没有东西要下载。** 装 frago 的是你手上已经有的那个 agent：把安装 skill 加进 Claude Code，然后开口
要它装。skill 会备好 git 和 uv、拉源码、建环境、部署 hook，再带你把凭证配上，最后开一张欢迎页，让
这台机器自己演一遍它现在能干什么——整个过程你不用亲手敲一条 frago 命令。

```
/plugin marketplace add tsaijamey/how-to-install-frago
/plugin install how-to-install-frago@how-to-install-frago
```

然后开口就行：**安装 frago**

→ [**how-to-install-frago**](https://github.com/tsaijamey/how-to-install-frago) — skill 自己的仓库

macOS、Windows、Linux 都能用。驱动安装的是 Claude Code；装完之后 opencode、codex 也可以作为 agent
内核使用。装 frago 本身只要 git 和 uv，另外几样是按能力来的——派活要 tmux、浏览器自动化要 Edge、
录制要 ffmpeg、Linux 上跑配方要 bubblewrap。skill 会问你打算用哪些，配好它们，并说清哪些仍然用不了。

<details>
<summary><b>想自己动手装？</b> 包在 PyPI 上。</summary>

<br>

需要 Python 3.13+。这条路给你 CLI 和网页界面，但 skill 做的那些机器准备工作一样都没有——hook、
凭证、各项能力的依赖都得你自己来。

```bash
uv tool install frago-cli   # 安装
frago init                  # 检查依赖、配好一个模型 profile
frago server start          # 启动网页界面，打开 http://127.0.0.1:8093
```

还没装 uv，或者想用一行命令装好，见[安装指南](docs/installation.zh-CN.md)。

</details>

> frago 没有桌面客户端。GitHub Releases 页面上旧版本附带的安装包已停止维护。

## 文档

- [使用指南](docs/user-guide.zh-CN.md) — 安装后的入门指引
- [关键概念](docs/concepts.zh-CN.md) — Recipe、Run、Session 与提示注入如何协作
- [Recipe 系统](docs/recipes.zh-CN.md) — 配方命令面，端到端
- [示例参考](docs/examples.zh-CN.md) — 实际的 Run + Recipe + 浏览器工作流
- [内核对比](docs/agent-cores.zh-CN.md) — Claude Code / codex / opencode 的等价能力、差异能力与用法差异
- [浏览器支持](docs/browser-support.zh-CN.md) — 后端、端口、标签组、桌面舞台
- [开发者文档](docs/developer.zh-CN.md) — CLI、架构、开发环境

产品内部，`frago book` 读取随包分发的知识库——与代码同步的操作手册，两边冲突时以它为准。

## 许可证

MIT — 详见 [LICENSE](LICENSE)

## 贡献

- [提交 Issue](https://github.com/tsaijamey/frago/issues)
- [技术讨论](https://github.com/tsaijamey/frago/discussions)
- [社区配方](https://github.com/tsaijamey/frago-recipe-community) —— 公开配方住在它自己的仓库

---

<div align="center"><sub>Created with Claude Code</sub></div>
