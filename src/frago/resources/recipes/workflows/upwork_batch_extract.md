---
name: upwork_batch_extract
type: workflow
runtime: python
version: "1.0"
description: "批量提取多个 Upwork 职位信息，自动导航并生成汇总文档"
use_cases:
  - "批量收集 Upwork 工作机会信息"
  - "建立工作档案库进行市场分析"
  - "自动化职位调研流程"
output_targets:
  - stdout
  - file
tags:
  - upwork
  - batch-processing
  - workflow
  - job-extraction
inputs:
  urls:
    type: array
    required: true
    description: "要提取的 Upwork 职位详情页 URL 列表"
    items:
      type: string
      format: url
  output_dir:
    type: string
    required: false
    description: "输出目录路径（默认: ./jobs/）"
    default: "./jobs/"
outputs:
  success:
    type: boolean
    description: "所有提取任务是否全部成功"
  total:
    type: number
    description: "总任务数"
  successful:
    type: number
    description: "成功任务数"
  failed:
    type: number
    description: "失败任务数"
  results:
    type: array
    description: "每个 URL 的处理结果详情"
  output_dir:
    type: string
    description: "输出文件存储目录"
dependencies:
  - upwork_extract_job_details_as_markdown
---

# upwork_batch_extract

## 功能描述

批量提取多个 Upwork 职位信息的 Workflow Recipe。自动完成以下流程：
1. 遍历提供的 URL 列表
2. 自动导航到每个职位详情页
3. 调用 `upwork_extract_job_details_as_markdown` Recipe 提取信息
4. 将每个职位信息保存为独立的 Markdown 文件
5. 生成包含所有处理结果的汇总报告

适用于需要批量收集 Upwork 工作机会信息、建立工作档案库或进行市场分析的场景。

## 使用方法

**前置条件**：
- Chrome 浏览器已启动并开启远程调试（`chrome --remote-debugging-port=9222`）
- 已安装 Frago CLI 工具
- 依赖的 Recipe `upwork_extract_job_details_as_markdown` 可用

**执行方式**：

```bash
# 通过 Recipe CLI 执行
uv run frago recipe run upwork_batch_extract \
  --params '{"urls": ["https://www.upwork.com/jobs/~1", "https://www.upwork.com/jobs/~2"], "output_dir": "./jobs/"}'

# 或通过 params-file 传递参数
cat > params.json << EOF
{
  "urls": [
    "https://www.upwork.com/jobs/~0123456789",
    "https://www.upwork.com/jobs/~9876543210"
  ],
  "output_dir": "./upwork_jobs/"
}
EOF

uv run frago recipe run upwork_batch_extract --params-file params.json
```

**参数说明**：

- `urls` (必需): Upwork 职位详情页 URL 数组，格式为 `https://www.upwork.com/jobs/~<job_id>`
- `output_dir` (可选): 输出目录路径，默认为 `./jobs/`，会自动创建不存在的目录

## 前置条件

- Chrome 浏览器已启动并开启远程调试端口 9222
- Chrome DevTools Protocol 连接正常
- 依赖 Recipe `upwork_extract_job_details_as_markdown` 已存在且可用
- Python 3.9+ 环境（用于执行 Workflow）
- 网络连接正常，可访问 Upwork 网站

## 预期输出

**文件输出**：
- 每个职位信息保存为独立的 Markdown 文件：`{output_dir}/job_{job_id}.md`
- 文件命名基于 URL 中的 job_id

**JSON 输出**（stdout）：

```json
{
  "success": true,
  "total": 2,
  "successful": 2,
  "failed": 0,
  "results": [
    {
      "url": "https://www.upwork.com/jobs/~0123456789",
      "status": "success",
      "output_file": "./jobs/job_0123456789.md",
      "execution_time": 3.45
    },
    {
      "url": "https://www.upwork.com/jobs/~9876543210",
      "status": "success",
      "output_file": "./jobs/job_9876543210.md",
      "execution_time": 2.89
    }
  ],
  "output_dir": "./jobs/"
}
```

**失败情况输出**：

```json
{
  "success": false,
  "total": 2,
  "successful": 1,
  "failed": 1,
  "results": [
    {
      "url": "https://www.upwork.com/jobs/~0123456789",
      "status": "success",
      "output_file": "./jobs/job_0123456789.md",
      "execution_time": 3.45
    },
    {
      "url": "https://www.upwork.com/jobs/~invalid",
      "status": "failed",
      "error": "页面加载失败",
      "error_type": "Exception"
    }
  ],
  "output_dir": "./jobs/"
}
```

## 注意事项

- **依赖 Recipe 稳定性**：Workflow 依赖 `upwork_extract_job_details_as_markdown` Recipe，如果该 Recipe 失效（如 Upwork 改版），Workflow 也会失败

- **导航延迟**：每次导航到新页面后会等待 3 秒以确保页面完全加载，这个延迟可能需要根据网络情况调整

- **错误处理**：
  - 单个 URL 处理失败不会中断整个流程，会继续处理剩余 URL
  - 最终返回所有处理结果，包括成功和失败的详情
  - 如果有任何失败任务，退出码为 1

- **并发限制**：当前实现按顺序处理 URL（串行），不支持并发。处理大量 URL 时会较慢

- **浏览器状态**：所有 URL 使用同一个浏览器 tab，确保 CDP 连接保持活跃

- **输出文件命名**：基于 URL 中的 job_id（去除 `~` 前缀），如果 URL 格式不标准可能导致命名冲突

- **异常传播**：Workflow 中调用原子 Recipe 时，会捕获 `RecipeExecutionError` 异常并记录到结果中，不会直接抛出

## 更新历史

| 日期 | 版本 | 变更说明 |
|------|------|----------|
| 2025-11-21 | v1.0 | 初始版本，支持批量提取 Upwork 职位信息 |
