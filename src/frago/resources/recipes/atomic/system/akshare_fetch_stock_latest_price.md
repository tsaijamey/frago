---
name: akshare_fetch_stock_latest_price
type: atomic
runtime: python
description: "获取单只A股的最新实时价格数据（基于AKShare API）"
use_cases:
  - "快速查询股票当前价格"
  - "供Workflow Recipe调用获取实时数据"
  - "构建股价监控和分析工具的基础模块"
tags:
  - stock
  - akshare
  - realtime-data
  - china-a-stock
output_targets:
  - stdout
inputs:
  symbol:
    type: string
    required: true
    description: "A股股票代码（6位数字，如 000001 为平安银行）"
outputs:
  data:
    type: object
    description: "包含价格、涨跌幅、成交量等完整市场数据"
dependencies: []
version: "1.0.0"
---

# akshare_fetch_stock_latest_price

## 功能描述

通过 AKShare API 获取单只A股的最新实时价格数据（基于分时行情最新一条记录）。返回结构化的JSON数据，包含：
- 当前价格、涨跌幅、涨跌额
- 成交量、成交额、换手率
- 当日最高/最低/开盘价、振幅
- 数据时间戳

适用于需要快速获取股价信息的场景，可作为更复杂监控和分析工具的基础模块。

## 使用方法

**Recipe 系统执行**（推荐）：
```bash
uv run frago recipe run akshare_fetch_stock_latest_price \
  --params '{"symbol": "000001"}' \
  --output-file result.json
```

**直接执行**：
```bash
uv run examples/atomic/system/akshare_fetch_stock_latest_price.py \
  '{"symbol": "000001"}'
```

## 前置条件

- 已安装依赖: `uv pip install akshare pandas`
- 网络可访问（需连接东方财富网API）
- 输入正确的6位A股代码（如 000001, 600000）

## 预期输出

成功时输出到 stdout：
```json
{
  "success": true,
  "data": {
    "symbol": "000001",
    "timestamp": "2025-11-24 15:00:00",
    "price": 12.58,
    "change_pct": 2.35,
    "change_amount": 0.29,
    "volume": 15234567,
    "amount": 192345678.90,
    "high": 12.68,
    "low": 12.25,
    "open": 12.30,
    "amplitude": 3.50,
    "turnover_rate": 0.85,
    "fetched_at": "2025-11-24 15:30:12"
  }
}
```

失败时输出到 stderr：
```json
{
  "success": false,
  "error": "股票 999999 无数据（可能代码错误或非交易时间）"
}
```

## 注意事项

- **交易时间限制**: 非交易时间或停牌股票可能返回空数据
- **代码格式**: 必须是6位数字（如 `000001`），不含前缀（如 `sz000001`）
- **数据延迟**: AKShare 免费API通常有1-5分钟延迟
- **速率限制**: 频繁调用可能被限流，建议控制调用频率（如每分钟不超过60次）
- **依赖稳定性**: 依赖AKShare库和东方财富网API，如API变更可能导致失效

## 更新历史

| 日期 | 版本 | 变更说明 |
|------|------|----------|
| 2025-11-24 | v1.0.0 | 初始版本，提取自stock-price-monitoring-research项目 |
