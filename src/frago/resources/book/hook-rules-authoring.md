# hook-rules-authoring

分类: 偏好（BETTER）

frago-core 的路由规则数据化在 `~/.frago/hook-rules.json`。当你观察到"一类事件应该触发一类知识注入"的重复模式时，MUST 用 `frago hook-rules add` 沉淀为规则——不要改 Rust，不要靠提醒用户。

## 何时该写规则

写规则的触发信号：
- 本 session 内同一种事件/prompt 反复出现，每次都要手动去查相同的 def 领域或 book 条目
- 观察到用户话术或工具调用里存在可规律化的 pattern（关键词、命令子串、路径特征）
- 当前 match 枚举能表达这个 pattern（`*_contains` / `*_contains_all` / `*_regex`）

不该写规则的情况：
- 只出现一次的巧合
- 需要复杂条件组合（需先讨论是否扩 match 类型而非硬套）
- 内容是一次性信息（该走 def 记忆而非 hook 注入）

## 核心命令

```bash
frago hook-rules list [--source=builtin|userdir|agent] [--event=<name>] [--show-disabled]
frago hook-rules show <rule_id>
frago hook-rules add --rule='<JSON>'               # 默认 source=agent + ttl_days=30
frago hook-rules disable <rule_id>
frago hook-rules enable <rule_id>
frago hook-rules remove <rule_id>
frago hook-rules validate
```

## 规则 JSON 结构

```json
{
  "id": "agent-<短描述>",
  "event": "UserPromptSubmit | PreToolUse | SessionStart | SessionEnd | ...",
  "match": { "type": "<match_type>", ... },
  "action": { "type": "<action_type>", ... },
  "dedup_scope": "session",
  "priority": 100,
  "description": "why + how to apply"
}
```

`source`、`created_at`、`ttl_days` 由 CLI 自动补；`agent` 源默认 30 天 TTL。

## match 类型速查

| type | 适用事件 | 字段 | 说明 |
|---|---|---|---|
| `always` | 任意 | — | 无条件命中（SessionStart 常用）|
| `tool_name_eq` | PreToolUse | value | 精确匹配工具名 |
| `bash_contains` | PreToolUse Bash | value | 子串 |
| `bash_contains_all` | PreToolUse Bash | values | AND 多子串，顺序无关 |
| `bash_regex` | PreToolUse Bash | pattern | 命令的**形状**（子串只能判断有哪些词）|
| `path_contains` | PreToolUse 带 file_path 的工具 | value, tools? | `tools` 限定工具，可区分读/写 |
| `path_contains_all` | 同上 | values, tools? | AND |
| `path_regex` | 同上 | pattern, tools? | Rust 正则（无 lookaround）|
| `tool_input_contains` | PreToolUse | key, value, tools? | 看进**工具参数**里某个字段，见下 |
| `tool_input_regex` | PreToolUse | key, pattern, tools? | 同上，正则；要精确一个值就加 `^…$` |
| `prompt_contains` | UserPromptSubmit | value | prompt 子串 |
| `prompt_regex` | UserPromptSubmit | pattern | prompt 正则 |
| `env_exists` | 任意 | name | 环境变量存在性 |
| `env_ne` | 任意 | name, value | 变量不存在或不等于该值时命中（"只在非 worker 会话"）|
| `all_of` / `any_of` / `not` | 任意 | clauses / clause | 组合与取反，可嵌套 |

`tool_input_*` 是唯一能看见工具参数的匹配。命令类只看 `command`、路径类只看 `file_path`，其余参数一律不可见——所以"调的是哪一个 skill / 哪一个 MCP 工具的哪个字段"过去表达不出来，只能连坐整个工具。字段不是字符串时按其紧凑 JSON 形态比对；字段缺失一律不命中。字段名在工具之间并不唯一（`command` 就不止一家），意图指向某个工具时 MUST 带 `tools`。

## action 类型速查

| type | 字段 | 行为 |
|---|---|---|
| `inject_book_topic` | topic | 跑 `frago book <topic>`，stdout 注入 context |
| `inject_book_section` | topic, section | 只注入一节，触发面比整页窄时用它省 token |
| `inject_literal` | text | 原文注入 |
| `run_command_and_inject_stdout` | command, timeout_ms? | command 前置 frago launcher，stdout 注入 |
| `deny_tool_call` | reason | **直接否决这次调用**（仅 PreToolUse），工具不执行，reason 作为拒绝理由回给 agent |
| `spawn_recipe_async` | recipe, params_from_event | 死变体，无 SessionEnd handler，仅为旧文件可解析而保留 |

`deny_tool_call` 是唯一有强制力的动作，其余都只是往上下文里加话、agent 可以读过去。它永不参与 dedup（同一会话每次命中都拦），且优先于所有注入。只用于损害落在会话之外、发起方自己收不回来的动作。

## 典型示例

**关键词路由到 def 领域：**
```bash
frago hook-rules add --source=agent --rule='{
  "id":"agent-video-tutorial",
  "event":"UserPromptSubmit",
  "match":{"type":"prompt_contains","value":"视频教程"},
  "action":{"type":"run_command_and_inject_stdout",
            "command":["frago-promotion","find","--","--name=bilibili-tutorial-video-methodology"]}
}'
```

**工具使用前挂专题提示：**
```bash
frago hook-rules add --rule='{
  "id":"agent-ffmpeg-safety",
  "event":"PreToolUse",
  "match":{"type":"bash_contains","value":"ffmpeg"},
  "action":{"type":"inject_book_topic","topic":"video-bgm"}
}'
```

**按参数拦住某个工具的某一种用法：**
```bash
frago hook-rules add --rule='{
  "id":"agent-ban-artifact-design",
  "event":"PreToolUse",
  "match":{"type":"all_of","clauses":[
    {"type":"tool_name_eq","value":"Skill"},
    {"type":"tool_input_regex","key":"skill","pattern":"^artifact-design$"}
  ]},
  "action":{"type":"deny_tool_call","reason":"这个 skill 已停用，理由：……"},
  "dedup_scope":"always"
}'
```
只拦这一个 skill，其余 skill 照常。`tool_name_eq` 单用会连坐整个工具——这是写这类规则最容易踩的坑。

## 原则

- 一条规则一件事，别塞多个场景进同一条
- id 用 `agent-<kebab-case>` 前缀，避免与 builtin 冲突
- 写 `description` 字段解释 why + how to apply，便于日后 distill 时判断是否保留
- agent 加的规则 30 天 TTL；真正长期有价值的规则等稳定后升级为 `source=userdir`（永不过期，规划中）
- 不要绕过 CLI 直接编辑 `~/.frago/hook-rules.json`，会绕过 seeding 和校验

## 下次召回入口

```bash
frago book hook-rules-authoring
```

系统会在你在 Bash 里运行任何 `frago hook-rules` 命令时自动注入本条。
