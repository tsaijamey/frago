#!/bin/bash
# AuViMa项目 - 自动化视觉管理系统
# 功能: 通过CDP接口执行JavaScript代码
# 背景: 本脚本是AuViMa项目的一部分，用于自动化控制Chrome浏览器进行网页操作和测试
#      在当前页面上下文中执行自定义JavaScript代码，提供灵活的页面操作和数据获取能力
# 用法: ./cdp_exec_js.sh "<javascript_code>" [--debug] [--timeout <seconds>] [--host <host>] [--port <port>]

# 检查Python环境
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# 加载Python环境检查
if [ -f "${SCRIPT_DIR}/check_python_env.sh" ]; then
    source "${SCRIPT_DIR}/check_python_env.sh"
    check_python_env || exit $?
fi

# 解析参数
JS_CODE=""
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
            echo "用法: $0 \"<javascript_code>\" [--debug] [--timeout <seconds>] [--host <host>] [--port <port>]"
            exit 1
            ;;
        *)
            if [ -z "$JS_CODE" ]; then
                JS_CODE="$1"
            else
                echo "错误: 只能指定一个JavaScript代码"
                echo "用法: $0 \"<javascript_code>\" [--debug] [--timeout <seconds>] [--host <host>] [--port <port>]"
                exit 1
            fi
            shift
            ;;
    esac
done

if [ -z "$JS_CODE" ]; then
    echo "错误: 必须提供JavaScript代码参数"
    echo "用法: $0 \"<javascript_code>\" [--debug] [--timeout <seconds>] [--host <host>] [--port <port>]"
    echo "例如: $0 \"document.body.style.backgroundColor='red'\""
    echo "      $0 \"document.title\""
    echo "      $0 \"window.location.href\" --debug --timeout 10"
    exit 2
fi

echo "=== Chrome CDP 执行JavaScript ==="
echo "代码: ${JS_CODE:0:100}..."

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
PYTHON_CMD="${PYTHON_CMD} exec-js \"${JS_CODE}\""

# 执行Python CLI
cd "$PROJECT_ROOT"
eval "$PYTHON_CMD"