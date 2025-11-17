#!/bin/bash
# AuViMa项目 - 自动化视觉管理系统
# 功能: 高亮页面元素
# 背景: 本脚本是AuViMa项目的一部分，用于自动化控制Chrome浏览器进行网页操作和测试
#      为指定元素添加彩色边框高亮效果，支持自定义颜色和边框宽度，用于元素识别和重点展示
# 用法: ./cdp_highlight.sh <selector> [color] [width] [--debug] [--timeout <seconds>] [--host <host>] [--port <port>]

# 检查Python环境
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# 加载Python环境检查
if [ -f "${SCRIPT_DIR}/../share/check_python_env.sh" ]; then
    source "${SCRIPT_DIR}/../share/check_python_env.sh"
    check_python_env || exit $?
fi

# 解析参数
SELECTOR=""
COLOR=""
WIDTH=""
DEBUG=""
TIMEOUT=""
HOST=""
PORT=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --debug)
            DEBUG="--debug"
            shift
            ;;
        --timeout)
            TIMEOUT="--timeout $2"
            shift 2
            ;;
        --host)
            HOST="--host $2"
            shift 2
            ;;
        --port)
            PORT="--port $2"
            shift 2
            ;;
        -*)
            echo "错误: 未知选项 $1"
            echo "用法: $0 <selector> [color] [width] [--debug] [--timeout <seconds>] [--host <host>] [--port <port>]"
            exit 1
            ;;
        *)
            if [ -z "$SELECTOR" ]; then
                SELECTOR="$1"
            elif [ -z "$COLOR" ]; then
                COLOR="$1"
            elif [ -z "$WIDTH" ]; then
                WIDTH="$1"
            else
                echo "错误: 参数过多"
                echo "用法: $0 <selector> [color] [width] [--debug] [--timeout <seconds>] [--host <host>] [--port <port>]"
                exit 1
            fi
            shift
            ;;
    esac
done

if [ -z "$SELECTOR" ]; then
    echo "错误: 必须提供选择器参数"
    echo "用法: $0 <selector> [color] [width] [--debug] [--timeout <seconds>] [--host <host>] [--port <port>]"
    echo "例如: $0 '.btn-primary' '#00ff00' 5"
    echo "      $0 '#header' '#0000ff'"
    echo "      $0 'div.content' '#ff0000' 4"
    exit 2
fi

echo "=== Chrome CDP 高亮元素 ==="
echo "选择器: $SELECTOR"
if [ -n "$COLOR" ]; then
    echo "颜色: $COLOR"
fi
if [ -n "$WIDTH" ]; then
    echo "宽度: ${WIDTH}px"
fi

# 构建Python命令 - 全局选项必须在子命令之前
PYTHON_CMD="auvima"

# 添加全局选项（在子命令之前）
if [ -n "$DEBUG" ]; then
    PYTHON_CMD="${PYTHON_CMD} ${DEBUG}"
fi

if [ -n "$TIMEOUT" ]; then
    PYTHON_CMD="${PYTHON_CMD} ${TIMEOUT}"
fi

if [ -n "$HOST" ]; then
    PYTHON_CMD="${PYTHON_CMD} ${HOST}"
fi

if [ -n "$PORT" ]; then
    PYTHON_CMD="${PYTHON_CMD} ${PORT}"
fi

# 添加子命令和参数
PYTHON_CMD="${PYTHON_CMD} highlight \"${SELECTOR}\""

if [ -n "$COLOR" ]; then
    PYTHON_CMD="${PYTHON_CMD} --color \"${COLOR}\""
fi

if [ -n "$WIDTH" ]; then
    PYTHON_CMD="${PYTHON_CMD} --width ${WIDTH}"
fi

# 执行Python CLI
cd "$PROJECT_ROOT"
eval "$PYTHON_CMD"
