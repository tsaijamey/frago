# agent-worker-driving

主控会话要落地子任务时，用 `frago agent` 驱动 worker。它替你处理会话拉起、权限跳过、答案提取、空闲检测，NEVER 手搓 `tmux new-session` + `claude`。

## 为什么禁止手搓 tmux + claude

手搓路径下 worker 以普通权限模式启动（即使加 `--permission-mode acceptEdits`，Bash 命令照样弹确认框），任务会卡死在权限提示上。此时主控用 `tmux send-keys` 代替真人按确认键，会被 Claude Code 平台的 auto-mode 分类器硬拦截（Auto-Mode Bypass / Create Unsafe Agents）——无论加多少"先抓屏验证提示内容再按"的防护都过不去，这是平台层的硬边界。

`frago agent` 从根上消除这个问题：worker 以 `--dangerously-skip-permissions` 启动，全程不弹权限提示，主控没有任何需要代批的时刻。

## 一轮任务（headless）

```bash
{{frago_launcher}} agent "<prompt>" --yes                     # claude -p 跑完一轮，stdout 流式输出
{{frago_launcher}} agent "<prompt>" --yes --driver tmux       # 同样一轮，但跑在常驻 tmux TUI 会话里
{{frago_launcher}} agent "<prompt>" --yes --model sonnet      # 指定模型
```

从 Bash 调用 MUST 带 `--yes`：无 TTY 环境下默认的 y/N 确认读不到输入会直接 Abort。

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
