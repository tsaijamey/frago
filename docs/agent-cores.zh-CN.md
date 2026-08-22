# 三个 cli-agent 内核的详细区别：Claude Code / codex / opencode

frago 把 cli-agent 称作**内核**（core）：会话由谁承载、代码由谁改、钩子由谁触发。
目前支持三个，本文写清它们的等价能力、差异能力与用法差异。

## 这份文档钉在哪个版本上

| 内核 | 版本 | 二进制来源 |
|---|---|---|
| Claude Code | 2.1.235 | 官方原生安装器，`~/.local/share/claude/versions/<版本>` |
| codex (OpenAI Codex CLI) | 0.147.0 | Homebrew cask，`/opt/homebrew/Caskroom/codex/<版本>/bin/codex` |
| opencode | 1.18.15 | 原生二进制 |

三家都在快速迭代，**下面每一条都是在上述版本上实地核对过的**，不是照文档转述。
换版本前先自己验一遍：这三家过去半年里都发生过「同一个开关换了语义」的事
（例：codex 0.147 移除了 `wire_api = "chat"`，照抄 2025 年的第三方接入教程必踩）。

---

## 一句话定位

- **Claude Code** — Anthropic 官方 CLI。生态最厚（技能、插件、子 agent、SDK、云端评审），
  模型分三档（主/中/快），权限靠策略而非沙箱。
- **codex** — OpenAI 官方 CLI。**唯一自带操作系统级沙箱**的一家；配置集中在一个
  `config.toml`，CLI / 桌面版 / VS Code 扩展三端共用；钩子协议刻意做成 Claude Code 的形状。
- **opencode** — 社区开源。**扩展模型完全不同**：插件是进程内 JS，能改的东西比另外两家深得多；
  自带无头服务端、Web 界面与 ACP，是三家里最容易被别的程序当组件嵌进去的一个。

---

## 等价能力

这些三家都有，差别只在名字和写法。

| 能力 | Claude Code | codex | opencode |
|---|---|---|---|
| 交互式 TUI | `claude` | `codex` | `opencode` |
| 一次性非交互执行 | `claude -p "<提示词>"` | `codex exec "<提示词>"` | `opencode run "<提示词>"` |
| 续接既有会话 | `claude --resume <uuid>` | `codex resume <uuid>` | `opencode -s <id>` |
| 续上最近一场 | `claude --continue` | `codex resume --last` | `opencode -c` |
| 分叉会话 | `--fork-session` | `codex fork` | `--fork` |
| 指定模型 | `--model` | `-m` / `-c model=…` | `-m <provider>/<model>` |
| MCP 客户端 | `claude mcp` | `codex mcp` | `opencode mcp` |
| 自身作为 MCP server | 有 | `codex mcp-server` | 有 |
| 子 agent | `--agents` / `claude agents` | `spawn_agent` 工具 + subagent 事件 | `opencode agent` |
| 自检 | `claude doctor` | `codex doctor` | `opencode debug` |
| 从别家导入配置 | `claude import` | `codex` 的外部 agent 迁移流程 | — |
| 自升级 | `claude update` | `codex update` | `opencode upgrade` |
| 项目级指令文件 | `CLAUDE.md` | `AGENTS.md` | `AGENTS.md`（从 cwd 逐级上溯到项目根，另可用配置里的 `instructions` 追加） |

**钩子事件集三家里有两家完全一致。** Claude Code 2.1.235 与 codex 0.147 都实现了
`PreToolUse` / `PostToolUse` / `UserPromptSubmit` / `SessionStart` / `SessionEnd` /
`Stop` / `SubagentStart` / `SubagentStop` / `PreCompact` / `PostCompact` /
`PermissionRequest`；`Notification` 只有 Claude Code 有。两家的 stdin 载荷字段
（`session_id` / `cwd` / `hook_event_name` / `prompt` / `tool_name` / `tool_input` /
`transcript_path` / `permission_mode`）与 stdout 词汇
（`hookSpecificOutput.additionalContext` / `permissionDecision` / `updatedInput` /
`decision` / `systemMessage` / `continue` / `stopReason` / `suppressOutput`）逐字相同——
codex 的内部注释里甚至直接写着「Claude requires `reason` when `decision` is `block`」。
**这不是巧合，是 codex 有意做成兼容形状**，所以一份写给 Claude Code 的命令钩子基本可以
原样搬到 codex。

---

## 差异能力

### 只有 codex 有

- **真正的操作系统级沙箱。** `codex sandbox <命令>` 在 macOS 上走 seatbelt、Linux 上走
  landlock/bwrap，把模型生成的命令关进去跑。沙箱档位是 `read-only` /
  `workspace-write` / `danger-full-access`，与审批策略（`untrusted` / `on-request` /
  `never`）正交。另外两家的「权限」是**策略层拦截**，进程本身没有被关起来。
- **三端共用一份配置。** `~/.codex/config.toml` 同时服务 CLI、ChatGPT 桌面版和 VS Code
  扩展，配一次全生效。代价是：从 Dock/Finder 启动的那两端继承的是 launchd 环境、
  **读不到 `~/.zshrc` 里的环境变量**，所以密钥要么写进配置，要么用 `env_key` 指一个
  它们真能看见的变量。
- **命令行整段覆盖配置。** `-c <点分路径>=<TOML 值>` 可以在启动时定义出一个完整的
  provider，无需改任何文件（实测：一个只有 `model` 一行、零 provider 定义的干净家目录，
  纯靠 `-c` 就跑在了 DeepSeek 上）。
- **钩子信任门。** 非托管的命令钩子在人过目并信任之前**不会运行**，信任记录按钩子内容的
  哈希存在 `config.toml` 的 `hooks.state`；钩子一改就要重新过目。自动化场景用
  `--dangerously-bypass-hook-trust` 绕开。另外两家没有这道门——写进配置即生效。
- **钩子输出溢出落盘。** 单次钩子回给模型的内容默认约 2500 token，超出部分写进
  `<临时目录>/hook_outputs/<会话>/<uuid>.txt`，只给模型一段头尾预览加文件路径。
  每个处理器可以用 `additionalContextLimit` 单独调阈值。
- **后台钩子。** 处理器加 `"async": true` 就在后台跑，不挡当前操作；每会话最多八个并发。
- **企业托管钩子。** `requirements.toml` 里的 `[hooks]` 由管理员下发，标记为托管、
  按策略默认信任、用户关不掉；`allow_managed_hooks_only = true` 可以只留托管钩子。
- **插件市场**（`codex plugin marketplace`）、**目标（goals）**、**记忆（memories）**、
  **远程控制**、**云端任务**（`codex cloud`）。

### 只有 opencode 有

- **进程内插件，能改的东西深得多。** 插件是放在 `~/.config/opencode/plugin/` 的 ES 模块，
  导出一组钩子函数，通过修改传入的 `output` 对象生效。完整能力（取自
  `@opencode-ai/plugin` 的类型定义）：

  | 钩子 | 能改什么 |
  |---|---|
  | `chat.message` | 观察新到的用户消息 |
  | `chat.params` | 改发给模型的 temperature / topP / topK / maxOutputTokens |
  | `chat.headers` | 改发给 provider 的 HTTP 头 |
  | `permission.ask` | 把一次权限询问直接判成 `allow` / `deny` / `ask` |
  | `command.execute.before` | 改斜杠命令展开出的内容 |
  | `tool.execute.before` | **改工具入参**（只能改参数，不能注入上下文，也不能直接拒） |
  | `tool.execute.after` | 改工具的标题、输出与元数据 |
  | `shell.env` | 改 shell 工具看到的环境变量 |
  | `tool` | **定义全新工具** |
  | `auth` / `provider` | 挂自定义鉴权方式与 provider |
  | `experimental.chat.messages.transform` | 重写整条消息历史 |
  | `experimental.chat.system.transform` | 重写系统提示词 |
  | `session.compacting` | 介入上下文压缩 |
  | `event` | 订阅通用事件流 |

- **无头服务端与 Web 界面。** `opencode serve` 起一个无头 HTTP 服务，`opencode web`
  连带开 Web 界面，`opencode attach <url>` 接上一个跑着的实例。
- **ACP（Agent Client Protocol）服务端**：`opencode acp`，供编辑器一类客户端接入。
- **会话导入导出**：`opencode export <会话>` / `opencode import <文件或 URL>`，
  会话可以整场搬走。
- **用量统计**：`opencode stats`。
- **`--pure`**：完全不加载外部插件跑一次。
- **GitHub agent** 与 `opencode pr <编号>`：拉下 PR 分支直接进会话。

### 只有 Claude Code 有

- **模型分三档**：主模型 / 中档（sonnet）/ 快模型（haiku），三档各自可配。
  codex 只有 `model` 一个主槽位（外加 `codex review` 专用的 `review_model`），
  opencode 是两档（`model` + `small_model`）。
- **`Notification` 钩子事件**（另两家没有）。
- **`--bare` 极简模式**：一次性跳过钩子、LSP、插件同步、自动记忆、`CLAUDE.md` 自动发现。
  排查「是不是某个扩展把事情搞坏了」时非常有用。
- **后台 agent**：`--bg` 起一场后台会话立即返回，之后用 `claude agents` 管。
- **`--output-format stream-json`**：把非交互执行变成一条结构化事件流，是三家里最适合
  被程序逐事件消费的输出形态。
- **企业网关**：`claude gateway`（鉴权与遥测）。
- **云端多 agent 评审**：`claude ultrareview`。
- **技能（Skills）与插件生态**：`claude plugin`，`/skill-doctor`、`plugin eval` 等配套。
  （codex 也有技能与插件，但生态与工具链成熟度不同。）

---

## 用法差异：同一件事，三种写法

### 1. 无人值守跑一轮

```bash
claude -p "把测试跑一遍并报告失败项" --dangerously-skip-permissions
codex exec "把测试跑一遍并报告失败项" --dangerously-bypass-approvals-and-sandbox
opencode run "把测试跑一遍并报告失败项"
```

要点：
- Claude Code 的 `-p` 天然跳过一次性的**目录信任**菜单；交互式 TUI 不跳，所以用 tmux
  驱动它时必须先把信任写进 `~/.claude.json` 的 `projects[<路径>].hasTrustDialogAccepted`。
- codex 同理有目录信任门，记录在 `config.toml` 的 `[projects."<路径>"] trust_level`，
  且**只认落盘的配置**——实测用 `-c` 在命令行上覆盖这一项无效。
- opencode 没有等价的启动开关，权限放行只能经会话级配置声明
  （`OPENCODE_CONFIG_CONTENT` 里的 `permission`），否则无人值守时第一次写文件就卡住。

### 2. 指定 endpoint 与 model

三家的机制**互不通用**，这是接第三方模型时最容易踩的地方。

| | Claude Code | codex | opencode |
|---|---|---|---|
| 主通道 | 环境变量 `ANTHROPIC_BASE_URL` / `ANTHROPIC_MODEL` / `ANTHROPIC_API_KEY` | `~/.codex/config.toml` 的 `[model_providers.<名>]`，或启动时 `-c` 覆盖 | `opencode.json`，或环境变量 `OPENCODE_CONFIG_CONTENT` 塞一整份 JSON 配置 |
| 线协议 | Anthropic Messages | **只剩 `responses`**（`chat` 在 0.147 被移除） | 由 provider 的 npm 包决定（`@ai-sdk/*`） |
| 密钥怎么给 | 环境变量 | `env_key` 指一个环境变量名，或 `experimental_bearer_token` 明文写进配置 | 配置里的 `apiKey`，或 `opencode providers` 存的凭据 |
| 端点补全约定 | 自己补 `/v1/messages`，所以存的地址**不带**版本段 | 完整 base_url，按 OpenAI 惯例 | `@ai-sdk/anthropic` 只补 `/messages`，所以地址**要带** `/v1` |

**同一家厂商，给三个内核的地址往往不是同一个 URL。** 例如 DeepSeek：
Claude Code 走 `https://api.deepseek.com/anthropic`，codex 走 `https://api.deepseek.com/`。
两者之间没有可靠的推导规则（DeepSeek 是砍掉 `/anthropic`，OpenRouter 是补上 `/v1`），
所以「一份 profile 喂三家」这件事必须为每家单独存一个地址，NEVER 靠字符串变换。

### 3. 权限与审批

| | Claude Code | codex | opencode |
|---|---|---|---|
| 模型 | 权限模式：`default` / `acceptEdits` / `plan` / `dontAsk` / `bypassPermissions` | 沙箱档位 × 审批策略，两个正交维度 | **三家里最细**：`{动作, 资源, 结果}` 规则表，动作有 `read` / `edit` / `bash` / `webfetch` / `websearch` / `grep` / `glob` / `external_directory` / `question` / `plan_enter` 等，资源是 glob，结果是 `allow` / `ask` / `deny`；可按 agent 分别配 |
| 全放行开关 | `--dangerously-skip-permissions` | `--dangerously-bypass-approvals-and-sandbox` | 无开关，只能写配置 |
| 细粒度 | `--allowedTools "Bash(git *) Edit"` | `matcher` 正则 + `PermissionRequest` 钩子 | `permission.ask` 插件钩子 |
| 是否真沙箱 | 否 | **是**（seatbelt / landlock） | 否 |

### 4. 钩子写法：命令 vs 进程内

**Claude Code 与 codex：外部命令 + JSON 管道。**

```jsonc
// Claude Code: ~/.claude/settings.json 的 hooks 段
// codex:       ~/.codex/hooks.json（也接受 config.toml 里的内联 [hooks] 表）
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "Bash",
        "hooks": [{ "type": "command", "command": "/路径/我的钩子", "timeout": 20 }] }
    ]
  }
}
```

钩子进程从 stdin 读一个 JSON 对象，往 stdout 写一个 JSON 对象。语言随意、进程隔离，
但**能做的事只有事件契约里定义的那几样**。

**opencode：进程内 JS 模块。**

```js
export const MyPlugin = async ({ client, $ }) => ({
  "tool.execute.before": async (input, output) => { output.args.cmd = "…" },
  "permission.ask":      async (input, output) => { output.status = "deny" },
})
```

能改的东西多得多（见上），代价是必须写 JS、跑在 opencode 进程里，一个抛异常的插件会
影响宿主。

**一个实打实的能力缺口。** Claude Code 与 codex 的 `PreToolUse` 可以在工具**跑之前**把
一段上下文送到模型面前，也可以直接拒掉这次调用；opencode 的 `tool.execute.before`
只能改参数。frago 的桥接插件因此做了两件绕行：注入的上下文攒着，在
`tool.execute.after` 里拼进同一次调用的结果（模型仍看得到，只是晚一步）；要拒的命令
则被**改写成**一条打印拒绝原因并以非零码退出的命令，让原命令根本没机会跑。
`permission.ask` 那条路只在权限真被询问时才触发，而无人值守场景通常已把权限预先放行，
所以它接不住这一档。

---

## 会话记录：存在哪、什么形态

| | 位置 | 形态 | 能不能事后追加读 |
|---|---|---|---|
| Claude Code | `~/.claude/projects/<路径编码>/<uuid>.jsonl` | 一行一条，只追加 | 能（字节偏移增量读） |
| codex | `~/.codex/sessions/<年>/<月>/<日>/rollout-<本地时刻>-<uuid>.jsonl` | 一行一条，只追加 | 能（同上） |
| opencode | `~/.local/share/opencode/opencode.db`（SQLite） | 关系表 `session` / `message` / `part` | 能，但没有「文件 + 偏移」这回事，要按片段游标取 |

三家的会话编号形状：Claude Code 是 UUID，codex 是 **UUIDv7（同样是 UUID 形状）**，
opencode 带 `ses_` 前缀。**前两家的编号空间天生重叠**——想从一个编号反推它属于哪家，
光看形状不够，必须落盘查一眼。

判「这一轮答完没有」的权威信号：

- Claude Code：transcript 里那条带终结 `stop_reason` 的记录
- codex：rollout 里的 `task_complete` 事件（带 `turn_id`、`last_agent_message`，
  失败时还带 `error`）
- opencode：会话库里带完成时刻、且结束标记不是 `tool-calls` 的助手消息

三家都**不要靠读屏判完成**。读屏在多工具轮的空窗帧会误判，而这三个信号都是结构化的。

---

## frago 对三家的支持现状

| 能力 | Claude Code | codex | opencode |
|---|---|---|---|
| 钩子路由（知识注入 + 规则） | ✅ 原生命令钩子 | ✅ 原生命令钩子，同一个二进制 | ✅ 经 JS 桥接插件 |
| `frago agent` 驱动 | ✅ | ✅ | ✅ |
| 会话工作台列表 / 记录 / 搜索 | ✅ | ✅ | ✅ |
| 会话归档备份 | ✅ | ✅ | ✅ |
| 工作台中栏发消息 | ✅ | ❌ 通道背后恒是 claude | ❌ 同左 |
| `--use-profile` 指定模型（只管这一次会话） | ✅ | ❌ 见下 | ✅ |
| 激活 profile（写进它自己的常驻配置，人手起的会话也跟着走） | ✅ | ❌ 同一个原因 | ✅ |

两处已知缺口，都已记进待办：

1. **工作台只能给 Claude Code 会话发消息**（`20260820-webui-composer-send-to-all`）。
   发送端点写死在 claude 那条通道上，另外两家的会话编号在 claude 的档案里不存在，
   发过去会凭空开一场新会话，所以输入区对它们整个禁用。
2. **模型与端点指定没有覆盖三家**（`20260820-per-harness-endpoint-and-model`）。
   `frago agent` 的 `--model` / `--endpoint` / `--api-key` / `--use-ccr` 无条件写
   `ANTHROPIC_*`，codex 一个都不读；`--use-profile` 在 codex 上会明确报「本轮不生效」，
   另外三个开关目前仍是静默失效。

关于「激活」这件事本身，有一点值得单说：**激活是有范围的，且范围由你选**。以前
激活只写 Claude Code，界面上不说，于是另外两家继续跑着它们自己配置的模型，而人以为
自己换了模型。现在按「激活」会先问一句写到哪几家，能写的都列出来，写不了的（codex）
也列出来但禁用，并把原因摆在旁边。取消勾选某一家等于把那一家还原成 frago 接管前的
样子——opencode 的模型选择会被抄回接管前的那个，而不是留下一个空配置。

还有一处是能力本身的边界而非 frago 的缺陷：**frago 的 `PreToolUse` 规则里认
`Edit` / `Write` 或文件路径的那批，在 codex 上不触发**。codex 改文件走 `apply_patch`，
载荷里没有 `file_path` 字段。认 shell 命令的那批（内置规则里的大多数）完全正常。

---

## 怎么选

- **要最厚的生态、最成熟的工具链、模型分三档** → Claude Code。
- **要真沙箱、要一份配置管住 CLI 与两个 IDE 端、或者本来就在 ChatGPT 体系里** → codex。
- **要把 agent 当组件嵌进自己的程序（无头服务端 / ACP / Web）、或者需要深度改写提示词、
  参数、工具行为** → opencode。

在 frago 里三家是可以混用的：会话工作台把三家的会话合并成一份清单，钩子规则写一份、
三家共用（vocabulary 差异由各自的桥接层消化）。默认内核在
`~/.frago/config.json` 的 `agent_core`，单次覆盖用 `frago agent --agent-type <内核>`。

---

## 相关文档

- [概念](concepts.zh-CN.md) — frago 的四支柱与会话记录模型
- [用户指南](user-guide.zh-CN.md) — 日常命令
- [开发者文档](developer.zh-CN.md) — driver 契约与扩展方式
