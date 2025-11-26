#!/usr/bin/env python3
"""
Recipe: akshare_fetch_stock_minute_data
Description: 获取单只A股的完整分时历史数据（当日所有1分钟K线）
Created: 2025-11-24
Version: 1.0.0
"""

import json
import sys
from datetime import datetime


def main():
    """获取股票分时历史数据"""

    # 延迟导入
    try:
        import akshare as ak
    except ImportError:
        print(json.dumps({
            "success": False,
            "error": "缺少依赖: akshare。请运行: uv pip install akshare pandas"
        }), file=sys.stderr)
        sys.exit(1)

    # 解析输入参数
    if len(sys.argv) < 2:
        print(json.dumps({
            "success": False,
            "error": "缺少必需参数: symbol（股票代码）"
        }), file=sys.stderr)
        sys.exit(1)

    try:
        params = json.loads(sys.argv[1])
    except json.JSONDecodeError as e:
        print(json.dumps({
            "success": False,
            "error": f"参数JSON解析失败: {e}"
        }), file=sys.stderr)
        sys.exit(1)

    symbol = params.get("symbol")
    if not symbol:
        print(json.dumps({
            "success": False,
            "error": "参数 'symbol' 不能为空"
        }), file=sys.stderr)
        sys.exit(1)

    # 可选参数：返回格式
    output_format = params.get("format", "full")  # full | summary

    # 获取分时数据
    try:
        df = ak.stock_zh_a_hist_min_em(symbol=symbol)

        if df.empty:
            print(json.dumps({
                "success": False,
                "error": f"股票 {symbol} 无分时数据（可能代码错误或非交易时间）"
            }), file=sys.stderr)
            sys.exit(1)

        # 转换为JSON格式
        if output_format == "summary":
            # 仅返回摘要信息
            result = {
                "success": True,
                "data": {
                    "symbol": symbol,
                    "total_records": len(df),
                    "time_range": {
                        "start": str(df.iloc[0]['时间']),
                        "end": str(df.iloc[-1]['时间'])
                    },
                    "price_range": {
                        "highest": float(df['最高'].max()),
                        "lowest": float(df['最低'].min()),
                        "open": float(df.iloc[0]['开盘']),
                        "close": float(df.iloc[-1]['收盘'])
                    },
                    "total_volume": int(df['成交量'].sum()),
                    "total_amount": float(df['成交额'].sum()),
                    "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
            }
        else:
            # 返回完整数据
            records = []
            for idx, row in df.iterrows():
                records.append({
                    "timestamp": str(row['时间']),
                    "open": float(row['开盘']),
                    "close": float(row['收盘']),
                    "high": float(row['最高']),
                    "low": float(row['最低']),
                    "volume": int(row['成交量']),
                    "amount": float(row['成交额']),
                    "amplitude": float(row['振幅']),
                    "change_pct": float(row['涨跌幅']),
                    "change_amount": float(row['涨跌额']),
                    "turnover_rate": float(row['换手率'])
                })

            result = {
                "success": True,
                "data": {
                    "symbol": symbol,
                    "total_records": len(records),
                    "time_range": {
                        "start": records[0]['timestamp'],
                        "end": records[-1]['timestamp']
                    },
                    "records": records,
                    "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
            }

        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0)

    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": f"获取分时数据失败: {str(e)}"
        }), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
