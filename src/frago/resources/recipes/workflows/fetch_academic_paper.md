---
name: fetch_academic_paper
type: workflow
runtime: python
description: "统一论文获取接口，自动识别来源（arXiv/PubMed/PMC）并选择合适的获取策略"
use_cases:
  - "批量下载搜索结果中的论文"
  - "从混合来源的论文列表获取内容"
  - "结合 search_academic_papers 工作流使用"
tags:
  - academic
  - batch-processing
  - paper-fetch
  - arxiv
  - pubmed
output_targets:
  - stdout
  - file
inputs:
  identifiers:
    type: array
    required: false
    description: "论文标识符列表，支持 arXiv ID、PMID、PMCID、各平台 URL 的混合"
  identifier:
    type: string
    required: false
    description: "单个论文标识符（与 identifiers 二选一）"
  output_dir:
    type: string
    required: false
    description: "输出目录，默认 './papers'"
  parallel:
    type: boolean
    required: false
    description: "是否并行获取，默认 false（串行更稳健）"
  max_workers:
    type: number
    required: false
    description: "最大并行数，默认 2"
  delay:
    type: number
    required: false
    description: "串行模式下请求间隔（秒），默认 3.0"
outputs:
  stats:
    type: object
    description: "获取统计（总数、成功数、失败数、各来源数量）"
  results:
    type: array
    description: "每篇论文的获取结果"
dependencies:
  - arxiv_fetch_paper
  - pubmed_fetch_paper
version: "2.0.0"
---

# fetch_academic_paper

## 功能描述

统一的论文获取工作流，自动识别论文来源并调用相应的 Atomic Recipe：

- **arXiv 论文**: 调用 `arxiv_fetch_paper`（v2.0.0），**直接 URL 下载 PDF**
- **PubMed/PMC 论文**: 调用 `pubmed_fetch_paper`，从 PMC 获取全文

**v2.0.0 主要变更**：
- arXiv 分支简化为直接 PDF 下载，移除 API 元数据获取
- 默认改为串行模式（`parallel: false`），添加 3 秒延迟，避免限流
- 显示下载文件大小

**来源识别规则**：
| 输入格式 | 识别为 |
|---------|--------|
| `2411.12345` | arXiv |
| `hep-th/0601001` | arXiv |
| `https://arxiv.org/abs/...` | arXiv |
| `12345678` (7-8位数字) | PubMed |
| `PMC1234567` | PMC |
| `https://pubmed.ncbi.nlm.nih.gov/...` | PubMed |
| `https://www.ncbi.nlm.nih.gov/pmc/articles/...` | PMC |
| `https://pmc.ncbi.nlm.nih.gov/articles/...` | PMC (新格式) |

## 使用方法

**获取单篇论文**：
```bash
uv run frago recipe run fetch_academic_paper \
  --params '{"identifier": "1706.03762", "output_dir": "./papers"}'
```

**批量获取（混合来源）**：
```bash
uv run frago recipe run fetch_academic_paper \
  --params '{
    "identifiers": [
      "1706.03762",
      "2303.08774",
      "https://pubmed.ncbi.nlm.nih.gov/12345678/"
    ],
    "output_dir": "./papers"
  }'
```

**调整延迟时间**：
```bash
uv run frago recipe run fetch_academic_paper \
  --params '{
    "identifiers": ["1706.03762", "2303.08774"],
    "delay": 5.0
  }'
```

**启用并行模式**（可能触发限流）：
```bash
uv run frago recipe run fetch_academic_paper \
  --params '{
    "identifiers": ["1706.03762", "2303.08774"],
    "parallel": true,
    "max_workers": 2
  }'
```

## 前置条件

- 依赖的 Atomic Recipe 已存在：
  - `arxiv_fetch_paper`
  - `pubmed_fetch_paper`
- 网络连接
- Python 3.9+

## 预期输出

```json
{
  "success": true,
  "workflow": "fetch_academic_paper",
  "output_dir": "./papers",
  "stats": {
    "total": 2,
    "success": 2,
    "failed": 0,
    "sources": {
      "arxiv": 2
    }
  },
  "results": [
    {
      "success": true,
      "source": "arXiv",
      "arxiv_id": "1706.03762",
      "detected_source": "arxiv",
      "recipe_used": "arxiv_fetch_paper",
      "content": {
        "format": "pdf",
        "file_path": "./papers/1706.03762.pdf",
        "file_size": 2215245,
        "file_size_mb": 2.11,
        "url": "https://arxiv.org/pdf/1706.03762.pdf"
      }
    },
    {
      "success": true,
      "source": "arXiv",
      "arxiv_id": "2303.08774",
      "detected_source": "arxiv",
      "recipe_used": "arxiv_fetch_paper",
      "content": {
        "format": "pdf",
        "file_path": "./papers/2303.08774.pdf",
        "file_size": 5242880,
        "file_size_mb": 5.0,
        "url": "https://arxiv.org/pdf/2303.08774.pdf"
      }
    }
  ]
}
```

## 注意事项

- **请求频率**: 默认 3 秒延迟，可通过 `delay` 参数调整
- **并行模式**: 可能触发 arXiv 限流（HTTP 429），建议仅在少量论文时使用
- **部分成功**: 即使部分论文获取失败，工作流也会继续处理其他论文
- **输出目录**: 会自动创建，不同来源的论文统一存放

## 更新历史

| 日期 | 版本 | 变更说明 |
|------|------|----------|
| 2025-11-25 | v2.0.0 | arXiv 分支改用直接 PDF 下载；默认串行模式避免限流 |
| 2025-11-25 | v1.1.0 | 修复 PMC URL 检测：支持新格式 `pmc.ncbi.nlm.nih.gov/articles/...` |
| 2025-11-25 | v1.0.0 | 初始版本 |
