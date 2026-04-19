---
name: feishu_check_messages
type: atomic
runtime: python
version: "2.0.0"
description: "通过飞书 API 拉取机器人收到的最新消息，白名单从 config.json 读取"
use_cases:
  - "轮询检查飞书机器人收到的新消息"
  - "获取飞书群聊或私聊中 @机器人 的消息"
tags:
  - feishu
  - lark
  - bot
  - communication
  - ingestion
output_targets:
  - stdout
inputs:
  max_results:
    type: number
    required: false
    description: "最多返回几条消息，默认 5"
outputs:
  messages:
    type: array
    description: "消息列表。每条包含 id（= 消息 msg_id）、prompt（指令文本）、reply_context。reply_context 字段：chat_id / chat_name / message_id（= 最后一条消息 id，用于回复定位）/ parent_message_id（若引用回复了其它消息则指向被引用消息，否则为 null；frago Thread Classifier L1 据此跨时间续挂 thread）/ sender_id"
  count:
    type: number
    description: "消息数量"
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

# feishu_check_messages

通过飞书开放平台 API 拉取机器人收到的最新消息。

白名单统一配置在 `~/.frago/config.json` → `task_ingestion.whitelist.feishu`：
- `allowed_chats`: 群白名单，仅轮询这些群
- `allowed_senders`: 用户白名单，仅响应这些用户的消息（空数组=群内所有人）

每次 poll 自动更新 `.chat_and_sender_directory.json`，记录所见群和用户的 id 映射。

```bash
# 拉取消息（自动按白名单过滤）
frago recipe run feishu_check_messages
frago recipe run feishu_check_messages --params '{"max_results": 10}'
```
