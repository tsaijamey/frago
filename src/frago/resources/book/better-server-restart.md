# better-server-restart

分类: 偏好（BETTER）

## 解决什么问题
agent 在需要刷新后端时倾向于直接 `frago server restart`，不检查 server 手里有没有正在跑的活。停机会连带终结这些活，任务半途丢失、状态不一致。`--force` 更危险——跳过保护直接 kill。

## 停机到底终结什么

**只终结 server 进程自己的后代。** 停机走的是「向 server 发 SIGTERM，再终结它 `children(recursive=True)` 里剩下的」。落在这个范围里的是：它正在执行的配方运行、它拉起的常驻监听（飞书消息流这类）、以及配方之间经总线互相调用时那些还没返回的跳转。

**`frago agent` 起的 worker 不在这个范围里。** worker 跑在 tmux 里，而 tmux 是独立守护进程、父进程是 1，与 server 没有父子关系。本机实测：33 个 tmux pane 与 server 的后代集合交集为 0，重启前后会话数 32 → 34，一个没死。

这一条以前写反过，说的是「重启会杀掉所有 sub-agent 子进程」——那是进程内 worker 年代的事实，tmux 驱动上来之后没跟着改。写反的代价不是多杀了谁，是让 agent 在该重启的时候不敢重启，明明可以立刻生效的改动被搁置，人还得亲自来确认一遍。

发起停机的那个进程和它的祖先另有保护，不会自杀——所以在 agent 任务里跑 restart 是安全的。

## 执行前必须确认的问题

```
server 手里有没有正在跑的活？
├─ 有 → 不要 restart，等它跑完或向用户确认
├─ 没有 → 可以 restart
└─ 不确定 → 先 frago server status 检查
```

注意问的是「server 手里的活」，不是「这台机器上有没有 agent 在忙」。tmux 里那些 worker 不受影响，不构成不重启的理由。

## 正确做法

```bash
# Step 1: 检查 server 状态和活跃任务
frago server status

# Step 2: 无活跃任务时重启
frago server restart

# Step 3: 有活跃任务时，向用户确认后才 --force
# NEVER 自行决定 --force
```

## server 进程管理的背景

server 运行时永远是系统级安装的 frago（uv tool install）。在 frago 源码仓库里执行 `uv run frago server start|restart` 时，会先自增补丁版本号、把当前代码打成 wheel 装到系统（`uv tool install --force`），再转交给系统 frago 完成启动——仓库 venv 里的 frago 从不作为 server 运行时。Linux 上 server 可由 systemd user service 管理，restart 检测 systemd 状态后委托 `systemctl --user restart`。不要直接操作 systemctl，不要 kill 进程，不要用 daemon.py 的内部方法。

## 不要做
- 不要在 server 手里有活时直接 restart — 那些活会丢失
- 不要拿「机器上有 agent 在忙」当不重启的理由 — tmux 里的 worker 不受停机影响，先按上面的范围确认再判断
- 不要自行使用 `--force` — 必须向用户确认
- 不要 `kill` 或 `pkill` server 进程 — 绕过了 graceful shutdown
- 不要代码改动后"习惯性重启" — 先确认是否真的需要重启（很多改动不需要）
