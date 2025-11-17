#!/bin/bash
# AuViMa项目 - 自动化视觉管理系统
# 功能: 获取页面或元素的文本内容
# 用法: ./cdp_get_content.sh [selector] [--debug] [--timeout <seconds>] [--host <host>] [--port <port>]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if [ -f "${SCRIPT_DIR}/check_python_env.sh" ]; then
    source "${SCRIPT_DIR}/check_python_env.sh"
    check_python_env || exit $?
fi

SELECTOR="body"
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
        -*)
            echo "错误: 未知选项 $1"
            exit 1
            ;;
        *)
            SELECTOR="$1"
            shift
            ;;
    esac
done

PYTHON_CMD="auvima"
[ -n "$DEBUG" ] && PYTHON_CMD="${PYTHON_CMD} ${DEBUG}"
[ -n "$TIMEOUT" ] && PYTHON_CMD="${PYTHON_CMD} ${TIMEOUT}"
[ -n "$HOST" ] && PYTHON_CMD="${PYTHON_CMD} ${HOST}"
[ -n "$PORT" ] && PYTHON_CMD="${PYTHON_CMD} ${PORT}"
PYTHON_CMD="${PYTHON_CMD} get-content \"${SELECTOR}\""

cd "$PROJECT_ROOT"
eval "$PYTHON_CMD"
