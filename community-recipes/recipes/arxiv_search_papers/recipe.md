---
name: arxiv_search_papers
type: atomic
runtime: python
description: "在 arXiv 学术数据库中搜索论文（物理/数学/计算机科学预印本）"
use_cases:
  - "查找最新的计算机科学研究论文"
  - "搜索物理/数学领域的预印本文献"
  - "构建文献综述的数据源"
tags:
  - academic-search
  - arxiv
  - research
  - preprint
output_targets:
  - stdout
  - file
inputs:
  query:
    type: string
    required: true
    description: "搜索关键词（支持布尔逻辑，如 'machine learning AND healthcare'）"
  max_results:
    type: number
    required: false
    default: 10
    description: "最大返回结果数"
outputs:
  success:
    type: boolean
    description: "是否成功执行"
  source:
    type: string
    description: "数据源名称（arXiv）"
  query:
    type: string
    description: "搜索关键词"
  total:
    type: number
    description: "返回的论文数量"
  papers:
    type: array
    description: "论文列表，每篇论文包含 title, authors, published, abstract, url, source, categories"
dependencies: []
version: "1.0.0"
---

# arxiv_search_papers

## 功能描述

在 arXiv 学术数据库中搜索论文。arXiv 是全球最大的预印本论文库，涵盖物理、数学、计算机科学、定量生物学、定量金融、统计学、电气工程和系统科学、经济学等领域。

**核心优势**：
- ✅ **完全免费**：无需 API key，无认证要求
- ✅ **无额外依赖**：仅使用 Python 标准库（urllib, xml.etree）
- ✅ **预印本优先**：获取最新研究成果（早于期刊发表）
- ✅ **分类信息**：提供论文的学科分类

此 Recipe 适合需要快速查找学术文献、构建文献综述、追踪前沿研究的场景。

## 使用方法

**推荐方式**（Recipe 系统）：
```bash
# 基本搜索
uv run frago recipe run arxiv_search_papers \
  --params '{"query": "machine learning"}' \
  --output-file arxiv_results.json

# 指定返回数量
uv run frago recipe run arxiv_search_papers \
  --params '{"query": "deep learning healthcare", "max_results": 20}' \
  --output-file results.json
```

**传统方式**（直接执行）：
```bash
# 使用 Python 直接执行
uv run python examples/atomic/system/arxiv_search_papers.py \
  '{"query": "quantum computing", "max_results": 10}'
```

## 前置条件

- Python 3.9+
- 网络连接（访问 export.arxiv.org）
- 无需额外 Python 库（使用标准库）

## 预期输出

```json
{
  "success": true,
  "source": "arXiv",
  "query": "machine learning",
  "total": 10,
  "papers": [
    {
      "title": "论文标题",
      "authors": ["作者1", "作者2"],
      "published": "2025-11-20",
      "abstract": "论文摘要前300字...",
      "url": "http://arxiv.org/abs/2311.12345v1",
      "source": "arXiv",
      "primary_category": "cs.LG",
      "categories": ["cs.LG", "cs.AI"]
    }
  ]
}
```

**字段说明**：
- `title`: 论文标题（已移除换行符）
- `authors`: 作者列表
- `published`: 发表日期（YYYY-MM-DD）
- `abstract`: 摘要（截取前300字）
- `url`: arXiv 论文链接
- `source`: 数据源标识（"arXiv"）
- `primary_category`: 主要学科分类（如 cs.LG 表示计算机科学-机器学习）
- `categories`: 所有相关学科分类

## 注意事项

- **查询语法**：arXiv API 支持高级查询语法（如 `all:machine learning AND cat:cs.AI`），详见 [arXiv API 文档](https://info.arxiv.org/help/api/index.html)
- **速率限制**：arXiv API 无严格速率限制，但建议每次请求间隔 3 秒以上，避免对服务器造成压力
- **结果排序**：默认按相关性降序排列（`sortBy=relevance, sortOrder=descending`）
- **超时设置**：请求超时设置为 15 秒，网络较慢时可能需要调整
- **XML 解析**：使用 `xml.etree.ElementTree` 解析 Atom feed 格式的响应

## 更新历史

| 日期 | 版本 | 变更说明 |
|------|------|----------|
| 2025-11-24 | v1.0.0 | 初始版本，支持基本搜索和分类信息提取 |
