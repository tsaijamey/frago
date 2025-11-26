---
name: pubmed_search_papers
type: atomic
runtime: python
description: "在 PubMed 生物医学数据库中搜索论文（NCBI E-utilities API）"
use_cases:
  - "搜索生物医学和生命科学领域的文献"
  - "查找临床研究和医学论文"
  - "获取具有 PMID 的标准化医学文献"
tags:
  - academic-search
  - pubmed
  - biomedical
  - ncbi
output_targets:
  - stdout
  - file
inputs:
  query:
    type: string
    required: true
    description: "搜索关键词（支持 PubMed 高级查询语法）"
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
    description: "数据源名称（PubMed）"
  query:
    type: string
    description: "搜索关键词"
  total:
    type: number
    description: "返回的论文数量"
  papers:
    type: array
    description: "论文列表，每篇论文包含 title, authors, published, url, pmid, journal, pub_type"
dependencies: []
version: "1.0.0"
---

# pubmed_search_papers

## 功能描述

在 PubMed 生物医学数据库中搜索论文。PubMed 是由美国国家生物技术信息中心（NCBI）维护的免费数据库，包含超过 3600 万条生物医学文献引用和摘要。

**核心优势**：
- ✅ **完全免费**：无需 API key，无认证要求
- ✅ **无额外依赖**：仅使用 Python 标准库（urllib, json）
- ✅ **权威来源**：NCBI 官方维护，医学领域最权威数据库
- ✅ **标准化数据**：每篇论文都有唯一的 PMID（PubMed ID）

此 Recipe 适合生物医学、临床研究、药学、护理学等领域的文献检索。

## 使用方法

**推荐方式**（Recipe 系统）：
```bash
# 基本搜索
uv run frago recipe run pubmed_search_papers \
  --params '{"query": "cancer immunotherapy"}' \
  --output-file pubmed_results.json

# 指定返回数量
uv run frago recipe run pubmed_search_papers \
  --params '{"query": "diabetes AND machine learning", "max_results": 20}' \
  --output-file results.json
```

**传统方式**（直接执行）：
```bash
# 使用 Python 直接执行
uv run python examples/atomic/system/pubmed_search_papers.py \
  '{"query": "COVID-19 vaccine", "max_results": 10}'
```

## 前置条件

- Python 3.9+
- 网络连接（访问 eutils.ncbi.nlm.nih.gov）
- 无需额外 Python 库（使用标准库）

## 预期输出

```json
{
  "success": true,
  "source": "PubMed",
  "query": "machine learning healthcare",
  "total": 10,
  "papers": [
    {
      "title": "论文标题",
      "authors": ["Author A", "Author B"],
      "published": "2025 Nov 23",
      "abstract": "N/A",
      "url": "https://pubmed.ncbi.nlm.nih.gov/12345678/",
      "source": "PubMed",
      "pmid": "12345678",
      "journal": "Journal Name",
      "pub_type": ["Journal Article", "Research Support"]
    }
  ]
}
```

**字段说明**：
- `title`: 论文标题
- `authors`: 作者列表（最多前10位）
- `published`: 发表日期（格式：YYYY Mon DD）
- `abstract`: 摘要（esummary API 不返回，标记为 "N/A"）
- `url`: PubMed 论文页面链接
- `source`: 数据源标识（"PubMed"）
- `pmid`: PubMed ID（唯一标识符）
- `journal`: 期刊全称
- `pub_type`: 出版类型（如 Journal Article, Review, Clinical Trial）

## 注意事项

- **查询语法**：PubMed 支持高级查询语法（如 `diabetes[Title] AND 2024[PDAT]`），详见 [PubMed 高级搜索指南](https://pubmed.ncbi.nlm.nih.gov/help/)
- **速率限制**：
  - **无 API key**: 最多每秒 3 个请求
  - **有 API key**: 最多每秒 10 个请求（在 URL 中添加 `&api_key=YOUR_KEY`）
  - 建议注册免费 API key 以提高速率
- **摘要获取**：当前使用 `esummary` API 不返回摘要。如需摘要，需额外调用 `efetch` API（未实现）
- **超时设置**：请求超时设置为 15 秒
- **PMID 唯一性**：每篇论文的 PMID 是永久性的唯一标识符，可用于引用和跨数据库链接

## API 端点说明

此 Recipe 使用两个 NCBI E-utilities API 端点：

1. **esearch.fcgi** - 搜索并返回 PMID 列表
   - 参数：`db=pubmed`, `term=<query>`, `retmax=<N>`, `retmode=json`
   - 返回：PMID 列表（JSON 格式）

2. **esummary.fcgi** - 根据 PMID 获取论文详细信息
   - 参数：`db=pubmed`, `id=<PMID1,PMID2,...>`, `retmode=json`
   - 返回：论文元数据（标题、作者、期刊等）

## 更新历史

| 日期 | 版本 | 变更说明 |
|------|------|----------|
| 2025-11-24 | v1.0.0 | 初始版本，支持基本搜索和元数据提取（不含摘要） |
