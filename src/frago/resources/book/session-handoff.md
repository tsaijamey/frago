# 交接：把这场会话剩下的事，写成下一场会话接得住的待办

## 什么时候写

- 会话到尾声，手上还有没做完、但这次不做的事；
- 半路冒出来、和本次目标无关的事（一次会话只打一个目标，其余记下来）；
- 上下文快满了，在这场会话里继续不划算，要换一场接着做；
- 天生周期性、会反复回来做的事（定期复盘、盯一个上游进展、跑一次巡检）。

判据只有一句：**这件事如果只留在这场对话里，下一场会话就等于没发生过。**

## 为什么写成待办，而不是指望下一个 agent 自己想起来

下一场会话可能是另一个 agent、另一个命令行工具、几周以后。它拿不到你的上下文，只
拿得到两样东西：`~/.frago/todo/` 下的这份文件，以及文件里记着的会话 id。前者说这件
事是什么、做到哪了；后者是回到原话的钥匙——细节、试过又放弃的路子、被否掉的方案都在
原始对话里，待办正文不必也不该复述。

## 一条待办要能回答四个问题

- **这是什么事** → `title`（英文，会被转成文件名和 id）加 `--summary`（中文一句话）
- **为什么有这件事、已经到哪一步、为什么停在这里** → `--context`
- **接手的人第一步做什么** → `--step`，可多条
- **怎么算做完** → `--done-when`，要可判定，不是「优化一下」

`title` 必须用英文：它会被 slugify 成文件名，中文标题只会变成拼音垃圾。中文写进
`--summary` 和 `--context`。

## 建一条

```bash
frago todo add "wind ai agent research" \
  --summary "调研上海万得在 AI agent 方向的近况" \
  --priority high --tag research \
  --context "这次只确认了 X；判断 Y 的依据是 Z。停在这里是因为拿不到 W。" \
  --step "先读 ~/.frago/data/wind/20260828-agent-scan/ 里已经抓到的三篇" \
  --done-when "能回答它们的 agent 产品会不会影响我们的取数路径"
```

会话 id 不用手写：`add` 自己解析当前会话记进去。解析不到时命令会在 stderr 说明原因，
按提示补 `--session <id>` 即可。单独查自己是谁：

```bash
frago session self          # 只打一行 id，可以直接 $(...) 取用
frago session self --json   # id、来源、原始记录文件路径
```

## 同一件事第二次、第三次接手

不要再 `add` 一条。找到原来那条，往上追加：

```bash
frago todo list --tag research     # 或 frago todo next
frago todo log <ref> "这次把 X 跑通了，卡在 Y：……。下一步先动 Z。" --status doing
```

`log` 只追加不覆盖：它在 `context` 末尾压一行日期和本场会话 id，再接上你这段话。一条
长周期的待办于是攒出一条时间线——接手的人一眼看到这件事被谈过几回、每回改了什么主意，
而不是只看到最后一手结论。

## 下一场会话怎么接住

```bash
frago todo list                 # 全部；--status doing 只看在做的
frago todo next                 # 最该做的那一件
frago todo show <ref>           # 完整 JSON，含 sessions 这条线索
```

拿到 `sessions` 里的 id 之后，回原话有两条路：

```bash
frago session show <id> --steps    # 归档过的会话；没有就先 frago session sync
frago session search "<一句话>"     # 记不清 id 时，按意思搜历史会话
```

## 别这么写

- 别把整场对话复述进 `context`。原话在会话记录里，`context` 只写背景、结论和判断依据。
- 别用中文 `title`。
- 别为同一件事开第二条待办；已有的那条 `log` 上去。
- 别写「优化性能」这种 `done_when`，写「导出一万行在三秒内完成」。
- 别只写「还没做完」。接手的人真正缺的是：为什么停、下一步先动哪里。

## 相邻的三个去处

- 结论性的知识（下次遇到同类问题直接能用的判断）→ `frago <domain> save`
- 产出物（报告、数据、截图）→ `~/.frago/data/<主体>/<YYYYMMDD>-<slug>/`
- 过程（原话）→ 会话记录，本文说的 `sessions` 就是它的入口

待办只装「还没做完的事」。
