---
name: feishu_broadcast_message
type: atomic
runtime: python
version: "1.0.0"
description: "向飞书机器人所在的允许群组广播消息，支持同步群列表和按编号管理允许群"
use_cases:
  - "向所有允许的飞书群广播通知"
  - "同步机器人所在群列表到配置文件"
  - "管理允许广播的群组"
tags:
  - feishu
  - lark
  - bot
  - broadcast
  - communication
output_targets:
  - stdout
inputs:
  action:
    type: string
    required: true
    description: "操作类型：sync（同步群列表）| broadcast（广播消息）| list（查看配置）"
  text:
    type: string
    required: false
    description: "广播消息文本（action=broadcast 时必填）"
outputs:
  chats:
    type: list
    description: "群列表（sync/list 时返回）"
  results:
    type: list
    description: "广播结果（broadcast 时返回）"
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

# feishu_broadcast_message

向飞书机器人所在的允许群组广播消息。

## 使用流程

### 1. 同步群列表

首次使用前，先同步机器人所在的所有群到配置文件：

```bash
frago recipe run feishu_broadcast_message --params '{"action": "sync"}'
```

生成的配置文件 `.broadcast_config.json` 位于配方目录，格式：

```json
{
  "chats": [
    {"index": 1, "chat_id": "oc_xxx", "name": "群名1"},
    {"index": 2, "chat_id": "oc_yyy", "name": "群名2"}
  ],
  "allowed_indexes": [1, 2]
}
```

### 2. 编辑允许的群

修改 `allowed_indexes` 数组，只保留需要广播的群编号。

### 3. 广播消息

```bash
frago recipe run feishu_broadcast_message --params '{"action": "broadcast", "text": "系统维护通知"}'
```

### 4. 查看当前配置

```bash
frago recipe run feishu_broadcast_message --params '{"action": "list"}'
```
