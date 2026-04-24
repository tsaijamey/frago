---
name: feishu_stream_messages
type: atomic
runtime: python
version: "1.0.0"
description: "通过飞书 WebSocket 长连接订阅机器人消息事件（事件驱动，非轮询）。白名单从 config.json 读取。"
use_cases:
  - "事件驱动实时接收飞书机器人消息（长连接模式）"
  - "作为 IngestionScheduler 的 stream-mode channel 的 source recipe"
tags:
  - feishu
  - lark
  - bot
  - communication
  - ingestion
  - stream
output_targets:
  - stdout
inputs:
  notify_recipe:
    type: string
    required: false
    description: "回复 recipe 名（由 scheduler 注入，recipe 本身不用）"
outputs:
  messages:
    type: array
    description: "（流式输出，不是批量）每条消息实时以 `{\"type\": \"message\", \"id\", \"prompt\", \"reply_context\"}` JSON 单行写入 stdout，进程不退出。reply_context 字段与 feishu_check_messages 一致。"
secrets:
  app_id:
    type: string
    required: true
    description: "飞书应用 App ID"
  app_secret:
    type: string
    required: true
    description: "飞书应用 App Secret"
no_proxy: true
dependencies: []
---

# feishu_stream_messages

通过飞书开放平台 WebSocket 长连接订阅 `im.message.receive_v1` 事件。

**此 recipe 不退出**：启动后持久运行，每收到一条目标消息就在 stdout 打印一行 JSON，由 `IngestionScheduler` stream-mode loop 逐行消费。

白名单配置位置与轮询版相同：`~/.frago/config.json` → `task_ingestion.whitelist.feishu`。

前提：飞书应用后台事件订阅方式须选择「长连接」。

```bash
# 一般由 IngestionScheduler 自动拉起，手动调试：
frago recipe run feishu_stream_messages
```
