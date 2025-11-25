#!/bin/bash
# Frago Init 快速测试脚本
# 运行所有可用测试

echo "🧪 Frago Init 快速测试"
echo "======================================"
echo ""

# 检查是否在正确的目录
if [ ! -f "pyproject.toml" ]; then
    echo "❌ 错误：请在项目根目录运行此脚本"
    exit 1
fi

# 测试 1: 单元测试
echo "📝 测试 1: 运行单元测试..."
echo "--------------------------------------"
uv run pytest tests/unit/init/ -v --no-cov
TEST1_EXIT=$?

echo ""
echo ""

# 测试 2: 手动交互测试
echo "🎯 测试 2: 运行交互式数据模型测试..."
echo "--------------------------------------"
uv run python tests/manual_test_models.py
TEST2_EXIT=$?

echo ""
echo ""

# 测试 3: 测试覆盖率
echo "📊 测试 3: 生成测试覆盖率报告..."
echo "--------------------------------------"
uv run pytest tests/unit/init/ --cov=frago.init --cov-report=term
TEST3_EXIT=$?

echo ""
echo ""

# 总结
echo "======================================"
echo "📋 测试总结"
echo "======================================"

if [ $TEST1_EXIT -eq 0 ]; then
    echo "✅ 单元测试: 通过"
else
    echo "❌ 单元测试: 失败"
fi

if [ $TEST2_EXIT -eq 0 ]; then
    echo "✅ 交互测试: 通过"
else
    echo "❌ 交互测试: 失败"
fi

if [ $TEST3_EXIT -eq 0 ]; then
    echo "✅ 覆盖率检查: 通过"
else
    echo "❌ 覆盖率检查: 失败"
fi

echo ""

# 总体结果
if [ $TEST1_EXIT -eq 0 ] && [ $TEST2_EXIT -eq 0 ] && [ $TEST3_EXIT -eq 0 ]; then
    echo "🎉 所有测试通过！"
    echo ""
    echo "📖 查看完整测试指南: tests/TESTING_GUIDE.md"
    echo "🚀 下一步: 继续实施 Phase 3 (依赖检查器和安装器)"
    exit 0
else
    echo "⚠️  部分测试失败，请查看上面的错误信息"
    exit 1
fi
