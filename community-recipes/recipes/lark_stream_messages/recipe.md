---
name: lark_stream_messages
type: atomic
runtime: python
version: "1.0.0"
description: "Subscribe to Lark bot message events via WebSocket long-connection (event-driven, non-polling). Whitelist is read from config.json."
use_cases:
  - "Event-driven real-time reception of Lark bot messages (long-connection mode)"
  - "Used as the source recipe of IngestionScheduler stream-mode channel"
tags:
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
    description: "Reply recipe name (injected by scheduler, not used by the recipe itself)"
outputs:
  messages:
    type: array
    description: "(Streaming output, not batched) Each message is written as a single-line JSON `{\"type\": \"message\", \"id\", \"prompt\", \"reply_context\"}` to stdout in real time; the process does not exit."
secrets:
  app_id:
    type: string
    required: true
    description: "Lark App ID"
  app_secret:
    type: string
    required: true
    description: "Lark App Secret"
dependencies: []
---

# lark_stream_messages

Subscribe to `im.message.receive_v1` events via Lark open platform WebSocket long-connection.

**This recipe does not exit**: once started it runs persistently; every accepted message is printed to stdout as a single JSON line, which `IngestionScheduler` stream-mode loop consumes line by line.

Whitelist path in `~/.frago/config.json`: `task_ingestion.whitelist.lark`.

Prerequisite: the Lark app's event subscription method must be set to "Long connection" (长连接) in the Lark developer console.

Unlike the Feishu counterpart, this recipe does **not** strip HTTP/HTTPS proxy env vars — `open.larksuite.com` is an overseas endpoint and typically requires the local proxy.

```bash
# Usually launched automatically by IngestionScheduler. For manual debugging:
frago recipe run lark_stream_messages
```
