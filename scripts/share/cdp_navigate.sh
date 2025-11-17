#!/bin/bash
# AuViMa项目 - 自动化视觉管理系统
# 功能: 通过Chrome DevTools Protocol (CDP)控制浏览器导航到指定URL
# 背景: 本脚本是AuViMa项目的一部分，用于自动化控制Chrome浏览器进行网页操作和测试
#      AuViMa通过CDP协议与Chrome实例通信，实现无头浏览器自动化任务
# 用法: ./cdp_navigate.sh <url> [--wait-for <selector>]

# 检查Python环境
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# 加载Python环境检查
if [ -f "${SCRIPT_DIR}/check_python_env.sh" ]; then
    source "${SCRIPT_DIR}/check_python_env.sh"
    check_python_env || exit $?
fi

# 解析参数
URL=""
WAIT_FOR=""
DEBUG=""
TIMEOUT=""
HOST=""
PORT=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --wait-for)
            WAIT_FOR="$2"
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
            echo "用法: $0 <url> [--wait-for <selector>] [--debug] [--timeout <seconds>] [--host <host>] [--port <port>]"
            exit 1
            ;;
        *)
            if [ -z "$URL" ]; then
                URL="$1"
            else
                echo "错误: 只能指定一个URL"
                echo "用法: $0 <url> [--wait-for <selector>] [--debug] [--timeout <seconds>] [--host <host>] [--port <port>]"
                exit 1
            fi
            shift
            ;;
    esac
done

if [ -z "$URL" ]; then
    echo "错误: 必须提供URL参数"
    echo "用法: $0 <url> [--wait-for <selector>] [--debug] [--timeout <seconds>] [--host <host>] [--port <port>]"
    echo "示例: $0 https://www.google.com"
    echo "示例: $0 https://www.google.com --wait-for '#search' --debug"
    exit 1
fi

# 自动补全URL协议
if [[ ! "$URL" =~ ^https?:// ]]; then
    URL="https://${URL}"
fi

echo "=== Chrome CDP 导航 ==="
echo "目标URL: $URL"
if [ -n "$WAIT_FOR" ]; then
    echo "等待元素: $WAIT_FOR"
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
PYTHON_CMD="${PYTHON_CMD} navigate \"${URL}\""

if [ -n "$WAIT_FOR" ]; then
    PYTHON_CMD="${PYTHON_CMD} --wait-for \"${WAIT_FOR}\""
fi

# 执行Python CLI
cd "$PROJECT_ROOT"
eval "$PYTHON_CMD"