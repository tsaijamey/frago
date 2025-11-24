"""性能测试 - Run命令系统

验证性能目标:
- log 命令 <50ms
- init 命令 <100ms
- 支持 10k+ 日志条目
"""

import time
from pathlib import Path
from datetime import datetime

from frago.run.manager import RunManager
from frago.run.logger import RunLogger
from frago.run.context import ContextManager
from frago.run.models import ActionType, ExecutionMethod, LogStatus


def test_init_performance():
    """测试 init 命令性能（<100ms）"""
    runs_dir = Path("/tmp/frago_perf_test/runs")
    runs_dir.mkdir(parents=True, exist_ok=True)

    manager = RunManager(runs_dir)

    start = time.time()
    instance = manager.create_run("性能测试任务")
    elapsed = (time.time() - start) * 1000  # 转换为毫秒

    print(f"init 命令性能: {elapsed:.2f}ms")
    assert elapsed < 100, f"init命令超时: {elapsed}ms > 100ms"

    # 清理
    import shutil
    shutil.rmtree(runs_dir)


def test_log_performance():
    """测试 log 命令性能（<50ms）"""
    runs_dir = Path("/tmp/frago_perf_test/runs")
    runs_dir.mkdir(parents=True, exist_ok=True)

    # 先创建一个run实例
    manager = RunManager(runs_dir)
    instance = manager.create_run("日志性能测试")

    run_dir = runs_dir / instance.run_id
    logger = RunLogger(run_dir)

    # 测试日志写入性能
    start = time.time()
    logger.write_log(
        step="测试日志",
        status=LogStatus.SUCCESS,
        action_type=ActionType.ANALYSIS,
        execution_method=ExecutionMethod.MANUAL,
        data={"test": "performance"}
    )
    elapsed = (time.time() - start) * 1000  # 转换为毫秒

    print(f"log 命令性能: {elapsed:.2f}ms")
    assert elapsed < 50, f"log命令超时: {elapsed}ms > 50ms"

    # 清理
    import shutil
    shutil.rmtree(runs_dir)


def test_large_log_handling():
    """测试处理 10k+ 日志条目"""
    runs_dir = Path("/tmp/frago_perf_test/runs")
    runs_dir.mkdir(parents=True, exist_ok=True)

    # 创建run实例
    manager = RunManager(runs_dir)
    instance = manager.create_run("大规模日志测试")

    run_dir = runs_dir / instance.run_id
    logger = RunLogger(run_dir)

    # 写入 10,000 条日志
    print("写入 10,000 条日志...")
    start_write = time.time()
    for i in range(10000):
        logger.write_log(
            step=f"日志条目 {i+1}",
            status=LogStatus.SUCCESS,
            action_type=ActionType.ANALYSIS,
            execution_method=ExecutionMethod.MANUAL,
            data={"index": i, "data": "test" * 10}  # 每条约100字节
        )

        if (i + 1) % 1000 == 0:
            elapsed = time.time() - start_write
            print(f"  已写入 {i+1} 条，耗时 {elapsed:.2f}s")

    write_time = time.time() - start_write
    print(f"写入总耗时: {write_time:.2f}s")

    # 读取所有日志
    print("读取所有日志...")
    start_read = time.time()
    logs = logger.read_logs()
    read_time = time.time() - start_read

    print(f"读取总耗时: {read_time:.2f}s")
    print(f"日志总数: {len(logs)}")
    assert len(logs) == 10000, f"日志数量不匹配: {len(logs)} != 10000"

    # 统计性能
    print(f"平均写入速度: {10000/write_time:.0f} 条/秒")
    print(f"平均读取速度: {10000/read_time:.0f} 条/秒")

    # 验证日志文件大小
    log_file = run_dir / "logs" / "execution.jsonl"
    file_size = log_file.stat().st_size / 1024 / 1024  # MB
    print(f"日志文件大小: {file_size:.2f} MB")

    # 清理
    import shutil
    shutil.rmtree(runs_dir)


if __name__ == "__main__":
    print("=" * 60)
    print("Run命令系统性能测试")
    print("=" * 60)

    print("\n1. 测试 init 命令性能...")
    test_init_performance()

    print("\n2. 测试 log 命令性能...")
    test_log_performance()

    print("\n3. 测试大规模日志处理...")
    test_large_log_handling()

    print("\n" + "=" * 60)
    print("✅ 所有性能测试通过！")
    print("=" * 60)
