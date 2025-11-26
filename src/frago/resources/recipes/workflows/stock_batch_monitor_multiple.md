---
name: stock_batch_monitor_multiple
type: workflow
runtime: python
description: "批量获取多只股票的最新价格并汇总分析（支持排序和统计）"
use_cases:
  - "对比多只股票的表现"
  - "筛选涨跌幅最大的股票"
  - "生成投资组合监控报告"
tags:
  - stock
  - batch-processing
  - analysis
  - workflow
output_targets:
  - stdout
  - file
inputs:
  symbols:
    type: array
    required: true
    description: "股票代码数组（如 [\"000001\", \"600000\", \"000002\"]）"
  sort_by:
    type: string
    required: false
    description: "排序方式：'change_pct'（涨跌幅，默认）| 'volume'（成交量）| 'price'（价格）"
  output_file:
    type: string
    required: false
    description: "保存结果到文件路径（可选）"
outputs:
  summary:
    type: object
    description: "汇总统计（成功数、上涨数、平均涨跌幅等）"
  results:
    type: array
    description: "所有成功获取的股票数据（已排序）"
  errors:
    type: array
    description: "获取失败的股票及错误信息"
dependencies:
  - akshare_fetch_stock_latest_price
version: "1.0.0"
---

# stock_batch_monitor_multiple

## 功能描述

批量获取多只A股的最新价格数据，并提供汇总分析功能：
- **并发获取**: 调用 `akshare_fetch_stock_latest_price` Recipe 获取每只股票数据
- **智能排序**: 支持按涨跌幅/成交量/价格排序
- **统计分析**: 自动计算上涨数、下跌数、平均涨跌幅、最大涨跌幅
- **错误处理**: 单只股票失败不影响整体执行，最后汇总错误信息

适用于需要快速了解多只股票整体表现的场景，如投资组合监控、行业板块分析等。

## 使用方法

**基础用法**（按涨跌幅排序）：
```bash
uv run frago recipe run stock_batch_monitor_multiple \
  --params '{"symbols": ["000001", "600000", "000002"]}'
```

**按成交量排序**：
```bash
uv run frago recipe run stock_batch_monitor_multiple \
  --params '{
    "symbols": ["000001", "600000", "000002", "600036"],
    "sort_by": "volume"
  }'
```

**保存到文件**：
```bash
uv run frago recipe run stock_batch_monitor_multiple \
  --params '{
    "symbols": ["000001", "600000", "000002"],
    "output_file": "reports/portfolio_20251124.json"
  }' \
  --output-file batch_result.json
```

## 前置条件

- 依赖 Recipe: `akshare_fetch_stock_latest_price` 必须可用
- 已安装依赖: `uv pip install akshare pandas`
- 网络可访问（需调用 AKShare API）

## 执行流程

1. **步骤1**: 遍历股票代码列表，逐个调用 `akshare_fetch_stock_latest_price`
2. **步骤2**: 收集所有成功结果，按指定方式排序
3. **步骤3**: 计算统计指标（上涨数、平均涨跌幅、最大涨跌幅等）
4. **步骤4**: 汇总结果并输出（stdout + 可选文件）

## 预期输出

### 实时输出（stderr）

```
📊 开始批量获取 3 只股票的数据...
============================================================
[1/3] 获取 000001 数据...
  ✅ 000001 | 价格: ¥12.58 | 涨跌: +2.35%
[2/3] 获取 600000 数据...
  ✅ 600000 | 价格: ¥8.92 | 涨跌: -1.20%
[3/3] 获取 000002 数据...
  ✅ 000002 | 价格: ¥25.48 | 涨跌: +0.85%
============================================================
📈 上涨: 2 | 📉 下跌: 1
📊 平均涨跌幅: +0.67%
🏆 最大涨幅: 000001 (+2.35%)
⚠️  最大跌幅: 600000 (-1.20%)

💾 结果已保存到: reports/portfolio_20251124.json
```

### 最终结果（stdout JSON）

```json
{
  "success": true,
  "workflow": "stock_batch_monitor_multiple",
  "summary": {
    "total_stocks": 3,
    "success_count": 3,
    "error_count": 0,
    "rising_count": 2,
    "falling_count": 1,
    "avg_change_pct": 0.67,
    "max_gainer": {
      "symbol": "000001",
      "change_pct": 2.35
    },
    "max_loser": {
      "symbol": "600000",
      "change_pct": -1.20
    }
  },
  "results": [
    {
      "symbol": "000001",
      "price": 12.58,
      "change_pct": 2.35,
      "volume": 1523456,
      ...
    },
    {
      "symbol": "000002",
      "price": 25.48,
      "change_pct": 0.85,
      ...
    },
    {
      "symbol": "600000",
      "price": 8.92,
      "change_pct": -1.20,
      ...
    }
  ],
  "errors": null
}
```

### 包含错误的输出示例

```json
{
  "success": true,
  "workflow": "stock_batch_monitor_multiple",
  "summary": {
    "total_stocks": 4,
    "success_count": 3,
    "error_count": 1,
    ...
  },
  "results": [...],
  "errors": [
    {
      "symbol": "999999",
      "error": "股票 999999 无数据（可能代码错误或非交易时间）"
    }
  ]
}
```

## 注意事项

- **执行时间**: 批量获取时间 = 股票数量 × 单次获取时间（约2-5秒/只）
- **建议数量**: 建议单次不超过20只股票，否则执行时间过长
- **失败处理**: 单只股票失败不会中止整体流程，失败信息记录在 `errors` 字段
- **排序逻辑**:
  - `change_pct`: 按涨跌幅降序（涨幅最大在前）
  - `volume`: 按成交量降序（成交量最大在前）
  - `price`: 按价格降序（价格最高在前）
- **交易时间**: 非交易时间所有股票都会失败
- **依赖可用性**: 执行前确认 `akshare_fetch_stock_latest_price` 可用：
  ```bash
  uv run frago recipe list | grep akshare_fetch_stock_latest_price
  ```

## 使用场景示例

### 场景1: 自选股监控

```bash
# 创建自选股列表文件 watchlist.json
echo '["000001", "600000", "000002", "600036"]' > watchlist.json

# 批量获取
uv run frago recipe run stock_batch_monitor_multiple \
  --params "{\"symbols\": $(cat watchlist.json)}" \
  --output-file daily_report.json
```

### 场景2: 行业板块分析

```bash
# 银行板块
uv run frago recipe run stock_batch_monitor_multiple \
  --params '{
    "symbols": ["600000", "600036", "601398", "601988"],
    "sort_by": "change_pct"
  }'
```

### 场景3: 定时监控（结合 cron）

```bash
# 每天收盘后15:30执行
30 15 * * 1-5 cd /path/to/frago && uv run frago recipe run stock_batch_monitor_multiple --params '{"symbols": [...]}' --output-file "reports/$(date +\%Y\%m\%d).json"
```

## 更新历史

| 日期 | 版本 | 变更说明 |
|------|------|----------|
| 2025-11-24 | v1.0.0 | 初始版本，支持批量获取、排序和统计分析 |
