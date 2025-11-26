#!/usr/bin/env python3
"""
Recipe: akshare_fetch_stock_latest_price
Description: 获取单只A股的最新实时价格数据
Created: 2025-11-24
Version: 1.0.0
"""

import json
import sys
from datetime import datetime


def main():
    """获取股票最新价格（一次性查询）"""

    # 延迟导入，避免在Recipe发现阶段报错
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

    # 获取分时数据（最新一条即为当前价格）
    try:
        df = ak.stock_zh_a_hist_min_em(symbol=symbol)

        if df.empty:
            print(json.dumps({
                "success": False,
                "error": f"股票 {symbol} 无数据（可能代码错误或非交易时间）"
            }), file=sys.stderr)
            sys.exit(1)

        latest = df.iloc[-1]

        result = {
            "success": True,
            "data": {
                "symbol": symbol,
                "timestamp": str(latest['时间']),
                "price": float(latest['收盘']),
                "change_pct": float(latest['涨跌幅']),
                "change_amount": float(latest['涨跌额']),
                "volume": int(latest['成交量']),
                "amount": float(latest['成交额']),
                "high": float(latest['最高']),
                "low": float(latest['最低']),
                "open": float(latest['开盘']),
                "amplitude": float(latest['振幅']),
                "turnover_rate": float(latest['换手率']),
                "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        }

        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0)

    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": f"获取数据失败: {str(e)}"
        }), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
