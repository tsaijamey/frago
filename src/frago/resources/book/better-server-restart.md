# better-server-restart

分类: 偏好（BETTER）

## 解决什么问题
agent 在需要刷新后端时倾向于直接 `{{frago_launcher}} server restart`，不检查是否有活跃任务。server 重启会杀掉所有 sub-agent 子进程，导致运行中的任务丢失、状态不一致。`--force` 更危险——跳过保护直接 kill。

## 执行前必须确认的问题

```
是否有任务正在运行？
├─ 有 → 不要 restart，等任务完成或向用户确认
├─ 没有 → 可以 restart
└─ 不确定 → 先 {{frago_launcher}} server status 检查
```

## 正确做法

```bash
# Step 1: 检查 server 状态和活跃任务
{{frago_launcher}} server status

# Step 2: 无活跃任务时重启
{{frago_launcher}} server restart

# Step 3: 有活跃任务时，向用户确认后才 --force
# NEVER 自行决定 --force
```

## server 进程管理的背景

frago server 通过 systemd user service 管理。`frago server restart` 检测 systemd 状态后委托 `systemctl --user restart`。不要直接操作 systemctl，不要 kill 进程，不要用 daemon.py 的内部方法。

## 不要做
- 不要在有活跃任务时直接 restart — 任务会丢失
- 不要自行使用 `--force` — 必须向用户确认
- 不要 `kill` 或 `pkill` server 进程 — 绕过了 graceful shutdown
- 不要代码改动后"习惯性重启" — 先确认是否真的需要重启（很多改动不需要）
