---
name: feishu_send_message
type: atomic
runtime: python
version: "1.2.0"
description: "通过飞书 API 发送文本/图片消息或撤回已发送消息，用于 frago 向飞书用户/群回复执行结果"
use_cases:
  - "回复飞书用户的 frago 指令消息"
  - "向飞书群发送任务执行结果"
  - "发送本地图片到飞书群（自动上传获取 image_key + 发送图片消息）"
  - "发送本地文件到飞书群（自动上传获取 file_key + 发送文件消息）"
  - "撤回误发或需要删除的消息"
tags:
  - feishu
  - lark
  - bot
  - communication
  - ingestion
output_targets:
  - stdout
inputs:
  chat_id:
    type: string
    required: false
    description: "目标群聊 ID（直接调用时必填；ingestion 场景从 reply_context 提取）"
  text:
    type: string
    required: false
    description: "消息文本（直接调用时必填；ingestion 场景从 status/result_summary 格式化）"
  status:
    type: string
    required: false
    description: "任务状态（ingestion notify 契约字段）"
  result_summary:
    type: string
    required: false
    description: "任务结果摘要（ingestion notify 契约字段）"
  error:
    type: string
    required: false
    description: "错误信息（ingestion notify 契约字段）"
  reply_context:
    type: object
    required: false
    description: "回复上下文，含 chat_id/message_id（ingestion notify 契约字段）"
  action:
    type: string
    required: false
    description: "操作类型：send（默认，发送消息）| recall（撤回消息，需提供 message_id）"
  image_path:
    type: string
    required: false
    description: "本地图片路径，传入后自动上传飞书并发送图片消息（与 text 互斥）"
  file_path:
    type: string
    required: false
    description: "本地文件路径，传入后自动上传飞书并发送文件消息（优先级：file_path > image_path > text）"
  message_id:
    type: string
    required: false
    description: "要撤回的消息 ID（仅 action=recall 时使用）"
outputs:
  message_id:
    type: string
    description: "发送成功的消息 ID"
  image_key:
    type: string
    description: "图片上传后的 image_key（仅图片模式返回）"
  file_key:
    type: string
    description: "文件上传后的 file_key（仅文件模式返回）"
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

# feishu_send_message

通过飞书开放平台 API 发送文本或图片消息到群聊或用户。

凭证通过 `FRAGO_SECRETS` 环境变量注入，配置于 `~/.frago/recipes.local.json` 或 Web UI。

```bash
# 发送文本消息
frago recipe run feishu_send_message --params '{"chat_id": "oc_xxx", "text": "任务已完成"}'

# 发送图片消息（自动上传 + 发送）
frago recipe run feishu_send_message --params '{"chat_id": "oc_xxx", "image_path": "/path/to/image.png"}'

# 发送文件消息（自动上传 + 发送）
frago recipe run feishu_send_message --params '{"chat_id": "oc_xxx", "file_path": "/path/to/document.pdf"}'

# 撤回消息
frago recipe run feishu_send_message --params '{"action": "recall", "message_id": "om_xxx"}'
```
