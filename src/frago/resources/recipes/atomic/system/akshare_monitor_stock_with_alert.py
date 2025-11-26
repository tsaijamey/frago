#!/usr/bin/env python3
"""
Recipe: akshare_monitor_stock_with_alert
Description: 持续监控股票价格并在异常波动时告警
Created: 2025-11-24
Version: 1.0.0
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path


def main():
    """监控股票价格并告警"""

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
            "error": "缺少必需参数: symbol"
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

    # 提取参数
    symbol = params.get("symbol")
    if not symbol:
        print(json.dumps({
            "success": False,
            "error": "参数 'symbol' 不能为空"
        }), file=sys.stderr)
        sys.exit(1)

    interval = params.get("interval", 60)  # 默认60秒
    duration = params.get("duration", 300)  # 默认5分钟
    output_dir = params.get("output_dir", "outputs")
    alert_change_pct = params.get("alert_change_pct", 3.0)  # 默认3%
    alert_amplitude = params.get("alert_amplitude", 8.0)  # 默认8%

    # 创建输出目录
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    data_file = output_path / f"monitor_{symbol}_{timestamp}.jsonl"
    alert_dir = output_path / "alerts"
    alert_dir.mkdir(parents=True, exist_ok=True)

    # 打印启动信息到 stderr（不干扰JSON输出）
    print(f"🚀 开始监控股票 {symbol}", file=sys.stderr)
    print(f"⏰ 轮询间隔: {interval}秒", file=sys.stderr)
    print(f"⏱️  监控时长: {duration}秒", file=sys.stderr)
    print(f"📁 数据文件: {data_file}", file=sys.stderr)
    print(f"🔔 告警阈值: 涨跌幅±{alert_change_pct}%, 振幅>{alert_amplitude}%", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    start_time = time.time()
    count = 0
    error_count = 0
    alerts_triggered = []

    try:
        while time.time() - start_time < duration:
            count += 1

            # 获取最新数据（带重试）
            data = None
            for retry in range(3):
                try:
                    df = ak.stock_zh_a_hist_min_em(symbol=symbol)
                    if not df.empty:
                        latest = df.iloc[-1]
                        data = {
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
                        break
                except Exception as e:
                    if retry == 2:
                        print(f"❌ [{count}] 获取失败（重试3次后）: {e}", file=sys.stderr)
                    time.sleep(2)

            if data is None:
                error_count += 1
                if error_count >= 3:
                    print("🚨 连续3次获取数据失败，可能网络异常", file=sys.stderr)
                    error_count = 0
                time.sleep(interval)
                continue

            error_count = 0

            # 保存数据到 JSONL
            with open(data_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(data, ensure_ascii=False) + '\n')

            # 检查告警条件
            alerts = []
            if abs(data['change_pct']) > alert_change_pct:
                alerts.append({
                    "type": "price_change",
                    "message": f"涨跌幅 {data['change_pct']:+.2f}% 超过阈值 ±{alert_change_pct}%",
                    "severity": "high"
                })

            if data['amplitude'] > alert_amplitude:
                alerts.append({
                    "type": "amplitude",
                    "message": f"振幅 {data['amplitude']:.2f}% 超过阈值 {alert_amplitude}%",
                    "severity": "medium"
                })

            # 发送告警
            if alerts:
                for alert in alerts:
                    print(f"⚠️  [{count}] 告警: {alert['message']}", file=sys.stderr)

                    # 保存告警到文件
                    alert_file = alert_dir / f"alert_{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                    alert_data = {
                        "symbol": symbol,
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "alert": alert,
                        "data": data
                    }
                    with open(alert_file, 'w', encoding='utf-8') as f:
                        json.dump(alert_data, f, ensure_ascii=False, indent=2)

                    alerts_triggered.append(alert_data)

            # 打印状态
            print(
                f"✅ [{count}] {data['timestamp']} | "
                f"价格: ¥{data['price']:.2f} | "
                f"涨跌: {data['change_pct']:+.2f}% | "
                f"成交量: {data['volume']:,}",
                file=sys.stderr
            )

            # 等待下一次轮询
            time.sleep(interval)

    except KeyboardInterrupt:
        print("\n⚠️  用户中断监控", file=sys.stderr)

    except Exception as e:
        print(f"\n❌ 监控异常: {e}", file=sys.stderr)
        print(json.dumps({
            "success": False,
            "error": str(e)
        }), file=sys.stderr)
        sys.exit(1)

    finally:
        elapsed = time.time() - start_time
        print("=" * 60, file=sys.stderr)
        print("📊 监控结束", file=sys.stderr)
        print(f"⏱️  总耗时: {elapsed:.0f}秒", file=sys.stderr)
        print(f"📝 采集次数: {count}次", file=sys.stderr)
        print(f"🔔 告警次数: {len(alerts_triggered)}次", file=sys.stderr)

        # 输出最终结果到 stdout
        result = {
            "success": True,
            "data": {
                "symbol": symbol,
                "start_time": datetime.fromtimestamp(start_time).strftime("%Y-%m-%d %H:%M:%S"),
                "end_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "duration_seconds": int(elapsed),
                "interval_seconds": interval,
                "total_samples": count,
                "alert_count": len(alerts_triggered),
                "alerts": alerts_triggered,
                "data_file": str(data_file),
                "alert_dir": str(alert_dir)
            }
        }

        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0)


if __name__ == "__main__":
    main()
