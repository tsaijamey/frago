---
name: clipboard_read
type: atomic
runtime: python
version: "1.0.0"
description: 读取系统剪贴板的文本内容
use_cases:
  - 从剪贴板获取用户复制的文本数据
  - 在工作流中使用剪贴板作为临时数据源
  - 快速提取剪贴板内容用于后续处理
tags:
  - clipboard
  - system
  - input
output_targets:
  - stdout
  - file
inputs: {}
outputs:
  content:
    type: string
    description: 剪贴板中的文本内容
  length:
    type: number
    description: 内容的字符长度
---

# Recipe: 读取剪贴板内容

## 功能描述

读取系统剪贴板的当前文本内容，并以 JSON 格式输出。支持跨平台（Linux、macOS、Windows）。

## 使用方法

```bash
# 标准输出
uv run frago recipe run clipboard_read

# 输出到文件
uv run frago recipe run clipboard_read --output-file clipboard.json
```

## 前置条件

- 需要安装 `pyperclip` 模块：`pip install pyperclip`
- Linux 系统可能需要额外安装 `xclip` 或 `xsel`

## 预期输出

```json
{
  "success": true,
  "data": {
    "content": "剪贴板中的文本内容",
    "length": 10
  }
}
```

## 注意事项

- 仅支持文本类型的剪贴板内容，不支持图片等二进制数据
- 如果剪贴板为空，`content` 将是空字符串
- Linux 环境下需要 X11 或 Wayland 会话

## 更新历史

- **v1.0.0** (2025-11-21): 初始版本，支持基础剪贴板读取功能
