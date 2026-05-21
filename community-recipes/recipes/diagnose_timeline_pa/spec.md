# diagnose_timeline_pa

## Goal
给非开发的 frago 使用者用：在使用者本机按时间范围采集 timeline / PA (Primary Agent) 相关的运行数据，
打成一个模板化的诊断包（目录 + 同名 zip），回传给 frago 开发团队定位潜在 bug。

配方只负责「采集 + 结构化 + 轻量索引」三件事，不做深度分析（深度分析在开发端做）。
输入是一个时间窗口（绝对区间或相对时长）与脱敏开关；输出是一个自包含的诊断包，
含原始数据（窗口过滤后）、清洗后的运行时快照、以及两个跨机器格式一致的模板化文件
（manifest.json 机读、SUMMARY.md 人读）。

核心价值：使用者一条命令产出标准化诊断包，开发端拿到的每个包结构、字段、计数口径完全一致，
不需要使用者懂内部数据格式，也不会误传含 secret 的敏感文件。

## Type & Runtime
- type: atomic
- runtime: python

选 python：纯本地数据处理——多源 JSONL/日志按时间窗过滤、跨格式时间戳归一、文件拷贝与脱敏、
打包 zip、生成 manifest/SUMMARY。无浏览器、无网络，标准库即可（json / datetime / zipfile / shutil / platform / os）。

## Inputs
全部可选。窗口解析优先级：`since` > (`start`[, `end`]) > 默认 `since=2h`。

- `start` (string, optional) — 窗口起点，ISO 时间，如 `2026-05-21T07:00:00`。可带时区；不带则按系统本地时区处理。
- `end` (string, optional) — 窗口终点，ISO 时间。缺省 = 当前时刻（now）。
- `since` (string, optional) — 相对时长字符串，如 `2h` / `30m` / `90s` / `1d`。给了 `since` 则窗口 = `[now - since, now]`，并忽略 `start`/`end`。
- `redact` (boolean, optional, default=false) — 脱敏开关。开启后抹掉消息正文（只保留结构 / 状态 / 时间），用于使用者想分享脱敏包的场景。
- `output_dir` (string, optional, default=`~/.frago/.diagnostics`) — 输出根目录。

默认窗口：未给任何时间参数时取 `since=2h`，即 `[now - 2h, now]`。

## Outputs
stdout 打印单行 JSON：
```json
{"success": true, "bundle_dir": "...", "archive": "...", "counts": {...}}
```

- `success` (boolean) — 是否成功生成诊断包。
- `bundle_dir` (string) — 诊断包目录绝对路径，形如 `{output_dir}/dia-{YYYYMMDD-HHMMSS}/`。
- `archive` (string) — 同名 zip 绝对路径，形如 `{output_dir}/dia-{YYYYMMDD-HHMMSS}.zip`。
- `counts` (object) — 各数据类型计数（与 manifest 中计数同源），至少含 timeline / traces / server_log / agents 各项条目数。

output_targets: file, stdout

诊断包目录结构：
```
dia-{YYYYMMDD-HHMMSS}/
├── manifest.json          # 机读元数据（见下）
├── SUMMARY.md             # 人读诊断概要（模板化，见下）
├── timeline.jsonl         # 窗口内 timeline 事件
├── traces.jsonl           # 窗口内 traces 事件（多日合并）
├── server.log             # 窗口内 server 日志（含轮转、含 traceback 续行，旧→新）
├── sessions/<csid>/       # csid 精确关联的 executor/PA 会话（诊断主证据）
├── agents/                # 按 mtime 纳入的 agent 自由文本日志（弱补充；或 redact 时的清单）
└── runtime/               # 脱敏后的运行时快照
```

## 关键约束：时区对齐（务必正确，否则窗口过滤错乱）
不同数据源时间戳格式不一致，必须统一归一到「本地 aware 时间」再比较：
- timeline 的 `ts` 是带时区的 ISO，例如 `2026-05-21T10:19:40.902916+08:00`
- traces 的 `ts` 是裸本地时间（无时区），例如 `2026-05-21T11:59:43.378392`
- server.log 时间是裸本地时间 `[2026-05-20 19:45:07,759]`（注意毫秒用逗号分隔）

解析规则：
- 用 `datetime.fromisoformat` 解析时间戳；若解析结果为 naive（无 tzinfo），附上系统本地时区（`datetime.now().astimezone().tzinfo`）。
- 使用者传入的 `start` / `end` 与计算 `now` 同样按本地 aware 处理后再参与比较。
- server.log 时间需先把毫秒分隔的逗号换成点（`,759` → `.759`）再 `fromisoformat`。
- 窗口判定为闭区间 `[window_start, window_end]`。

NEVER 对任何源数据做 `[:N]` 截断：窗口内内容必须完整保留。

## 采集内容（全部按时间窗过滤后写入诊断包）
1. **timeline.jsonl** — 源：`~/.frago/timeline/timeline.jsonl`，逐行 JSON。保留 `ts` 落在窗口内的事件，原序输出。
   （不读 `.bak-*` 备份文件。）
2. **traces.jsonl** — 源：`~/.frago/traces/trace-*.jsonl`（多日文件合并）。每行有 `ts`（裸本地）、`data_type`、`subkind`、`task_id`、`msg_id`、`thread_id`、`event`。按窗口过滤，合并后按 `ts` 排序输出。
3. **server.log** — 源：`~/.frago/server.log` 及轮转 `server.log.1` / `.2` / `.3`。
   - 格式：`[YYYY-MM-DD HH:MM:SS,mmm] LEVEL logger: message`。
   - 多行 traceback 的续行没有时间戳，必须跟随其首行记录一起，按首行时间戳判定是否在窗口内。
   - 跨所有轮转文件合并后，按时间从旧到新输出。
4. **sessions/**（精确关联，诊断主证据）— 源：`~/.frago/sessions/claude/<csid>/`。
   - **关联链**（实测确立）：taskboard 的 `task_id`（ULID）→ 完整 timeline 中该 task 最后一条 `task_session_updated` 的 `data.csid`（claude session id, UUID）→ `~/.frago/sessions/claude/<csid>/`（含 `metadata.json` / `summary.json` / `steps.jsonl`，是 executor/PA 的结构化会话记录）。
   - **为什么不靠 agents 日志关联**：`logs/agent-{id8}.log` 的 id 是 `agent_service` 内部自生成的 uuid，与 timeline 的 `task_id` 是两套独立 id 空间，实测在 timeline/traces 中 0 命中，无法反查。csid 才是唯一能精确关联到 task 的桥。
   - 选取范围（取并集）：① 窗口内有活动的 task_id（含仅在窗口内 `task_recovery` 的）经「完整 timeline」反查到的 csid；② 窗口内 `task_session_updated` 直接出现的 csid；③ `config.json` 的 `primary_agent.session_id`（PA 自身会话）。
   - 体积：单个 task session 多为 KB 级；整个 sessions 库可达百 MB——**只采选中的 csid，绝不全采**。
   - 拷贝到 `sessions/<csid>/`：非 redact 全拷；redact 时只拷 `metadata.json` / `summary.json`（纯结构/计数，无正文），不拷 `steps.jsonl`。
   - 不读取 `~/.claude/projects/` 下的原始 Claude 会话（越界 + 隐私），只用 frago 自己的 `~/.frago/sessions`。
5. **agents/**（尽力补充，非主证据）— 源：`~/.frago/logs/` 下 `agent-*.log` / `agent-attached-*.txt` / `prompt-*.txt` / `console-*.txt`。
   - 文件内部无逐行时间戳且 id 无法与 task 关联，**仅按 mtime 落在窗口内**纳入（前缀匹配实测不命中，作弱条件保留）。已知局限：若某 task 在窗口内只是被 recovery、其 agent 日志写于更早时段，则采不到——精确证据走 sessions/ 那条链。
   - 纳入文件原样拷贝到 `agents/`（redact 行为见下）。
6. **runtime/** — 拷贝（脱敏后）以下文件：`runtime.json`、`config.json`、`schedules.json`、`feishu_poll_state.json`、`telemetry.json`、`.device_id`；并记录 `server.pid` 内容及该进程存活状态（`os.kill(pid, 0)` 探测）。

## 永不采集（安全红线，硬排除）
- `~/.frago/recipes.local.json`（含 secrets）
- `~/.frago/profiles.json`
- 任何 `.env`、`FRAGO_SECRETS`、以及含 `token` / `key` / `password` / `secret` 字样的字段
- `config.json` 拷贝前递归剔除「key 名（小写后）含 `secret` / `token` / `key` / `password` 的字段」，再写入 `runtime/`。

## redact 开启时的行为
- timeline / traces 中的正文类字段，其值替换为 `<redacted len=N>`（N 为原值字符串长度）。
  正文类字段名（在 `data` 及顶层中匹配）：`prompt`、`text`、`result_summary`、`summary`、`prompt_hint`、`reason`、`content`、`root_summary`。
- `agents/` 下的自由文本文件不拷贝正文，改为写一份清单 `agents/manifest.json`（每项：文件名 / 大小 bytes / mtime ISO）。

## 产出模板（两个文件跨机器格式必须一致）
**manifest.json**（机读）至少含：
- `tool_version`：采集工具（本配方）版本
- `generated_at`：生成时间（ISO，本地 aware）
- `params_raw`：原始输入参数
- `window`：解析后的窗口 `{start, end}`（ISO，本地 aware）
- `frago_version`：frago 版本
- `platform`：`{system, release, machine, python}`（取自 `platform` 模块）
- `hostname`、`device_id`（取自 `~/.frago/.device_id`）
- `server`：`{pid, alive}`
- `counts`：各项计数（与 stdout 的 counts 同源）

**SUMMARY.md**（人读，模板化，跨机器格式一致）含：
- 窗口与环境（窗口区间、平台、frago 版本、hostname、device_id、server 存活状态）
- 各 data_type 计数：
  - timeline 按 `data_type`
  - traces 按 `data_type` / `subkind`
  - server.log 总数 / ERROR 数 / WARNING 数
  - agents 文件数
- **生命周期扫描（诊断重点）**：基于完整 timeline 重建每个 msg / task 的最终状态，对「窗口内有活动」的对象：
  - 标出仍处于非终态的 msg（未到 `closed` / `dismissed`）与 task（未到 `completed` / `failed` / `resume_failed` / `replied`）
  - **失败任务**：列出窗口内活跃且最终态为 `failed` / `resume_failed` 的 task，附其 csid、窗口内 `task_recovery` 次数、对应 session 是否已采集——失败任务常引发恢复风暴，是诊断重点
  - 列出 boot/fold 次数（`startup_fold_completed` 的 `entries_read` / `entries_skipped`）
  - 列出 reflection tick 次数
- **server.log 信号聚合**（不止抽样）：
  - WARNING / ERROR 各做「模式聚合」——把消息里的 ULID / UUID / 数字归一为占位符后按出现次数排序，列 top N（每条带原文样例 + 计数）。重复刷屏的告警（如 `FAILED task <id> already recovered <n> times` ×164）必须以聚合形式直接出现在 SUMMARY，而不是只给一个总数让人去翻原始日志。

## Error Scenarios
- 源文件 / 目录缺失（其他使用者机器上可能没有某些文件）→ 跳过该项，计数置 0，不报错；其余继续采集。
- `since` 格式非法（不匹配 `\d+[smhd]`）→ exit 非 0，stderr 给出清晰错误。
- `start` / `end` 解析失败 → exit 非 0，stderr 指明哪个参数解析失败。
- `start` 晚于 `end` → exit 非 0，stderr 提示窗口区间非法。
- `output_dir` 不可写 → exit 非 0，stderr 提示。
- timeline / traces 某行非法 JSON → 跳过该行，计入 `parse_errors` 计数，不中断。
- server.pid 文件缺失或进程不存在 → `server.alive=false`，不报错。
- 整体目标：对所有源文件缺失 / 损坏要健壮，能产出尽量完整的诊断包，绝不因单个源失败而整体失败。

## Test Cases
1. 默认窗口：`frago recipe run diagnose_timeline_pa --params '{}'`
   → stdout `success=true`，`bundle_dir` 与 `archive` 路径存在，`counts` 含 timeline/traces/server_log/agents 各项；窗口 = 最近 2h。
2. 相对窗口 + 脱敏：`frago recipe run diagnose_timeline_pa --params '{"since":"30m","redact":true}'`
   → 包内 timeline.jsonl 正文字段为 `<redacted len=N>`；`agents/manifest.json` 存在且无正文文件。
3. 绝对窗口：`frago recipe run diagnose_timeline_pa --params '{"start":"2026-05-21T00:00:00","end":"2026-05-21T01:00:00"}'`
   → 仅含该 1 小时内事件；manifest `window` 与传入一致（归一为本地 aware）。
4. 安全红线：任意参数运行后，`bundle_dir` 内全树 grep `token`/`secret`/`password` 字段值 → 无命中；不含 `recipes.local.json` / `profiles.json`。
5. 健壮性：临时把 `~/.frago/traces` 改名后运行 → 仍 `success=true`，traces 计数为 0，其余项正常。

## 实现说明
- 时间戳归一是本配方最易错处：所有比较前都过 `normalize_to_local_aware(dt)`；naive → 附本地时区，aware → 原样。
- 生命周期重建用「完整 timeline」（不是窗口过滤后的），按 msg_id / task_id 折叠到最终状态，再用「窗口内是否出现该 id」判定是否纳入 SUMMARY 的非终态告警。
  - 终态参考（本机观测）：msg `closed`；task `replied` / `completed` / `failed`。中间态：msg `awaiting_decision` / `dispatched`；task `dispatched` / `executing`。
  - 实现时按「不在终态集合即视为非终态」判定，终态/非终态集合以代码侧实际 status 枚举为准，NEVER 硬编码假设的状态名（如 `queued`/`started`/`finished` 本机未观测到，需对照 codebase 校正）。
- traces 同时带 `data_type` 与 `subkind`，SUMMARY 的 traces 计数按二者交叉分组。
- agents/ 纳入用到的 task_id 前缀集合，从「窗口内 timeline + traces 的 task_id 前 8 位」取并集。
- zip 打包用 `zipfile`，归档根目录即 `dia-{stamp}/`，与目录内容一致。
- frago 版本可从 `~/.frago/config.json` 的 `resources_version` 或 `frago --version` 取，取不到则置 `null`，不报错。
