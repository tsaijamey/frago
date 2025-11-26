---
name: search_academic_papers
type: workflow
runtime: python
description: "并行查询多个学术数据库（arXiv + PubMed），合并结果并按时间排序"
use_cases:
  - "快速获取跨学科领域的文献综述"
  - "同时搜索多个数据库以获得更全面的结果"
  - "比较不同数据库的搜索结果质量"
tags:
  - academic-search
  - parallel-processing
  - multi-database
  - research
output_targets:
  - stdout
  - file
inputs:
  query:
    type: string
    required: true
    description: "搜索关键词（将同时用于所有数据库）"
  databases:
    type: array
    required: false
    default: ["arxiv", "pubmed"]
    description: "要查询的数据库列表，可选: arxiv, pubmed"
  max_results:
    type: number
    required: false
    default: 10
    description: "每个数据库返回的最大结果数"
  sort_by:
    type: string
    required: false
    default: "date"
    description: "排序方式: date（按时间降序）或 relevance（保持API原始排序）"
outputs:
  success:
    type: boolean
    description: "是否成功执行"
  workflow:
    type: string
    description: "Workflow 名称"
  query:
    type: string
    description: "搜索关键词"
  databases_queried:
    type: array
    description: "查询的数据库列表"
  total_papers:
    type: number
    description: "所有数据库返回的论文总数"
  database_stats:
    type: object
    description: "每个数据库的查询统计（成功/失败、数量）"
  papers:
    type: array
    description: "合并并排序后的所有论文列表"
dependencies:
  - arxiv_search_papers
  - pubmed_search_papers
version: "1.0.0"
---

# search_academic_papers

## 功能描述

并行查询多个学术数据库（arXiv + PubMed），合并结果并按时间排序。这是一个 Workflow Recipe，编排了两个 Atomic Recipes 来实现高效的跨数据库文献检索。

**核心优势**：
- ✅ **并行查询**：使用线程池同时查询多个数据库，大幅提升速度
- ✅ **统一输出**：标准化不同数据库的输出格式
- ✅ **智能排序**：支持按时间或相关性排序
- ✅ **容错处理**：单个数据库失败不影响其他数据库查询
- ✅ **详细统计**：提供每个数据库的查询成功率和结果数量

**适用场景**：
- 需要快速获取跨学科文献（如机器学习+医疗健康）
- 希望对比不同数据库的搜索结果
- 构建文献综述时需要全面覆盖

## 使用方法

```bash
# 基本用法（默认查询 arXiv + PubMed）
uv run frago recipe run search_academic_papers \
  --params '{"query": "machine learning healthcare"}' \
  --output-file results.json

# 仅查询 arXiv
uv run frago recipe run search_academic_papers \
  --params '{"query": "quantum computing", "databases": ["arxiv"]}' \
  --output-file arxiv_only.json

# 指定每个数据库返回20篇
uv run frago recipe run search_academic_papers \
  --params '{"query": "deep learning", "max_results": 20}' \
  --output-file results.json

# 按相关性排序（而非时间）
uv run frago recipe run search_academic_papers \
  --params '{"query": "neural networks", "sort_by": "relevance"}' \
  --output-file results.json
```

## 前置条件

- 依赖的 Atomic Recipes 已存在：
  - `arxiv_search_papers`
  - `pubmed_search_papers`
- Python 3.9+
- 网络连接（访问 arXiv 和 PubMed API）
- 无需额外 Python 库（使用标准库）

## 执行流程

1. **参数解析**：验证必需参数（query），设置默认值（databases, max_results, sort_by）
2. **并行查询**：使用 `ThreadPoolExecutor` 同时查询所有指定的数据库
   - 调用 `arxiv_search_papers` Recipe
   - 调用 `pubmed_search_papers` Recipe
3. **结果收集**：等待所有查询完成，收集成功和失败的结果
4. **日期标准化**：统一不同数据库的日期格式为 `YYYY-MM-DD`
5. **排序**：按指定方式排序（默认按时间降序）
6. **汇总输出**：生成包含所有论文和统计信息的 JSON 输出

## 预期输出

```json
{
  "success": true,
  "workflow": "search_academic_papers",
  "query": "machine learning healthcare",
  "databases_queried": ["arxiv", "pubmed"],
  "total_papers": 20,
  "database_stats": {
    "arxiv": {
      "success": true,
      "count": 10
    },
    "pubmed": {
      "success": true,
      "count": 10
    }
  },
  "papers": [
    {
      "title": "论文标题",
      "authors": ["作者1", "作者2"],
      "published": "2025-11-23",
      "published_normalized": "2025-11-23",
      "abstract": "摘要...",
      "url": "https://...",
      "source": "arXiv",
      "primary_category": "cs.LG",
      "categories": ["cs.LG", "cs.AI"]
    },
    {
      "title": "论文标题2",
      "authors": ["Author A", "Author B"],
      "published": "2025 Nov 20",
      "published_normalized": "2025-11-20",
      "abstract": "N/A",
      "url": "https://pubmed.ncbi.nlm.nih.gov/12345678/",
      "source": "PubMed",
      "pmid": "12345678",
      "journal": "Journal Name"
    }
  ]
}
```

**字段说明**：
- `success`: 整体执行是否成功
- `workflow`: Workflow 名称
- `query`: 搜索关键词
- `databases_queried`: 查询的数据库列表
- `total_papers`: 所有数据库返回的论文总数
- `database_stats`: 每个数据库的查询统计
  - `success`: 该数据库是否查询成功
  - `count`: 返回的论文数量
  - `error`: 错误信息（如果失败）
- `papers`: 合并并排序后的所有论文
  - 包含原始 `published` 字段（各数据库格式不同）
  - 新增 `published_normalized` 字段（统一为 YYYY-MM-DD）

## 注意事项

- **并行执行**：使用线程池并行查询，速度取决于最慢的数据库
- **容错机制**：单个数据库查询失败不影响其他数据库，最终结果仍会返回
- **日期格式**：
  - arXiv: `YYYY-MM-DD`
  - PubMed: `YYYY Mon DD`（如 "2025 Nov 23"）
  - Workflow 统一为 `YYYY-MM-DD`（存储在 `published_normalized`）
- **排序逻辑**：
  - `sort_by="date"`: 按 `published_normalized` 降序（最新优先）
  - `sort_by="relevance"`: 保持 API 原始排序（各数据库内部按相关性排序）
- **查询关键词**：相同的关键词将用于所有数据库，但不同数据库的查询语法可能不同
- **摘要缺失**：PubMed 的 `abstract` 字段为 "N/A"（需要额外 API 调用）

## 性能优化建议

1. **限制数据库数量**：只查询需要的数据库以减少等待时间
2. **调整 max_results**：根据需要调整每个数据库的返回数量
3. **使用 API key**（PubMed）：注册免费 API key 提高速率限制（3 req/s → 10 req/s）
4. **缓存结果**：对于重复查询，考虑缓存结果到文件

## 更新历史

| 日期 | 版本 | 变更说明 |
|------|------|----------|
| 2025-11-24 | v1.0.0 | 初始版本，支持 arXiv + PubMed 并行查询，带日期标准化和排序 |
