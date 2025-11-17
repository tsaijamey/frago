#!/bin/bash
# CDP通用函数库
# 用途：提供CDP脚本的共享函数
# 日期：2025-11-15

# 设置严格模式
set -euo pipefail

# 加载环境配置（如果存在）
if [ -f "${HOME}/Repos/AuViMa/.env.cdp" ]; then
    source "${HOME}/Repos/AuViMa/.env.cdp"
fi

# 默认配置
: ${CDP_PORT:=9222}
: ${CDP_HOST:=127.0.0.1}
: ${DEBUG:=0}

# 代理配置（优先级：命令行参数 > 环境变量 > 无代理）
: ${CDP_PROXY_HOST:=""}
: ${CDP_PROXY_PORT:=""}
: ${CDP_PROXY_USERNAME:=""}
: ${CDP_PROXY_PASSWORD:=""}
: ${CDP_NO_PROXY:=0}

# ========================================
# 辅助函数
# ========================================

# 调试日志输出
debug_log() {
    if [ "$DEBUG" = "1" ]; then
        echo "[DEBUG] $*" >&2
    fi
}

# ========================================
# T047: 代理参数处理函数
# ========================================

# 从环境变量加载代理配置
load_proxy_from_env() {
    # 如果已经通过CDP_*变量配置，或者禁用了代理，直接返回
    if [ "$CDP_NO_PROXY" = "1" ]; then
        debug_log "代理已禁用 (CDP_NO_PROXY=1)"
        return 0
    fi

    if [ -n "$CDP_PROXY_HOST" ] && [ -n "$CDP_PROXY_PORT" ]; then
        debug_log "使用CDP_PROXY配置"
        return 0
    fi

    # 尝试从HTTP_PROXY/HTTPS_PROXY解析
    local proxy_url="${HTTPS_PROXY:-${https_proxy:-${HTTP_PROXY:-${http_proxy:-}}}}"

    if [ -n "$proxy_url" ]; then
        debug_log "从环境变量解析代理: $proxy_url"

        # 去除协议前缀
        proxy_url="${proxy_url#http://}"
        proxy_url="${proxy_url#https://}"

        # 提取认证信息（如果存在）
        if [[ "$proxy_url" == *"@"* ]]; then
            local auth_part="${proxy_url%%@*}"
            proxy_url="${proxy_url#*@}"

            CDP_PROXY_USERNAME="${auth_part%%:*}"
            CDP_PROXY_PASSWORD="${auth_part#*:}"
        fi

        # 提取主机和端口
        CDP_PROXY_HOST="${proxy_url%%:*}"
        CDP_PROXY_PORT="${proxy_url#*:}"

        # 如果端口包含路径，去掉路径
        CDP_PROXY_PORT="${CDP_PROXY_PORT%%/*}"

        debug_log "解析结果 - Host: $CDP_PROXY_HOST, Port: $CDP_PROXY_PORT"
    fi

    # 检查NO_PROXY环境变量
    local no_proxy_env="${NO_PROXY:-${no_proxy:-}}"
    if [ -n "$no_proxy_env" ]; then
        # 检查CDP_HOST是否在NO_PROXY列表中
        if echo "$no_proxy_env" | grep -qE "(^|,)(${CDP_HOST}|\*)(,|$)"; then
            CDP_NO_PROXY=1
            debug_log "CDP主机在NO_PROXY列表中，禁用代理"
        fi
    fi
}

# 构建Python CLI的代理参数
build_proxy_args() {
    local proxy_args=""

    # 如果禁用代理
    if [ "$CDP_NO_PROXY" = "1" ]; then
        proxy_args="--no-proxy"
        debug_log "代理参数: $proxy_args"
        echo "$proxy_args"
        return 0
    fi

    # 如果配置了代理
    if [ -n "$CDP_PROXY_HOST" ] && [ -n "$CDP_PROXY_PORT" ]; then
        proxy_args="--proxy-host '$CDP_PROXY_HOST' --proxy-port $CDP_PROXY_PORT"

        # 添加认证信息（如果存在）
        if [ -n "$CDP_PROXY_USERNAME" ] && [ -n "$CDP_PROXY_PASSWORD" ]; then
            proxy_args="$proxy_args --proxy-username '$CDP_PROXY_USERNAME' --proxy-password '$CDP_PROXY_PASSWORD'"
        fi

        debug_log "代理参数: $proxy_args"
    fi

    echo "$proxy_args"
}

# 初始化：自动从环境变量加载代理配置
load_proxy_from_env

# 错误输出
error_log() {
    echo "✗ $*" >&2
}

# 成功输出
success_log() {
    echo "✓ $*"
}

# 信息输出
info_log() {
    echo "ℹ $*"
}

# ========================================
# T007: CDP环境检查函数
# ========================================
check_cdp_environment() {
    local port="${1:-$CDP_PORT}"
    local host="${2:-$CDP_HOST}"
    
    debug_log "检查CDP环境 - Host: $host, Port: $port"
    
    # 检查websocat是否安装
    if ! command -v websocat &> /dev/null; then
        error_log "websocat未安装。请运行: brew install websocat"
        return 4
    fi
    
    # 检查CDP服务是否运行
    if ! curl -s --noproxy '*' "http://${host}:${port}/json/version" > /dev/null 2>&1; then
        error_log "CDP服务未在 ${host}:${port} 运行"
        info_log "启动Chrome with CDP: google-chrome --remote-debugging-port=${port}"
        return 3
    fi
    
    debug_log "CDP环境检查通过"
    return 0
}

# ========================================
# T008: WebSocket URL获取函数
# ========================================
get_websocket_url() {
    local port="${1:-$CDP_PORT}"
    local host="${2:-$CDP_HOST}"
    local target_id="${3:-}"
    
    debug_log "获取WebSocket URL - Host: $host, Port: $port"
    
    # 获取页面列表
    local pages_json=$(curl -s --noproxy '*' "http://${host}:${port}/json" 2>/dev/null)
    
    if [ -z "$pages_json" ]; then
        error_log "无法获取CDP页面列表"
        return 1
    fi
    
    # 提取WebSocket URL - 优先使用jq，回退到grep
    local ws_url
    
    if command -v jq &> /dev/null; then
        # 使用jq提取（推荐）
        if [ -n "$target_id" ]; then
            ws_url=$(echo "$pages_json" | jq -r ".[] | select(.id==\"${target_id}\") | .webSocketDebuggerUrl // empty" 2>/dev/null | head -1)
        else
            ws_url=$(echo "$pages_json" | jq -r '.[0].webSocketDebuggerUrl // empty' 2>/dev/null)
        fi
    else
        # 回退到grep方法
        ws_url=$(echo "$pages_json" | grep -o '"webSocketDebuggerUrl":[[:space:]]*"ws://[^"]*"' | sed 's/.*"ws/ws/' | sed 's/".*//' | head -1)
    fi
    
    if [ -z "$ws_url" ]; then
        error_log "无法获取WebSocket URL"
        return 1
    fi
    
    debug_log "WebSocket URL: $ws_url"
    echo "$ws_url"
    return 0
}

# ========================================
# T009: 标准错误处理函数
# ========================================
handle_error() {
    local exit_code=$1
    local error_msg="${2:-未知错误}"
    local script_name="${3:-${0##*/}}"
    
    case $exit_code in
        0) return 0 ;;
        1) error_log "[$script_name] 一般错误: $error_msg" ;;
        2) error_log "[$script_name] 参数错误: $error_msg" ;;
        3) error_log "[$script_name] 环境错误: CDP未运行" ;;
        4) error_log "[$script_name] 工具缺失: websocat未安装" ;;
        127) error_log "[$script_name] 命令未找到: $error_msg" ;;
        *) error_log "[$script_name] 错误 ($exit_code): $error_msg" ;;
    esac
    
    return $exit_code
}

# 设置错误陷阱
setup_error_trap() {
    trap 'handle_error $? "脚本意外退出" "${BASH_SOURCE[0]##*/}"' ERR
}

# ========================================
# T010: JSON响应解析函数
# ========================================

# 使用jq解析JSON（如果可用）
parse_json_with_jq() {
    local json="$1"
    local query="$2"
    
    if command -v jq &> /dev/null; then
        echo "$json" | jq -r "$query" 2>/dev/null
        return $?
    fi
    return 1
}

# 使用awk作为后备方案解析简单JSON
parse_json_with_awk() {
    local json="$1"
    local key="$2"
    
    # 提取简单的键值对
    echo "$json" | awk -F"\"${key}\":" '{print $2}' | awk -F'[,}]' '{gsub(/^[ \t]*"|"[ \t]*$/, "", $1); print $1}'
}

# 通用JSON解析函数
parse_json() {
    local json="$1"
    local query="$2"
    
    debug_log "解析JSON - Query: $query"
    
    # 优先使用jq
    if command -v jq &> /dev/null; then
        debug_log "使用jq解析"
        parse_json_with_jq "$json" "$query"
    else
        debug_log "使用awk解析（功能有限）"
        # 将jq查询转换为简单键名
        local key=$(echo "$query" | sed 's/^\.//' | sed 's/\[.*\]//')
        parse_json_with_awk "$json" "$key"
    fi
}

# 检查CDP响应是否包含错误
check_cdp_response() {
    local response="$1"
    
    # 检查是否有错误字段
    if echo "$response" | grep -q '"error"'; then
        local error_msg=$(parse_json "$response" '.error.message')
        error_log "CDP错误: $error_msg"
        return 1
    fi
    
    # 检查是否有结果
    if echo "$response" | grep -q '"result"'; then
        debug_log "CDP响应成功"
        return 0
    fi
    
    # 既无错误也无结果，可能是格式问题
    debug_log "CDP响应格式未知"
    return 2
}

# ========================================
# CDP命令执行函数
# ========================================
execute_cdp_command() {
    local method="$1"
    local params="${2:-{}}"
    local ws_url="${3:-}"
    
    # 如果没有提供WebSocket URL，获取一个
    if [ -z "$ws_url" ]; then
        ws_url=$(get_websocket_url) || return $?
    fi
    
    # 构建CDP命令（使用单行JSON格式）
    local cmd_id=${CDP_CMD_ID:-1}
    local cmd_json
    cmd_json=$(printf '{"id": %d, "method": "%s", "params": %s}' "$cmd_id" "$method" "$params")
    
    debug_log "执行CDP命令: $method"
    debug_log "命令JSON: $cmd_json"
    
    # 发送命令并获取响应
    local response=$(echo "$cmd_json" | websocat -t -n1 "$ws_url" 2>/dev/null)
    
    debug_log "CDP响应: $response"
    
    # 检查响应
    if check_cdp_response "$response"; then
        echo "$response"
        return 0
    else
        return 1
    fi
}

# ========================================
# 导出函数供其他脚本使用
# ========================================
export -f debug_log
export -f error_log
export -f success_log
export -f info_log
export -f load_proxy_from_env
export -f build_proxy_args
export -f check_cdp_environment
export -f get_websocket_url
export -f handle_error
export -f setup_error_trap
export -f parse_json
export -f parse_json_with_jq
export -f parse_json_with_awk
export -f check_cdp_response
export -f execute_cdp_command

# 如果直接运行此脚本，显示可用函数
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    echo "CDP通用函数库已加载"
    echo ""
    echo "可用函数："
    echo "  - check_cdp_environment: 检查CDP环境"
    echo "  - get_websocket_url: 获取WebSocket连接URL"
    echo "  - handle_error: 标准错误处理"
    echo "  - parse_json: 解析JSON响应"
    echo "  - execute_cdp_command: 执行CDP命令"
    echo "  - load_proxy_from_env: 从环境变量加载代理配置"
    echo "  - build_proxy_args: 构建Python CLI的代理参数"
    echo ""
    echo "代理配置环境变量："
    echo "  - CDP_PROXY_HOST: 代理主机地址"
    echo "  - CDP_PROXY_PORT: 代理端口"
    echo "  - CDP_PROXY_USERNAME: 代理认证用户名"
    echo "  - CDP_PROXY_PASSWORD: 代理认证密码"
    echo "  - CDP_NO_PROXY: 禁用代理 (1=禁用)"
    echo "  - HTTP_PROXY/HTTPS_PROXY: 标准代理环境变量"
    echo "  - NO_PROXY: 不使用代理的主机列表"
    echo ""
    echo "使用方法："
    echo "  source $(realpath "${BASH_SOURCE[0]}")"
fi