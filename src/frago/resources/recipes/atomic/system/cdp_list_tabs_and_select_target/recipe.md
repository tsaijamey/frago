---
name: cdp_list_tabs_and_select_target
type: atomic
runtime: python
description: "列出Chrome所有tabs并选择/锁定其中一个作为CDP操作目标"
use_cases:
  - "多tab环境下需要指定操作哪个页面"
  - "切换CDP连接到不同的tab"
  - "获取当前Chrome所有打开的页面信息"
tags:
  - cdp
  - tab-management
  - session
output_targets:
  - stdout
  - file
inputs:
  action:
    type: string
    required: false
    description: "操作类型: list(列出所有tabs) 或 select(选择并锁定tab)，默认list"
  index:
    type: number
    required: false
    description: "通过索引选择tab (action=select时)"
  title:
    type: string
    required: false
    description: "通过标题模糊匹配选择tab (action=select时)"
  url:
    type: string
    required: false
    description: "通过URL模糊匹配选择tab (action=select时)"
  id:
    type: string
    required: false
    description: "通过精确ID选择tab (action=select时)"
  host:
    type: string
    required: false
    description: "CDP主机地址，默认127.0.0.1"
  port:
    type: number
    required: false
    description: "CDP端口，默认9222"
  save_config:
    type: boolean
    required: false
    description: "是否保存选中的tab配置到 ~/.frago/current_target.json，默认true"
outputs:
  tabs:
    type: array
    description: "所有tab的信息列表 (action=list时)"
  selected_tab:
    type: object
    description: "选中的tab详情 (action=select时)"
  config_path:
    type: string
    description: "保存的配置文件路径 (action=select时)"
dependencies: []
version: "1.0.0"
---

# cdp_list_tabs_and_select_target

## 功能描述

这个配方解决了CDP自动化中的一个核心问题：当Chrome打开多个tab时，如何精确控制操作哪个页面。

默认情况下，frago会自动连接到第一个可用的page。但在复杂场景下（如同时打开多个网站进行数据采集），需要明确指定目标tab。

配方提供两种操作模式：
- **list**: 列出所有Chrome tabs的基本信息（index、标题、URL）
- **select**: 通过index/title/url/id选择并锁定一个tab

## 使用方法

**列出所有tabs**：
```bash
uv run frago recipe run cdp_list_tabs_and_select_target
# 或指定参数
uv run frago recipe run cdp_list_tabs_and_select_target \
  --params '{"action": "list"}'
```

**通过索引选择tab**：
```bash
uv run frago recipe run cdp_list_tabs_and_select_target \
  --params '{"action": "select", "index": 0}'
```

**通过标题模糊匹配选择**：
```bash
uv run frago recipe run cdp_list_tabs_and_select_target \
  --params '{"action": "select", "title": "GitHub"}'
```

**通过URL模糊匹配选择**：
```bash
uv run frago recipe run cdp_list_tabs_and_select_target \
  --params '{"action": "select", "url": "youtube.com"}'
```

**通过精确ID选择**：
```bash
uv run frago recipe run cdp_list_tabs_and_select_target \
  --params '{"action": "select", "id": "F7D7569E470E12306173702FCD3E2DE2"}'
```

## 前置条件

- Chrome以远程调试模式启动：`google-chrome --remote-debugging-port=9222`
- CDP端口可访问（默认9222）

## 预期输出

**list操作输出**：
```json
{
  "success": true,
  "action": "list",
  "tabs_count": 5,
  "tabs": [
    {
      "index": 0,
      "id": "F7D7569E470E12306173702FCD3E2DE2",
      "title": "Google Gemini",
      "url": "https://gemini.google.com/app/...",
      "full_title": "Google Gemini",
      "full_url": "https://gemini.google.com/app/2b531fd00e311183"
    },
    {
      "index": 1,
      "id": "3EAFDE3EDB2CF5BDDF32862E38D66FC4",
      "title": "Claude",
      "url": "https://claude.ai/new"
    }
  ]
}
```

**select操作输出**：
```json
{
  "success": true,
  "action": "select",
  "selected_tab": {
    "id": "3EAFDE3EDB2CF5BDDF32862E38D66FC4",
    "title": "Claude",
    "url": "https://claude.ai/new",
    "websocket_url": "ws://127.0.0.1:9222/devtools/page/3EAFDE3EDB2CF5BDDF32862E38D66FC4"
  },
  "config_saved": true,
  "config_path": "/home/user/.frago/current_target.json",
  "usage_hint": "后续命令使用: uv run frago --target-id 3EAFDE3EDB2CF5BDDF32862E38D66FC4 <command>"
}
```

## 注意事项

- **Tab ID不稳定**：每次Chrome会话的tab ID都会变化，不要硬编码ID
- **标题/URL匹配**：使用大小写不敏感的模糊匹配，返回第一个匹配的tab
- **配置持久化**：选中的tab信息保存在 `~/.frago/current_target.json`，可供其他工具读取
- **后台操作**：使用 `--target-id` 在指定tab上操作，无需激活该tab

## AI Agent使用建议

1. 执行多tab操作前，先 `list` 获取所有tab信息
2. 根据任务需求选择合适的匹配方式（标题通常比URL更稳定）
3. 保存返回的 `selected_tab.id` 或 `websocket_url` 用于后续操作
4. 如果目标tab被关闭，需要重新执行 `list` 和 `select`

## 更新历史

| 日期 | 版本 | 变更说明 |
|------|------|----------|
| 2025-11-27 | v1.0.0 | 初始版本 |
