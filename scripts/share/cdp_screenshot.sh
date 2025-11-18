#!/bin/bash
# AuViMa项目 - 自动化视觉管理系统
# 功能: 通过CDP接口截图当前页面
# 背景: 本脚本是AuViMa项目的一部分，用于自动化控制Chrome浏览器进行网页操作和测试
#      提供网页截图功能，支持保存为PNG格式图片，用于文档记录、自动化测试验证等场景
# 用法: ./cdp_screenshot.sh <save_directory> [--debug] [--timeout <seconds>] [--host <host>] [--port <port>]

# 检查Python环境
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# 加载Python环境检查
if [ -f "${SCRIPT_DIR}/check_python_env.sh" ]; then
    source "${SCRIPT_DIR}/check_python_env.sh"
    check_python_env || exit $?
fi

# 解析参数
SAVE_DIR=""
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
            echo "用法: $0 <save_directory> [--debug] [--timeout <seconds>] [--host <host>] [--port <port>]"
            exit 1
            ;;
        *)
            if [ -z "$SAVE_DIR" ]; then
                SAVE_DIR="$1"
            else
                echo "错误: 只能指定一个保存目录"
                echo "用法: $0 <save_directory> [--debug] [--timeout <seconds>] [--host <host>] [--port <port>]"
                exit 1
            fi
            shift
            ;;
    esac
done

if [ -z "$SAVE_DIR" ]; then
    echo "错误: 必须提供保存目录参数"
    echo "该脚本仅用于收集数据/创建分镜/执行录制阶段(收集素材)"
    echo "用法: $0 <save_directory> [--debug] [--timeout <seconds>] [--host <host>] [--port <port>]"
    echo "示例: $0 /path/to/screenshots"
    echo "      $0 /path/to/screenshots --debug --timeout 30"
    exit 1
fi

# 创建保存目录
mkdir -p "${SAVE_DIR}"

echo "=== Chrome CDP 截图 ==="
echo "保存目录: $SAVE_DIR"

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
PYTHON_CMD="${PYTHON_CMD} screenshot \"${SAVE_DIR}\""

# 执行Python CLI
cd "$PROJECT_ROOT"
eval "$PYTHON_CMD"