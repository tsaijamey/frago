---
name: lark_send_message
type: atomic
runtime: python
version: "1.0.0"
description: "Send text/image/file messages or recall sent messages via Lark Open API; used by frago to reply task execution results to Lark users/groups."
use_cases:
  - "Reply to a user's frago command message on Lark"
  - "Send task execution results to a Lark group"
  - "Send a local image to a Lark group (auto-upload image_key + send image message)"
  - "Send a local file to a Lark group (auto-upload file_key + send file message)"
  - "Recall a mistakenly sent or to-be-deleted message"
tags:
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
    description: "Target chat_id (required for direct invocation; ingestion path pulls from reply_context)"
  text:
    type: string
    required: false
    description: "Message text (required for direct invocation; ingestion path formats from status/result_summary)"
  status:
    type: string
    required: false
    description: "Task status (ingestion notify contract field)"
  result_summary:
    type: string
    required: false
    description: "Task result summary (ingestion notify contract field)"
  error:
    type: string
    required: false
    description: "Error message (ingestion notify contract field)"
  reply_context:
    type: object
    required: false
    description: "Reply context containing chat_id/message_id (ingestion notify contract field)"
  action:
    type: string
    required: false
    description: "Action type: send (default, send a message) | recall (recall a message; requires message_id)"
  image_path:
    type: string
    required: false
    description: "Local image path; auto-upload to Lark and send as image message (mutually exclusive with text)"
  file_path:
    type: string
    required: false
    description: "Local file path; auto-upload to Lark and send as file message (priority: file_path > image_path > text)"
  message_id:
    type: string
    required: false
    description: "Message ID to recall (used only when action=recall)"
outputs:
  message_id:
    type: string
    description: "Message ID of the sent message"
  image_key:
    type: string
    description: "image_key returned after image upload (image mode only)"
  file_key:
    type: string
    description: "file_key returned after file upload (file mode only)"
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

# lark_send_message

Send text, image, or file messages to a Lark chat or user via the Lark Open Platform API (overseas `open.larksuite.com` endpoint).

Credentials are injected via the `FRAGO_SECRETS` environment variable, configured in `~/.frago/recipes.local.json` or via the Web UI.

Unlike the Feishu counterpart, this recipe does **not** strip HTTP/HTTPS proxy env vars — `open.larksuite.com` is an overseas endpoint and typically requires the local proxy.

```bash
# Send a text message
frago recipe run lark_send_message --params '{"chat_id": "oc_xxx", "text": "Task completed"}'

# Send an image message (auto upload + send)
frago recipe run lark_send_message --params '{"chat_id": "oc_xxx", "image_path": "/path/to/image.png"}'

# Send a file message (auto upload + send)
frago recipe run lark_send_message --params '{"chat_id": "oc_xxx", "file_path": "/path/to/document.pdf"}'

# Recall a message
frago recipe run lark_send_message --params '{"action": "recall", "message_id": "om_xxx"}'
```
