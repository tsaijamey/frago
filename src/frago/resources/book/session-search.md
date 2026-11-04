# session-search

分类: 效率（AVAILABLE）

用户问"上次我们是怎么定的"、"之前那个报错后来怎么解决的"时，答案就在本机的原始会话记录里——但那不在你的上下文里，你确实不记得。

这时候 NEVER 回答"我不记得了"，也 NEVER 自己去 grep 原始会话库。用这条命令。

```bash
frago session search "<一句话说清你要找什么>"
```

`frago sessions search` 是同一条命令的别名，两种写法都认。

## 它做了什么

三步，两步是代码做的、一步是模型做的：

1. **模型把一句话摊成 8~14 个字面量关键词**——同义说法、中英两种写法、可能出现的命令名、文件名、报错原文。这一步代码做不好：从"调通扩展桥接那回"想到当时屏幕上会出现 `ws://`、`extension bridge`、`桥接`，是语义推理不是字符串处理。
2. **ripgrep 扫一遍 `~/.frago/sessions`**，claude、opencode、codex 三个核的会话都在这棵树下，一趟扫完。四五 GB 的量级两三秒。

结果按**命中了几个不同的关键词**排序，其次才是命中密度、最近活动。原因是会话记录一行是一整条记录，同一个词在一行里出现一百次不代表这场会话更相关，而同时命中五个不同的词几乎一定就是要找的那场。

## 为什么搜备份而不搜 Claude 自己的目录

`~/.claude/projects` 会随时间滚动删除旧会话，那里现存的只是历史的一小截——搜它等于宣布几个月前的事没发生过。`~/.frago/sessions` 是 frago 的备份，只增不减，30 秒一轮跟到最新，对还活着的会话与源文件逐字节相等。

备份里有两代格式，都搜：`raw.jsonl` 是原文逐字节副本，`steps.jsonl` 是早期的加工副本（工具返回值等内容已被摘掉）。老会话往往只剩后者，而它们的原文已随 Claude 的滚删永久消失。这类会话在结果里标"只剩早期加工副本"——**在那儿搜不到 NEVER 等于那件事没发生过**，换个说法或改搜当时的用户提问再试。

## 常用参数

```bash
frago session search "<一句话>" --days 30      # 只搜最近 N 天（按记录里的时间，不看文件 mtime）
frago session search "<一句话>" --top 5        # 只要前 N 场
frago session search "<一句话>" --no-expand    # 跳过模型，按原句切词（快，但笨）
frago session search "<一句话>" --terms "a,b"  # 你自己给关键词，跳过模型
frago session search "<一句话>" --json         # 机器可读
```

模型扩展默认走 `frago-core --mode chat --as-role lightagent` 单轮无状态模式（几秒量级，不起子会话、不落新会话文件）。**已经知道该搜哪几个字面量时用 `--terms` 直接给**，省掉这一轮。心里没数、只有一句话时才让模型扩。

扩展那一轮失败、超时或输出格式不对时，命令自动退回按原句切词继续搜，并在输出里写明这次是退回来的——NEVER 因为扩展没跑成就整条命令失败。

## 提取会话内容：frago session ask

找到目标会话 id（或拿到现成的会话 id）后，**NEVER 直接 `Read` 那个 `raw.jsonl` 文件，也 NEVER 写 `uv run python` / `jq` / `cat` 切片硬读**——原始会话文件动辄数兆到数十兆，直接读会把大量原始工具输出塞进主会话上下文。

一律用 `frago session ask` 让轻量模型单轮读取并提炼你要的结论：

```bash
frago session ask <会话id或前8位> "<你要提取的具体问题或结论>"
frago session ask 32c0bb7a "提取最后一条结论记录并脱敏连接串" --tail 20
frago session ask a1d5f9f8 "第 450 至 520 条记录中引用的 32c0bb7a 历史结论是什么" --range 450:520
frago session ask 32c0bb7a "当时报错原因和最终修复命令是什么" --grep "error,fix"
```

- **位置参数**：第一个是 `<session_id>`（支持完整 UUID 或前 8 位唯一前缀），第二个是一句自然语言问句 `"<question>"`。
- **可选范围参数**：`--range <起:止>`（按 1-based 记录序号切片，问句里写「第 450 至 520 条」也会自动识别）、`--tail <N>`（只看末尾 N 条有效记录）、`--grep "<词1,词2>"`（按字面量筛记录并带前后 2 条上下文）。
- **底层机制**：代码层自动剥离 `<frago-employee>`、`<must-use-skill>` 与超长噪音并对连接串/密钥脱敏，再通过标准输入交给 `frago-core --mode chat --as-role lightagent` 单轮作答（不调 `frago agent`、不起 tmux、不落会话文件）。

## 读结果

每一场命中给出：来源（claude / opencode / codex / coreagent / agy）、会话 id、标题、命中了哪几个词、命中记录数、最后活动时刻、工作目录、原始文件路径、单轮提取命令模板，以及几段命中处的上下文。

还给一条可直接执行的续接命令（`claude --resume <id>`、`opencode -s <id>` 或 `codex resume <id>`）。要把整场会话接过来继续聊才用续接命令；**只提取某段结论、某次查询输出或某个决定依据，一律跑 `frago session ask <id> "<问句>"`**。

记录数带 `+` 号（如 `40+`）表示该会话触到了每文件的计数上限，实际命中只多不少——那是"数到这就不数了"，不是"总共就这些"。

最后活动时刻取自记录自己带的时间戳（claude 与 codex 是 `timestamp`，opencode 是 `time`），不是文件的修改时间——备份文件的 mtime 是"什么时候备的"，批量回填过的一整批都是同一个时刻，拿它当会话时间会全错。极少数只有元数据记录的空壳会话文件里根本没有时间，给了 `--days` 时它们被排除并在告警里报数。

那些已从 `~/.claude/projects` 滚删的归档会话，`claude --resume` 接不回去——直接用 `frago session ask <id> "<问句>"` 从备份库提取内容。

## 什么时候用

- 用户提到"上次""之前""那次"并指向一件具体的事
- 你需要一个过去做过的决定的依据，而当前上下文里没有
- 排查问题时想知道同样的现象以前出现过没有

不适用的：找**产出物**（报告、spec、数据文件）用 `frago context data:<关键词>`；找**已沉淀的结构化知识**用 `frago <域名> find`。这条命令翻的是原始对话过程本身。
