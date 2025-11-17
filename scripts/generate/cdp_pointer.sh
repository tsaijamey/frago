#!/bin/bash
# AuViMa项目 - 自动化视觉管理系统
# 功能: 在元素上显示鼠标指针
# 用法: ./cdp_pointer.sh <selector> [--debug] [--timeout <seconds>] [--host <host>] [--port <port>]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if [ -f "${SCRIPT_DIR}/../share/check_python_env.sh" ]; then
    source "${SCRIPT_DIR}/../share/check_python_env.sh"
    check_python_env || exit $?
fi

SELECTOR=""
DEBUG=""
TIMEOUT=""
HOST=""
PORT=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --debug) DEBUG="--debug"; shift ;;
        --timeout) TIMEOUT="--timeout $2"; shift 2 ;;
        --host) HOST="--host $2"; shift 2 ;;
        --port) PORT="--port $2"; shift 2 ;;
        -*) echo "错误: 未知选项 $1"; exit 1 ;;
        *)
            if [ -z "$SELECTOR" ]; then
                SELECTOR="$1"
            else
                echo "错误: 参数过多"
                exit 1
            fi
            shift
            ;;
    esac
done

if [ -z "$SELECTOR" ]; then
    echo "错误: 必须提供选择器参数"
    echo "用法: $0 <selector> [--debug] [--timeout <seconds>] [--host <host>] [--port <port>]"
    exit 2
fi

PYTHON_CMD="auvima"
[ -n "$DEBUG" ] && PYTHON_CMD="${PYTHON_CMD} ${DEBUG}"
[ -n "$TIMEOUT" ] && PYTHON_CMD="${PYTHON_CMD} ${TIMEOUT}"
[ -n "$HOST" ] && PYTHON_CMD="${PYTHON_CMD} ${HOST}"
[ -n "$PORT" ] && PYTHON_CMD="${PYTHON_CMD} ${PORT}"
PYTHON_CMD="${PYTHON_CMD} pointer \"${SELECTOR}\""

cd "$PROJECT_ROOT"
eval "$PYTHON_CMD"
