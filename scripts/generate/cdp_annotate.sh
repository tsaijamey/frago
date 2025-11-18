#!/bin/bash
# AuViMa项目 - 自动化视觉管理系统
# 功能: 在元素上添加文字标注
# 用法: ./cdp_annotate.sh <selector> <text> [--position top|bottom|left|right] [--debug] [--timeout <seconds>] [--host <host>] [--port <port>]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if [ -f "${SCRIPT_DIR}/../share/check_python_env.sh" ]; then
    source "${SCRIPT_DIR}/../share/check_python_env.sh"
    check_python_env || exit $?
fi

SELECTOR=""
TEXT=""
POSITION=""
DEBUG=""
TIMEOUT=""
HOST=""
PORT=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --position)
            POSITION="--position $2"
            shift 2
            ;;
        --debug) DEBUG="--debug"; shift ;;
        --timeout) TIMEOUT="--timeout $2"; shift 2 ;;
        --host) HOST="--host $2"; shift 2 ;;
        --port) PORT="--port $2"; shift 2 ;;
        -*) echo "错误: 未知选项 $1"; exit 1 ;;
        *)
            if [ -z "$SELECTOR" ]; then
                SELECTOR="$1"
            elif [ -z "$TEXT" ]; then
                TEXT="$1"
            else
                echo "错误: 参数过多"
                exit 1
            fi
            shift
            ;;
    esac
done

if [ -z "$SELECTOR" ] || [ -z "$TEXT" ]; then
    echo "错误: 必须提供选择器和标注文本"
    echo "用法: $0 <selector> <text> [--position top|bottom|left|right] [--debug] [--timeout <seconds>] [--host <host>] [--port <port>]"
    echo "例如: $0 'button' '点击这里' --position top"
    echo "      $0 '#submit' '提交按钮' --position bottom"
    exit 2
fi

PYTHON_CMD="auvima"
[ -n "$DEBUG" ] && PYTHON_CMD="${PYTHON_CMD} ${DEBUG}"
[ -n "$TIMEOUT" ] && PYTHON_CMD="${PYTHON_CMD} ${TIMEOUT}"
[ -n "$HOST" ] && PYTHON_CMD="${PYTHON_CMD} ${HOST}"
[ -n "$PORT" ] && PYTHON_CMD="${PYTHON_CMD} ${PORT}"
PYTHON_CMD="${PYTHON_CMD} annotate \"${SELECTOR}\" \"${TEXT}\""
[ -n "$POSITION" ] && PYTHON_CMD="${PYTHON_CMD} ${POSITION}"

cd "$PROJECT_ROOT"
eval "$PYTHON_CMD"
