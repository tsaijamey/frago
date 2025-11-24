#!/bin/bash
# frago目 - 自动化视觉管理系统
# 功能: 验证Python环境和项目依赖
# 背景: 本脚本是Frago项目的一部分，用于确保Python环境正确配置
#      检查Python版本、虚拟环境、项目依赖等，确保CLI命令能正常运行

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

check_python_env() {
    echo "=== 检查Python环境 ==="
    
    # 检查Python是否可用
    if ! command -v python &> /dev/null; then
        echo "✗ Python未安装或不在PATH中"
        echo "请安装Python 3.8+ 或确保python命令可用"
        return 1
    fi
    
    # 检查Python版本
    PYTHON_VERSION=$(python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
    if [ $? -ne 0 ]; then
        echo "✗ 无法获取Python版本信息"
        return 1
    fi
    
    # 检查Python版本是否 >= 3.8
    MAJOR_VERSION=$(echo "$PYTHON_VERSION" | cut -d. -f1)
    MINOR_VERSION=$(echo "$PYTHON_VERSION" | cut -d. -f2)
    
    if [ "$MAJOR_VERSION" -lt 3 ] || ([ "$MAJOR_VERSION" -eq 3 ] && [ "$MINOR_VERSION" -lt 8 ]); then
        echo "✗ Python版本过低: $PYTHON_VERSION"
        echo "需要Python 3.8+，当前版本: $PYTHON_VERSION"
        return 1
    fi
    
    echo "✓ Python版本: $PYTHON_VERSION"
    
    # 检查项目根目录
    if [ ! -d "$PROJECT_ROOT" ]; then
        echo "✗ 项目根目录不存在: $PROJECT_ROOT"
        return 1
    fi
    
    # 检查pyproject.toml
    if [ ! -f "$PROJECT_ROOT/pyproject.toml" ]; then
        echo "✗ pyproject.toml不存在"
        echo "请确保在项目根目录运行脚本"
        return 1
    fi
    
    echo "✓ 项目配置存在"
    
    # 检查frago包是否可导入
    cd "$PROJECT_ROOT"
    if ! python -c "import sys; sys.path.insert(0, 'src'); import frago" 2>/dev/null; then
        echo "✗ 无法导入frago包"
        echo "请确保项目依赖已安装: uv sync"
        return 1
    fi
    
    echo "✓ frago包可导入"
    
    # 检查CLI模块
    if ! python -c "import sys; sys.path.insert(0, 'src'); import frago.cli" 2>/dev/null; then
        echo "✗ 无法导入CLI模块"
        return 1
    fi
    
    echo "✓ CLI模块可导入"
    
    # 检查核心依赖
    if ! python -c "import websocket, click, pydantic" 2>/dev/null; then
        echo "✗ 缺少核心依赖"
        echo "请安装依赖: uv sync"
        return 1
    fi
    
    echo "✓ 核心依赖可用"
    
    echo "=== Python环境检查完成 ==="
    return 0
}

# 如果直接运行此脚本，则执行检查
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    check_python_env
    exit $?
fi