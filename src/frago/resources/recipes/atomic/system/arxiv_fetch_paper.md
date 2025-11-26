---
name: arxiv_fetch_paper
type: atomic
runtime: python
description: "直接下载 arXiv 论文 PDF，无需 API 调用，最稳健的方式"
use_cases:
  - "下载单篇 arXiv 论文 PDF"
  - "批量下载论文时作为基础 Recipe"
tags:
  - academic
  - arxiv
  - pdf-download
output_targets:
  - stdout
  - file
inputs:
  identifier:
    type: string
    required: true
    description: "arXiv 论文标识符，支持多种格式：纯 ID (2411.12345)、URL (https://arxiv.org/abs/...)、PDF URL"
  output_dir:
    type: string
    required: false
    description: "输出目录，默认为当前目录"
outputs:
  arxiv_id:
    type: string
    description: "标准化的 arXiv ID"
  content:
    type: object
    description: "下载结果（格式、文件路径、大小、URL）"
dependencies: []
version: "2.0.0"
---

# arxiv_fetch_paper

## 功能描述

直接通过 URL 下载 arXiv 论文 PDF。这是经过调研验证的**最稳健方式**：

- 无需 API 调用，避免限流问题
- 直接访问 `https://arxiv.org/pdf/{id}.pdf`
- 支持新旧两种 arXiv ID 格式
- 自动验证下载内容是否为有效 PDF

相比旧版本移除了：
- arXiv API 元数据获取（易受限流影响）
- 多格式降级逻辑（source/abstract 选项）

如需元数据，建议使用 `arxiv` Python 库单独获取。

## 使用方法

**通过 Recipe 系统执行**（推荐）：
```bash
# 下载单篇论文 PDF
uv run frago recipe run arxiv_fetch_paper \
  --params '{"identifier": "1706.03762", "output_dir": "./papers"}'

# 使用完整 URL
uv run frago recipe run arxiv_fetch_paper \
  --params '{"identifier": "https://arxiv.org/abs/2303.08774", "output_dir": "./papers"}'
```

**直接执行**：
```bash
python examples/atomic/system/arxiv_fetch_paper.py '{"identifier": "1706.03762"}'
```

## 前置条件

- Python 3.9+
- 网络连接（需要访问 arxiv.org）
- 无需 API Key

## 预期输出

```json
{
  "success": true,
  "source": "arXiv",
  "arxiv_id": "1706.03762",
  "content": {
    "format": "pdf",
    "file_path": "./papers/1706.03762.pdf",
    "file_size": 2215245,
    "file_size_mb": 2.11,
    "url": "https://arxiv.org/pdf/1706.03762.pdf"
  }
}
```

## 注意事项

- **请求频率**: 批量下载时建议添加 3 秒延迟，避免触发限流
- **文件命名**: 使用 arXiv ID 命名，旧格式 ID 中的 `/` 替换为 `_`
- **PDF 验证**: 自动检查下载内容是否以 `%PDF` 开头

## 更新历史

| 日期 | 版本 | 变更说明 |
|------|------|----------|
| 2025-11-25 | v2.0.0 | 重构：移除 API 元数据获取，改为纯直接 PDF 下载（更稳健） |
| 2025-11-25 | v1.1.0 | 修复 API 请求：HTTP→HTTPS，增加 User-Agent，超时 15s→30s |
| 2025-11-25 | v1.0.0 | 初始版本 |
