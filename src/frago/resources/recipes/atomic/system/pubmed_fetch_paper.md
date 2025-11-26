---
name: pubmed_fetch_paper
type: atomic
runtime: python
description: "从 PubMed/PMC 获取论文内容（PDF/XML全文/摘要），支持多格式智能降级"
use_cases:
  - "下载生物医学论文 PDF"
  - "获取 XML 全文用于文本挖掘"
  - "快速获取摘要进行初步筛选"
tags:
  - academic
  - pubmed
  - pmc
  - pdf-download
  - paper-fetch
output_targets:
  - stdout
  - file
inputs:
  identifier:
    type: string
    required: true
    description: "论文标识符，支持 PMID (12345678)、PMCID (PMC1234567)、PubMed URL、PMC URL"
  output_dir:
    type: string
    required: false
    description: "输出目录，默认为当前目录"
  formats:
    type: array
    required: false
    description: "希望获取的格式列表，按优先级排序，默认 ['pdf', 'xml', 'abstract']"
outputs:
  metadata:
    type: object
    description: "论文元数据（标题、作者、摘要、期刊、DOI等）"
  content:
    type: object
    description: "获取到的内容信息（格式、文件路径、大小等）"
dependencies: []
version: "1.1.0"
---

# pubmed_fetch_paper

## 功能描述

从 PubMed/PMC 生物医学数据库获取论文内容。支持多格式智能降级：首先尝试从 PMC 下载 PDF，如果不可用则尝试 XML 全文，最后降级为仅返回摘要。

**重要区分**：
- **PubMed**: 收录生物医学文献的索引数据库，包含元数据和摘要
- **PMC (PubMed Central)**: 全文数据库，仅收录部分论文的全文
- 只有在 PMC Open Access 子集中的论文才能下载 PDF 或 XML 全文

## 使用方法

**通过 Recipe 系统执行**（推荐）：
```bash
# 使用 PMID 下载论文
uv run frago recipe run pubmed_fetch_paper \
  --params '{"identifier": "12345678", "output_dir": "./papers"}'

# 使用 PMCID
uv run frago recipe run pubmed_fetch_paper \
  --params '{"identifier": "PMC1234567", "output_dir": "./papers"}'

# 使用 PubMed URL
uv run frago recipe run pubmed_fetch_paper \
  --params '{"identifier": "https://pubmed.ncbi.nlm.nih.gov/12345678/", "output_dir": "./papers"}'

# 仅获取摘要
uv run frago recipe run pubmed_fetch_paper \
  --params '{"identifier": "12345678", "formats": ["abstract"]}'
```

**直接执行**：
```bash
python examples/atomic/system/pubmed_fetch_paper.py '{"identifier": "12345678", "output_dir": "./papers"}'
```

## 前置条件

- Python 3.9+
- 网络连接（需要访问 ncbi.nlm.nih.gov）
- 无需 API Key（但频繁访问建议注册获取 API Key）

## 预期输出

```json
{
  "success": true,
  "source": "PubMed",
  "metadata": {
    "pmid": "12345678",
    "pmcid": "PMC1234567",
    "title": "论文标题",
    "authors": ["作者1", "作者2"],
    "abstract": "论文摘要...",
    "published": "2024-11",
    "journal": "Nature",
    "doi": "10.1038/xxx",
    "url": "https://pubmed.ncbi.nlm.nih.gov/12345678/",
    "pmc_url": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1234567/"
  },
  "content": {
    "format": "pdf",
    "file_path": "./papers/PMC1234567.pdf",
    "file_size": 2345678,
    "url": "https://..."
  }
}
```

**当论文不在 PMC 中时**：
```json
{
  "success": true,
  "source": "PubMed",
  "metadata": { ... },
  "content": {
    "format": "abstract",
    "text": "论文摘要...",
    "note": "论文不在 PMC Open Access 子集中，仅返回摘要"
  }
}
```

## 注意事项

- **PMC 限制**: 并非所有 PubMed 论文都在 PMC 中有全文，受限于出版商授权
- **Open Access 子集**: 只有 OA 子集中的论文支持程序化下载
- **请求频率**: NCBI 要求不要超过每秒 3 个请求，大批量时请添加延迟
- **文件命名**: 下载的文件使用 PMCID 命名（如 `PMC1234567.pdf`）
- **与搜索配方配合**: 可结合 `pubmed_search_papers` 的输出使用，从搜索结果的 `pmid` 或 `url` 字段获取论文

## 更新历史

| 日期 | 版本 | 变更说明 |
|------|------|----------|
| 2025-11-25 | v1.1.0 | 修复 PMC URL 解析：支持新格式 `pmc.ncbi.nlm.nih.gov/articles/...` |
| 2025-11-25 | v1.0.0 | 初始版本 |
