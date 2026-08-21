# schedule-tasks

分类: 替代（MUST）

## 解决什么问题

定时任务最危险的失败不是报错，是**无声**：它没跑，而你以为它跑了。数据停在三天前，
页面还好好地显示着，没有任何一处会主动告诉你。这一章讲怎么让定时任务跑起来，
以及怎么让它在没跑的时候能被发现。

## 三种任务形态，选一种

```bash
frago schedule add <配方名> --cron "0 9 * * *"          # 配方   → frago 直接执行
frago schedule add --command "df -h /" --every 6h       # 命令   → frago 直接执行
frago schedule add --prompt "汇总昨天的飞书消息" --cron "0 8 * * *"   # 自然语言 → 交给 PA
```

三者只能给一个。**配方和命令由 frago 自己执行，不经过任何 agent**；
只有自然语言任务才交给 PA——那一种本来就需要理解和判断。

分家的理由是一次真实故障：2026-04 到 2026-08 之间所有定时任务都要过 PA，
于是一台 agent 会话起不来的机器上，配方型任务到点只在日志里留一行警告，
然后什么都不发生。机械任务的执行不该绑在一个 agent 能不能启动上。

方向也因此反过来：**PA 不再是定时任务的必经之路，而是它的调用方之一**——
agent 可以自己敲 `frago schedule add` 给自己或给系统排活。

## 通知回路：写文件不算通知

`--notify-on` 决定什么时候说话，`--notify-to` 决定说给谁听。**两者缺一不可**：
`--notify-on` 不是 `never` 时不给 `--notify-to`，命令直接拒绝，因为通知无处可去。

```bash
frago schedule add github_star_watch --cron "0 9,21 * * *" \
  --params '{"action":"update","no_open":true}' \
  --notify-on change --notify-to feishu --notify-context '{"chat_id":"oc_xxx"}'
```

落点三选一：

| `--notify-to` | 推到哪 | 什么时候用 |
|---|---|---|
| 已配置的 channel 名 | 复用该 channel 的 notify recipe（飞书回话走的就是这条路） | 默认首选，人本来就在那儿看 |
| `desktop` | 本机系统通知 | 个人机器、没配 channel 时 |
| `pa` | 投给常驻 agent 读 | 想让 agent 接着做点什么时 |

`frago channel list` 看有哪些 channel。**服务器上通常一个都没有**——那种机器上
`desktop` 也无意义（没人看着屏幕）。所以部署到服务器前先想清楚通知推去哪，
否则等于没有通知回路。

## 什么时候说话：四条规矩

**一、默认 `change`——有新鲜事才说。** 一个每天两次、每次都说「没有变化」的任务，
会在两周内把人训练成无视它。沉默必须有意义，收到消息这件事本身才有信息量。

**二、什么算「有变化」由任务自己定。** 调度器不可能知道某个任务的「变化」是什么，
任务永远知道。所以约定：

> **配方在结果 JSON 里给一个 `notify` 字段，那句话就是这次要说的；没有这个字段，
> 就是没什么可说的。**

```python
out = {"success": True, "new_count": len(records), ...}
if records:                      # 有新鲜事才给 notify
    out["notify"] = f"新增 {len(records)} 位：{names}（累计 {total}）"
return out
```

`summary` / `notify_text` 同样认。命令型没法这样自报，所以比对输出指纹——
算指纹前会先摘掉时间戳一类每次都变的字段，否则「有没有变化」永远是「有」。

**三、失败一定说话，但会收敛。** 失败时任务根本没跑完，没机会报 `notify`，
这时沉默等于把故障藏起来。所以失败无视 `--notify-on change`，照样推送；
但连续失败只在第 1、2、5、10、20、50、100 次说话，中间不刷屏。
**恢复正常时会再说一声**——不报恢复，人就永远不知道什么时候可以停止担心。

**四、没跑本身也是事件。** 超过三个周期没有成功运行，调度器主动推一条。
这条专门对付开头说的那种无声失败，而且这条通知能发出去本身就证明调度器活着，
一下子把排查范围缩小到「是这个任务的问题」。

## 手动触发

```bash
frago schedule run <id>
```

命令型和配方型直接在命令行跑完，当场打印状态、耗时、以及**为什么通知了或没通知**。
自然语言型跑不了——PA 的队列在服务端进程里，命令行进程碰不到，这一条会明确报错
而不是假装成功。

## 看状态

```bash
frago schedule list                  # 带 Kind 和 Notify 两列
frago schedule history <id>          # 每轮的状态、耗时、有没有通知
frago schedule toggle <id>           # 停用/启用
```

## 不要做

- 不要用 `frago recipe schedule`（`--interval` 那个）当常驻定时。它跑在前台，
  关掉终端就没了。要常驻用 `frago schedule`。
- 不要给一个需要判断的任务写成 `--command`。要判断就用 `--prompt` 交给 PA，
  别在 shell 里拼 if。
- 不要给纯机械的任务写成 `--prompt`。让 agent 去「读懂一句话然后执行配方」，
  多出来的全是失败面。
- 不要把通知配成 `always` 然后指望自己会看。会变成噪音，然后你会关掉它。
- 不要在配方里无条件返回 `notify` 字段。那等于把 `change` 退化成 `always`。
