#!/usr/bin/env python3
"""
Workflow: stock_batch_monitor_multiple
Description: 批量获取多只股票的最新价格并汇总分析
Created: 2025-11-24
Version: 1.0.0
"""

import json
import sys
from pathlib import Path


def main():
    """批量监控多只股票"""

    # 导入 RecipeRunner
    try:
        from frago.recipes import RecipeRunner, RecipeExecutionError
    except ImportError:
        print(json.dumps({
            "success": False,
            "error": "无法导入 RecipeRunner，请确保在 Frago 项目环境中运行"
        }), file=sys.stderr)
        sys.exit(1)

    # 解析输入参数
    if len(sys.argv) < 2:
        print(json.dumps({
            "success": False,
            "error": "缺少必需参数: symbols（股票代码列表）"
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

    # 验证必需参数
    symbols = params.get("symbols")
    if not symbols or not isinstance(symbols, list):
        print(json.dumps({
            "success": False,
            "error": "参数 'symbols' 必须是非空数组（如 [\"000001\", \"600000\"]）"
        }), file=sys.stderr)
        sys.exit(1)

    # 可选参数
    sort_by = params.get("sort_by", "change_pct")  # change_pct | volume | price
    output_file = params.get("output_file")  # 可选：保存到文件

    # 初始化 Recipe Runner
    runner = RecipeRunner()
    results = []
    errors = []

    print(f"📊 开始批量获取 {len(symbols)} 只股票的数据...", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    try:
        # 步骤1: 批量调用 akshare_fetch_stock_latest_price
        for idx, symbol in enumerate(symbols, 1):
            print(f"[{idx}/{len(symbols)}] 获取 {symbol} 数据...", file=sys.stderr)

            try:
                result = runner.run('akshare_fetch_stock_latest_price', params={
                    "symbol": symbol
                })

                if result["success"]:
                    results.append(result["data"])
                    stock_data = result["data"]
                    print(
                        f"  ✅ {symbol} | 价格: ¥{stock_data['price']:.2f} | "
                        f"涨跌: {stock_data['change_pct']:+.2f}%",
                        file=sys.stderr
                    )
                else:
                    errors.append({
                        "symbol": symbol,
                        "error": result.get("error", "Unknown error")
                    })
                    print(f"  ❌ {symbol} | 获取失败", file=sys.stderr)

            except RecipeExecutionError as e:
                errors.append({
                    "symbol": symbol,
                    "error": e.stderr
                })
                print(f"  ❌ {symbol} | Recipe执行失败: {e.stderr}", file=sys.stderr)

            except Exception as e:
                errors.append({
                    "symbol": symbol,
                    "error": str(e)
                })
                print(f"  ❌ {symbol} | 未知错误: {e}", file=sys.stderr)

        print("=" * 60, file=sys.stderr)

        # 步骤2: 排序和分析
        if results:
            # 排序
            if sort_by == "change_pct":
                results.sort(key=lambda x: x['change_pct'], reverse=True)
            elif sort_by == "volume":
                results.sort(key=lambda x: x['volume'], reverse=True)
            elif sort_by == "price":
                results.sort(key=lambda x: x['price'], reverse=True)

            # 统计分析
            prices = [r['price'] for r in results]
            changes = [r['change_pct'] for r in results]
            volumes = [r['volume'] for r in results]

            summary = {
                "total_stocks": len(symbols),
                "success_count": len(results),
                "error_count": len(errors),
                "rising_count": len([c for c in changes if c > 0]),
                "falling_count": len([c for c in changes if c < 0]),
                "avg_change_pct": sum(changes) / len(changes) if changes else 0,
                "max_gainer": {
                    "symbol": results[0]['symbol'],
                    "change_pct": results[0]['change_pct']
                } if sort_by == "change_pct" and results else None,
                "max_loser": {
                    "symbol": results[-1]['symbol'],
                    "change_pct": results[-1]['change_pct']
                } if sort_by == "change_pct" and results else None
            }

            print(f"📈 上涨: {summary['rising_count']} | 📉 下跌: {summary['falling_count']}", file=sys.stderr)
            print(f"📊 平均涨跌幅: {summary['avg_change_pct']:+.2f}%", file=sys.stderr)
            if summary['max_gainer']:
                print(
                    f"🏆 最大涨幅: {summary['max_gainer']['symbol']} "
                    f"({summary['max_gainer']['change_pct']:+.2f}%)",
                    file=sys.stderr
                )
            if summary['max_loser']:
                print(
                    f"⚠️  最大跌幅: {summary['max_loser']['symbol']} "
                    f"({summary['max_loser']['change_pct']:+.2f}%)",
                    file=sys.stderr
                )

        else:
            summary = {
                "total_stocks": len(symbols),
                "success_count": 0,
                "error_count": len(errors)
            }

        # 步骤3: 返回汇总结果
        output = {
            "success": True,
            "workflow": "stock_batch_monitor_multiple",
            "summary": summary,
            "results": results,
            "errors": errors if errors else None
        }

        # 保存到文件（如果指定）
        if output_file:
            output_path = Path(output_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(output, f, ensure_ascii=False, indent=2)
            print(f"\n💾 结果已保存到: {output_file}", file=sys.stderr)

        # 输出到 stdout
        print(json.dumps(output, ensure_ascii=False, indent=2))
        sys.exit(0)

    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": {
                "type": type(e).__name__,
                "message": str(e)
            }
        }, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
