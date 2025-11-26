---
name: akshare_fetch_stock_minute_data
type: atomic
runtime: python
description: "获取单只A股的完整分时历史数据（当日所有1分钟K线）"
use_cases:
  - "分析股票当日走势和价格波动"
  - "生成分时K线图表"
  - "计算技术指标（VWAP、布林带等）"
  - "回测交易策略"
tags:
  - stock
  - akshare
  - historical-data
  - minute-kline
  - china-a-stock
output_targets:
  - stdout
  - file
inputs:
  symbol:
    type: string
    required: true
    description: "A股股票代码（6位数字）"
  format:
    type: string
    required: false
    description: "输出格式：'full' 完整数据（默认）或 'summary' 仅摘要"
outputs:
  data:
    type: object
    description: "包含分时K线数组（full）或摘要信息（summary）"
dependencies: []
version: "1.0.0"
---

# akshare_fetch_stock_minute_data

## 功能描述

通过 AKShare API 获取单只A股的完整分时历史数据（当日所有1分钟K线），包括：
- 每分钟的开盘/收盘/最高/最低价
- 成交量、成交额、换手率
- 涨跌幅、涨跌额、振幅
- 时间序列数据（从开盘到当前时刻）

支持两种输出格式：
- **full**: 返回所有分时记录（通常200-240条）
- **summary**: 仅返回摘要统计（记录数、价格区间、总成交量等）

## 使用方法

**完整数据模式**：
```bash
uv run frago recipe run akshare_fetch_stock_minute_data \
  --params '{"symbol": "000001"}' \
  --output-file minute_data.json
```

**摘要模式**（数据量更小）：
```bash
uv run frago recipe run akshare_fetch_stock_minute_data \
  --params '{"symbol": "000001", "format": "summary"}' \
  --output-file summary.json
```

## 前置条件

- 已安装依赖: `uv pip install akshare pandas`
- 网络可访问（需连接东方财富网API）
- 必须在交易日执行（非交易日无数据）

## 预期输出

### Full 格式输出

```json
{
  "success": true,
  "data": {
    "symbol": "000001",
    "total_records": 240,
    "time_range": {
      "start": "2025-11-24 09:30:00",
      "end": "2025-11-24 15:00:00"
    },
    "records": [
      {
        "timestamp": "2025-11-24 09:31:00",
        "open": 12.30,
        "close": 12.32,
        "high": 12.35,
        "low": 12.28,
        "volume": 152345,
        "amount": 1876543.21,
        "amplitude": 0.57,
        "change_pct": 0.16,
        "change_amount": 0.02,
        "turnover_rate": 0.008
      },
      ...
    ],
    "fetched_at": "2025-11-24 15:30:00"
  }
}
```

### Summary 格式输出

```json
{
  "success": true,
  "data": {
    "symbol": "000001",
    "total_records": 240,
    "time_range": {
      "start": "2025-11-24 09:30:00",
      "end": "2025-11-24 15:00:00"
    },
    "price_range": {
      "highest": 12.68,
      "lowest": 12.25,
      "open": 12.30,
      "close": 12.58
    },
    "total_volume": 15234567,
    "total_amount": 192345678.90,
    "fetched_at": "2025-11-24 15:30:00"
  }
}
```

## 注意事项

- **数据量**: Full模式输出较大（通常几十KB），建议使用 `--output-file` 保存
- **交易时间**: 仅交易日有数据，周末/节假日无法获取
- **时间范围**: 仅包含当日数据（9:30-15:00，午间休市无数据）
- **数据延迟**: 免费API通常有1-5分钟延迟
- **用途选择**:
  - 需要绘制K线图或计算指标 → 使用 full 格式
  - 仅需统计信息 → 使用 summary 格式（减少网络传输）

## 更新历史

| 日期 | 版本 | 变更说明 |
|------|------|----------|
| 2025-11-24 | v1.0.0 | 初始版本，支持full/summary两种输出格式 |
