# agent-worker-driving

主控会话要落地子任务时，用 `frago agent` 驱动 worker。它替你处理会话拉起、权限跳过、答案提取、空闲检测，NEVER 手搓 `tmux new-session` + `claude`。

## 为什么禁止手搓 tmux + claude

手搓路径下 worker 以普通权限模式启动（即使加 `--permission-mode acceptEdits`，Bash 命令照样弹确认框），任务会卡死在权限提示上。此时主控用 `tmux send-keys` 代替真人按确认键，会被 Claude Code 平台的 auto-mode 分类器硬拦截（Auto-Mode Bypass / Create Unsafe Agents）——无论加多少"先抓屏验证提示内容再按"的防护都过不去，这是平台层的硬边界。

`frago agent` 从根上消除这个问题：worker 以 `--dangerously-skip-permissions` 启动，全程不弹权限提示，主控没有任何需要代批的时刻。

## 一轮任务

```bash
{{frago_launcher}} agent "<prompt>"                        # 起 tmux 会话跑完一轮，打印答案
{{frago_launcher}} agent --prompt-file <任务书.md>         # 任务书走文件，长 prompt 首选
{{frago_launcher}} agent "<prompt>" --json                 # 机器可读摘要，调用方判读用这个
{{frago_launcher}} agent "<prompt>" --model sonnet         # 指定模型
{{frago_launcher}} agent "<prompt>" --agent-type opencode  # 换 cli-agent
{{frago_launcher}} agent "<prompt>" --resume <uuid>        # 续接既有会话
```

只有一个后端：**恒起一个 tmux 会话，在里面跑指定的 cli-agent**。没有 headless 形态，没有 `--driver` 可选。

`--yes` / `-y` 已废弃，收到即忽略（历史调用方带着它不会报错）。NEVER 在新代码里写它——它当年只用来应答 claude -p 那道确认闸，那条路已经不存在。同样已退场：`--driver`、`--ask`、`--passthrough`。

`--json` 的输出：
```json
{"status": "ok", "exit_code": 0, "session_id": "...", "tmux_name": "frago-agent-...", "text": "<答案原文>", "duration_ms": 6781}
```

## 派完活怎么收到通知（MUST）

`frago agent` 是阻塞的：它跑完 tmux 里那一轮才退出。主控 MUST 用 harness 自带的**后台执行**起它（Claude Code 的 Bash 工具 `run_in_background: true`），而不是前台干等——前台等于把主控会话钉死在一个 worker 上。

后台起之后不需要任何轮询、不需要兜底定时器：harness 托管着这个进程，它退出的瞬间就会重新唤起你，形态与 Agent 工具"启动即返回句柄、完成时收到通知"完全一致。

```bash
# 主控：Bash 工具带 run_in_background: true
{{frago_launcher}} agent --prompt-file <任务书.md> --timeout 1800
```

NEVER 用 `nohup` / `&` 手动脱离。那样起的进程被摘出 harness 的进程树，harness 不知道它存在，**退出时永远不会唤醒你**——这条路必然停摆，只能靠定时器猜时间回来看一眼。这不是没做好，是原理上就通知不了。

一轮任务写成任务书文件经 `--prompt-file` 传，比命令行拼长 prompt 更稳（不受引号与换行折磨），也便于你自己复查派了什么。

## worker 停在哪：退出码

| exit code | 状态 | 含义 |
|---|---|---|
| 0 | ok | 本轮答完，答案在 stdout |
| 1 | timeout | 超时未答完，会话仍活，可 `send` 续 |
| 2 | needs_input | 撞上认证墙 / 权限门 / 澄清菜单，**MUST 交真人** |
| 3 | error | driver 或 tmux 层失败 |

## 常驻会话（多轮交互）

```bash
{{frago_launcher}} agent start claude --name mywork    # 起会话，等 TUI ready 后返回会话名
{{frago_launcher}} agent send mywork "<prompt>"        # 投喂一轮，阻塞到回答产出并打印提取的答案
{{frago_launcher}} agent peek mywork                   # 抓当前 pane 画面（不打扰会话）
{{frago_launcher}} agent ls                            # 列出活会话（name / agent_type / pid / alive）
{{frago_launcher}} agent stop mywork                   # 杀会话并清理 sidecar
```

agent_type 支持 claude / codex / opencode，各自有 driver 处理 ready 信号、完成检测、答案提取。

## 角色标识

`frago agent` 的全部拉起路径都会给 worker 注入 `FRAGO_AGENT_ROLE=worker`。worker 读到该变量即知自己是执行者，在会话内直接完成任务，NEVER 再拉起新的 agent 会话（否则角色无限递归）。

## worker 需要人工输入时

driver 能识别 worker 停在认证墙 / 澄清问题上（`send` 会提示 "Agent needs input"）。此时把阻塞点报告给用户，由真人 `tmux attach` 处理，NEVER 尝试代替用户输入决策。

## 产出交付

```bash
{{frago_launcher}} agent attach --files '["<abs_path>", ...]'    # 把产出文件注册到当前 conv 的 outbox
```
