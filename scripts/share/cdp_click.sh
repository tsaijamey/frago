#!/bin/bash
# AuViMa项目 - 自动化视觉管理系统
# 功能: 通过CDP接口点击页面中的指定元素
# 背景: 本脚本是AuViMa项目的一部分，用于自动化控制Chrome浏览器进行网页操作和测试
#      通过CSS选择器定位元素并触发点击事件，实现UI自动化测试
# 用法: ./cdp_click.sh <selector> [--wait-timeout <seconds>] [--debug] [--timeout <seconds>] [--host <host>] [--port <port>]

# 检查Python环境
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# 加载Python环境检查
if [ -f "${SCRIPT_DIR}/check_python_env.sh" ]; then
    source "${SCRIPT_DIR}/check_python_env.sh"
    check_python_env || exit $?
fi

# 解析参数
SELECTOR=""
WAIT_TIMEOUT=""
DEBUG=""
TIMEOUT=""
HOST=""
PORT=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --wait-timeout)
            WAIT_TIMEOUT="--wait-timeout $2"
            shift 2
            ;;
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
            echo "用法: $0 <selector> [--wait-timeout <seconds>] [--debug] [--timeout <seconds>] [--host <host>] [--port <port>]"
            exit 1
            ;;
        *)
            if [ -z "$SELECTOR" ]; then
                SELECTOR="$1"
            else
                echo "错误: 只能指定一个选择器"
                echo "用法: $0 <selector> [--wait-timeout <seconds>] [--debug] [--timeout <seconds>] [--host <host>] [--port <port>]"
                exit 1
            fi
            shift
            ;;
    esac
done

if [ -z "$SELECTOR" ]; then
    echo "错误: 必须提供选择器参数"
    echo "用法: $0 <selector> [--wait-timeout <seconds>] [--debug] [--timeout <seconds>] [--host <host>] [--port <port>]"
    echo "例如: $0 \"button.submit\""
    echo "      $0 \"#login-btn\" --wait-timeout 10 --debug"
    exit 2
fi

echo "=== Chrome CDP 点击 ==="
echo "选择器: $SELECTOR"
if [ -n "$WAIT_TIMEOUT" ]; then
    echo "等待超时: ${WAIT_TIMEOUT#--wait-timeout } 秒"
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
PYTHON_CMD="${PYTHON_CMD} click \"${SELECTOR}\""

if [ -n "$WAIT_TIMEOUT" ]; then
    PYTHON_CMD="${PYTHON_CMD} ${WAIT_TIMEOUT}"
fi

# 执行Python CLI
cd "$PROJECT_ROOT"
eval "$PYTHON_CMD"