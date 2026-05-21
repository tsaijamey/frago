---
name: diagnose_timeline_pa
type: atomic
runtime: python
version: "1.0"
description: "按时间窗采集本机 timeline / PA 运行数据，打成模板化诊断包（目录 + zip），含脱敏与安全红线过滤，供 frago 开发端定位 bug。"
use_cases:
  - "非开发使用者一条命令产出标准化诊断包回传开发团队"
  - "按相对时长或绝对区间圈定问题发生的时间窗，只采集窗口内运行数据"
  - "想分享诊断包又担心泄露正文/凭证时，开启 redact 产出脱敏包"
output_targets:
  - stdout
  - file
tags:
  - diagnostics
  - timeline
  - primary-agent
inputs:
  start:
    type: string
    required: false
    description: "窗口起点 ISO 时间（可带时区，不带按本地时区）。被 since 覆盖。"
  end:
    type: string
    required: false
    description: "窗口终点 ISO 时间，缺省=当前时刻。被 since 覆盖。"
  since:
    type: string
    required: false
    description: "相对时长 如 2h/30m/90s/1d；给定则窗口=[now-since, now] 并忽略 start/end。"
  redact:
    type: boolean
    required: false
    description: "脱敏开关，default=false。开启后抹掉正文字段、agents 只留清单。"
  output_dir:
    type: string
    required: false
    description: "输出根目录，default=~/.frago/.diagnostics。"
outputs:
  success:
    type: boolean
    description: "是否成功生成诊断包"
  bundle_dir:
    type: string
    description: "诊断包目录绝对路径 {output_dir}/dia-{YYYYMMDD-HHMMSS}/"
  archive:
    type: string
    description: "同名 zip 绝对路径"
  counts:
    type: object
    description: "各数据类型计数，至少含 timeline/traces/server_log/agents"
---

# diagnose_timeline_pa

## 功能描述
在使用者本机按时间范围采集 timeline / PA (Primary Agent) 相关运行数据，打成一个模板化诊断包（目录 + 同名 zip），回传给 frago 开发团队定位潜在 bug。配方只做「采集 + 结构化 + 轻量索引」，不做深度分析。

采集内容（全部按时间窗过滤后写入）：
- `timeline.jsonl` — `~/.frago/timeline/timeline.jsonl`（不读 `.bak-*`）
- `traces.jsonl` — `~/.frago/traces/trace-*.jsonl` 多日合并、按 ts 排序
- `server.log` — `~/.frago/server.log` 及轮转 `.1/.2/.3`，含 traceback 续行，旧→新
- `agents/` — `~/.frago/logs/` 下 agent 自由文本（mtime 在窗口内或 id 前缀命中窗口内 task_id）
- `runtime/` — 脱敏后的 `runtime.json` / `config.json` / `schedules.json` / `feishu_poll_state.json` / `telemetry.json` / `.device_id` 及 server 存活状态

产出两个跨机器格式一致的模板文件：`manifest.json`（机读）、`SUMMARY.md`（人读，含生命周期扫描诊断重点）。

## 使用方式
```
frago recipe run diagnose_timeline_pa --params '{}'
frago recipe run diagnose_timeline_pa --params '{"since":"30m","redact":true}'
frago recipe run diagnose_timeline_pa --params '{"start":"2026-05-21T00:00:00","end":"2026-05-21T01:00:00"}'
```
窗口解析优先级：`since` > (`start`[, `end`]) > 默认 `since=2h`。

## 前置条件
- 本机存在 `~/.frago` 运行目录（部分源文件缺失会被健壮跳过，不影响整体成功）。
- 无网络、无浏览器依赖，仅用 Python 标准库。

## 预期输出
stdout 单行 JSON：`{"success": true, "bundle_dir": "...", "archive": "...", "counts": {...}}`。
诊断包目录与同名 zip 落在 `output_dir` 下。

## 注意事项
- 安全红线（硬排除）：永不采集 `recipes.local.json` / `profiles.json`；runtime/ 内所有 JSON 递归剔除 key 名含 `secret`/`token`/`key`/`password` 的字段。
- 时区对齐：所有时间戳归一到本地 aware 时间后再做闭区间 `[start, end]` 过滤；server.log 毫秒逗号先转点。
- 绝不对窗口内源数据做 `[:N]` 截断；SUMMARY 中 ERROR 为人读抽样，完整日志在 server.log 内。
- 生命周期状态枚举对照 codebase（taskboard/models.py）：msg 终态 `{closed, dismissed}`，task 终态 `{completed, failed, resume_failed, replied}`。

## 更新历史
- 1.0 (2026-05-21): 初版，实现采集 + 结构化 + 模板化索引 + 脱敏 + 安全红线过滤。
