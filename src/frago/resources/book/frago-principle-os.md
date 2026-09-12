# frago-principle-os

分类: 第一性原理（AVAILABLE）

## 解决什么问题
agent 不知道 frago 是什么品类的东西，会按「普通 CLI 工具」对待——缺少 frago 应当被赋予的特殊地位（agent 的运行环境，而非 agent 的对手或助手）。这条原则把 frago 的定位说清楚，并把 agent 在 frago 上能做的事按支柱分好：一件事该找哪根支柱，看一眼就知道。

## 第一性原理

frago = **agent OS**，AI agent 的操作系统。

frago 不造 agent。agent 指 Claude Code / codex / opencode / codebuddy 等外部 agent，frago 为它们提供「可运行的环境」——agent 知道怎么做、在哪里动手、记得什么、把跑通的事冻成什么、怎么和这场会话之外的世界打交道。

## 底座：内核可换

frago 不绑定某一个 agent。Claude Code / codex / opencode / codebuddy 任一个装上就是内核，同一份 hook 引擎注册进各家，下面五根支柱对每一种内核都成立。

你怎么用它：你是哪种内核不影响你怎么用 frago。NEVER 因为自己是 Claude Code 就假设别的内核用不了这些命令，也 NEVER 把 frago 理解成某个内核的封装。

## agent 面：五根支柱

回答的问题：agent 在 frago 上怎么活。

| 支柱 | 定义 | 对应命令 |
|---|---|---|
| 1. 会话伴侣：知道怎么做 | 两层。静态规则按事件精准注入，不用模型；LightAgent 在提交前、收尾时、否决前三处各判一次。book 是被注入的内容 | frago-core、`frago hook-rules`、`frago book`、`~/.frago/hook/*` |
| 2. 手和眼：在真实环境里操作 | 你登录着的浏览器、一块可录制的桌面、内置交付能力、内容查看 | `frago browser`、`frago desktop`、`frago apps`、`frago view` |
| 3. 记忆与召回：三入口加交接 | 结论层、产物层、过程层各一个入口，外加待办把没做完的事交给下一场 | `frago def` / `frago <域名>`、`frago context`、`frago session search`、`frago todo` |
| 4. 配方：跑通一次冻成代码 | agent 自己造的工具，确定性、零 token；模块化、可互调、可挂页面、可开放给指定的人、可调度、可守护、可上市场 | `frago recipe`、`frago daemon`、`frago market` |
| 5. 边界：派活、进件、远程、定时 | agent 与其他 agent、与外界、与另一台机器、与时钟之间的接口 | `frago agent`、`frago channel` / `frago reply`、`frago remote`、`frago schedule` |

### 1. 会话伴侣：知道怎么做

定义：frago 不靠一份常驻的大文档告诉你规则，靠两层伴侣在事件发生的那一刻推给你。第一层是 frago-core 的静态规则（随包规则在 `~/.frago/hook/builtin-rules.json`，用户规则在 `~/.frago/hook-rules.json`），不用模型，零成本；第二层是 LightAgent，在你提交 prompt 前指路、收尾时判完没完、否决前复核，说明书在 `~/.frago/hook/{prompt,stop,veto}.md`。`frago book` 是这两层注入给你的内容本体。

命令：`frago hook-rules list/show/add`、`frago book <主题>`、`frago book --brief`。

你怎么用它：不用主动调它——hook 注入到上下文里的内容就是这一支柱在说话，照它做。注入只给一条速记，要全文时跑 `frago book <主题>`。同一类事件反复需要同一类提醒，用 `frago hook-rules add` 沉淀成规则，NEVER 写进常驻文档，见 `frago book frago-principle-extend`。

### 2. 手和眼：在真实环境里操作

定义：agent 动手的地方不是沙盒，是这台机器上真实的浏览器、桌面和文件。浏览器是你已经登录着的那个；桌面是一块可脚本驱动、可录成视频的舞台，窗口里是真 tmux、真标签页；内置交付能力是「输入一段话，产出一件成品」；内容查看负责把 Markdown / PDF / 代码读成你能用的形状。

命令：`frago browser`、`frago desktop`、`frago apps list/use`、`frago view`。

你怎么用它：与网页有关的一切走 `frago browser`，NEVER 用 WebFetch / WebSearch，NEVER 自起浏览器进程（`frago book must-browser-search`、`browser-usage`）。要演示、录屏走 `frago desktop`，标准路径 status → up → 驱动（`frago book desktop-usage`）。要一件成品先看 `frago apps list` 有没有现成的。

### 3. 记忆与召回：三入口加交接

定义：你每次启动都是零记忆，这台机器、这个人、这套流程的事实全在 frago 里。三个入口回答三个不同的问题：结论层（这件事沉淀成结论了吗）、产物层（上次那份东西落在哪）、过程层（当时怎么做的、为什么这么定、用户原话是什么）。交接是第四件事：会话尾声把没做完的事连同会话 id 交给下一场。

命令：`frago def list` → `frago <域名> find/save`、`frago context data:<关键词>`、`frago session search "<一句话>"`、`frago todo add/next/show/log`。

你怎么用它：不知道就先召回，NEVER 先推理，三个入口互不替代，查了一个不等于查过了（`frago book frago-principle-recall`）。凡是问「为什么是这样」「上次怎么办的」，过程层 MUST 查。这一轮学到的本机事实用 `frago <域名> save` 存回去；没做完的事用 `frago todo add` 交出去（`frago book session-handoff`）。

### 4. 配方：跑通一次冻成代码

定义：配方是 agent 给自己造的工具，不是给人看的说明书。第一次由 agent 一步步试出来，之后每一次是一段确定性的代码，不用模型、零 token、结果和上次一模一样。配方已是模块系统：基类、总线、导出与导入、契约描述头；可以挂页面、按身份开放给指定的人、按点跑、常驻守护、上市场分享。界面是可选的那一层，不是重点。

命令：`frago recipe list/info/run/create/validate/expose/schedule/search/share/install`、`frago daemon`、`frago market`。

你怎么用它：动手前先 `frago recipe list`，有现成的就用，NEVER 从零写脚本重做一遍（`frago book must-tool-priority`）。写临时脚本前过一道判断闸：这段劳动会不会再来一次，会就固化成配方（`frago book better-recipe-gate`）。写配方按 `frago book recipe-creation`，数据落点按 `frago book must-recipe-data`，开放给人按 `frago book recipe-expose`。

### 5. 边界：派活、进件、远程、定时

定义：这一支柱的命令对象都不是本机的文件或页面，而是另一个会话、另一个渠道、另一台机器、时钟。派活是一个会话拉起另一个 cli-agent 会话干子任务，交付物走 attach 回到主控；进件是从飞书、邮件、Slack 等渠道收任务、把结果发回同一渠道；远程是给服务器上另一台 frago 下发任务书；定时是命令、配方按点由 frago 直接执行，自然语言任务才交给 PA。

命令：`frago agent start/send/peek/stop/attach`、`frago channel` + `frago reply`、`frago remote add/send/status`、`frago schedule`。

你怎么用它：子任务用 `frago agent` 驱动 worker，NEVER 手搓 tmux + claude（`frago book agent-worker-driving`）；你自己是 worker 时直接把活干完，NEVER 再拉起新的 agent 会话。外部渠道来的任务用 `frago reply` 回到它来的那个渠道。远程下任务书说要什么结果，不写命令序列（`frago book remote-frago`）。定时任务按 `frago book schedule-tasks` 的三形态选。

## 人面：一层

frago 也有会话工作台与 WebUI、模型供应商 profile、配方市场、安装与自更新（`frago start / profile / market / update / autostart`）——**那些是给人用的**。agent 通过五根支柱看见 frago，这一层不归 agent 管；agent 只在给人指路时提它，比如「去 WebUI 设置页改 profile」。

## agent OS 是个什么品类

业界没有标准定义。frago 是这个定义的一次具体落地。所以：
- 不要按「自动化工具」理解 frago（它不只是 RPA）
- 不要按「Claude Code 的封装」理解 frago（内核可换，它不依赖某个具体 agent）
- 按「操作系统支持多种应用程序」那个比喻理解——agent 是跑在 frago 上的「应用」，五根支柱是这个操作系统给应用的系统调用
