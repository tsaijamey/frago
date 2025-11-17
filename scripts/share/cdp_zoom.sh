#!/bin/bash
# AuViMa项目 - 自动化视觉管理系统
# 功能: 设置页面缩放比例
# 用法: ./cdp_zoom.sh <factor> [--debug] [--timeout <seconds>] [--host <host>] [--port <port>]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if [ -f "${SCRIPT_DIR}/check_python_env.sh" ]; then
    source "${SCRIPT_DIR}/check_python_env.sh"
    check_python_env || exit $?
fi

FACTOR=""
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
            if [ -z "$FACTOR" ]; then
                FACTOR="$1"
            else
                echo "错误: 参数过多"
                exit 1
            fi
            shift
            ;;
    esac
done

if [ -z "$FACTOR" ]; then
    echo "错误: 必须提供缩放比例"
    echo "用法: $0 <factor> [--debug] [--timeout <seconds>] [--host <host>] [--port <port>]"
    echo "例如: $0 1.5  # 放大到150%"
    echo "      $0 0.8  # 缩小到80%"
    exit 2
fi

PYTHON_CMD="auvima"
[ -n "$DEBUG" ] && PYTHON_CMD="${PYTHON_CMD} ${DEBUG}"
[ -n "$TIMEOUT" ] && PYTHON_CMD="${PYTHON_CMD} ${TIMEOUT}"
[ -n "$HOST" ] && PYTHON_CMD="${PYTHON_CMD} ${HOST}"
[ -n "$PORT" ] && PYTHON_CMD="${PYTHON_CMD} ${PORT}"
PYTHON_CMD="${PYTHON_CMD} zoom ${FACTOR}"

cd "$PROJECT_ROOT"
eval "$PYTHON_CMD"
