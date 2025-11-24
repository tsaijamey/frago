#!/bin/bash
# 代理配置测试脚本
# 用途：测试代理参数的正确传递和使用
# 日期：2025-11-18

set -euo pipefail

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# 加载CDP通用函数
source "$PROJECT_ROOT/scripts/share/cdp_common.sh"

# 测试计数器
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

# ========================================
# 测试辅助函数
# ========================================

test_header() {
    echo ""
    echo "========================================="
    echo "测试: $1"
    echo "========================================="
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
}

test_pass() {
    echo "✓ 通过: $1"
    PASSED_TESTS=$((PASSED_TESTS + 1))
}

test_fail() {
    echo "✗ 失败: $1"
    echo "  原因: $2"
    FAILED_TESTS=$((FAILED_TESTS + 1))
}

# ========================================
# 测试1: 环境变量代理配置解析
# ========================================
test_env_proxy_parsing() {
    test_header "环境变量代理配置解析"

    # 保存原始环境变量
    local orig_http_proxy="${HTTP_PROXY:-}"
    local orig_https_proxy="${HTTPS_PROXY:-}"
    local orig_no_proxy="${NO_PROXY:-}"

    # 测试用例1: 简单HTTP代理
    export HTTP_PROXY="http://proxy.example.com:8080"
    unset HTTPS_PROXY NO_PROXY
    unset CDP_PROXY_HOST CDP_PROXY_PORT CDP_NO_PROXY

    load_proxy_from_env

    if [ "$CDP_PROXY_HOST" = "proxy.example.com" ] && [ "$CDP_PROXY_PORT" = "8080" ]; then
        test_pass "简单HTTP代理解析"
    else
        test_fail "简单HTTP代理解析" "Host: $CDP_PROXY_HOST, Port: $CDP_PROXY_PORT"
    fi

    # 测试用例2: 带认证的HTTPS代理
    export HTTPS_PROXY="http://user:pass@proxy.example.com:3128"
    unset HTTP_PROXY NO_PROXY
    unset CDP_PROXY_HOST CDP_PROXY_PORT CDP_PROXY_USERNAME CDP_PROXY_PASSWORD CDP_NO_PROXY

    load_proxy_from_env

    if [ "$CDP_PROXY_HOST" = "proxy.example.com" ] && \
       [ "$CDP_PROXY_PORT" = "3128" ] && \
       [ "$CDP_PROXY_USERNAME" = "user" ] && \
       [ "$CDP_PROXY_PASSWORD" = "pass" ]; then
        test_pass "带认证的HTTPS代理解析"
    else
        test_fail "带认证的HTTPS代理解析" "Host: $CDP_PROXY_HOST, Port: $CDP_PROXY_PORT, User: $CDP_PROXY_USERNAME"
    fi

    # 测试用例3: NO_PROXY环境变量
    export HTTP_PROXY="http://proxy.example.com:8080"
    export NO_PROXY="localhost,127.0.0.1"
    unset CDP_PROXY_HOST CDP_PROXY_PORT CDP_NO_PROXY
    CDP_HOST="127.0.0.1"

    load_proxy_from_env

    if [ "$CDP_NO_PROXY" = "1" ]; then
        test_pass "NO_PROXY环境变量匹配"
    else
        test_fail "NO_PROXY环境变量匹配" "CDP_NO_PROXY=$CDP_NO_PROXY"
    fi

    # 恢复原始环境变量
    if [ -n "$orig_http_proxy" ]; then
        export HTTP_PROXY="$orig_http_proxy"
    else
        unset HTTP_PROXY 2>/dev/null || true
    fi

    if [ -n "$orig_https_proxy" ]; then
        export HTTPS_PROXY="$orig_https_proxy"
    else
        unset HTTPS_PROXY 2>/dev/null || true
    fi

    if [ -n "$orig_no_proxy" ]; then
        export NO_PROXY="$orig_no_proxy"
    else
        unset NO_PROXY 2>/dev/null || true
    fi
}

# ========================================
# 测试2: 代理参数构建
# ========================================
test_proxy_args_building() {
    test_header "代理参数构建"

    # 测试用例1: 无代理配置
    unset CDP_PROXY_HOST CDP_PROXY_PORT CDP_PROXY_USERNAME CDP_PROXY_PASSWORD
    CDP_NO_PROXY=0

    local args=$(build_proxy_args)
    if [ -z "$args" ]; then
        test_pass "无代理配置时返回空字符串"
    else
        test_fail "无代理配置时返回空字符串" "返回: $args"
    fi

    # 测试用例2: 禁用代理
    CDP_NO_PROXY=1

    local args=$(build_proxy_args)
    if echo "$args" | grep -q "\-\-no-proxy"; then
        test_pass "禁用代理时返回--no-proxy参数"
    else
        test_fail "禁用代理时返回--no-proxy参数" "返回: $args"
    fi

    # 测试用例3: 简单代理配置
    CDP_PROXY_HOST="proxy.example.com"
    CDP_PROXY_PORT="8080"
    unset CDP_PROXY_USERNAME CDP_PROXY_PASSWORD
    CDP_NO_PROXY=0

    local args=$(build_proxy_args)
    if echo "$args" | grep -q "\-\-proxy-host" && echo "$args" | grep -q "\-\-proxy-port"; then
        test_pass "简单代理配置参数构建"
    else
        test_fail "简单代理配置参数构建" "返回: $args"
    fi

    # 测试用例4: 带认证的代理配置
    CDP_PROXY_HOST="proxy.example.com"
    CDP_PROXY_PORT="8080"
    CDP_PROXY_USERNAME="user"
    CDP_PROXY_PASSWORD="pass"
    CDP_NO_PROXY=0

    local args=$(build_proxy_args)
    if echo "$args" | grep -q "\-\-proxy-username" && echo "$args" | grep -q "\-\-proxy-password"; then
        test_pass "带认证的代理配置参数构建"
    else
        test_fail "带认证的代理配置参数构建" "返回: $args"
    fi
}

# ========================================
# 测试3: Python配置验证（如果Python可用）
# ========================================
test_python_config_validation() {
    test_header "Python配置验证"

    # 检查Python是否可用
    if ! command -v python3 &> /dev/null; then
        echo "⊘ 跳过: Python3未安装"
        return 0
    fi

    # 检查frago包是否可用
    if ! python3 -c "import frago" 2>/dev/null; then
        echo "⊘ 跳过: frago包未安装"
        return 0
    fi

    # 测试用例1: 验证代理配置类
    local test_script="
from frago.cdp.config import CDPConfig

# 测试简单代理配置
config = CDPConfig(
    proxy_host='proxy.example.com',
    proxy_port=8080
)

is_valid, error = config.validate_proxy_config()
assert is_valid, f'验证失败: {error}'
print('简单代理配置验证通过')

# 测试无效端口
config = CDPConfig(
    proxy_host='proxy.example.com',
    proxy_port=99999
)

is_valid, error = config.validate_proxy_config()
assert not is_valid, '应该验证失败'
assert '端口无效' in error, f'错误信息不正确: {error}'
print('无效端口验证通过')

# 测试认证配置不完整
config = CDPConfig(
    proxy_host='proxy.example.com',
    proxy_port=8080,
    proxy_username='user'
)

is_valid, error = config.validate_proxy_config()
assert not is_valid, '应该验证失败'
assert '同时指定' in error, f'错误信息不正确: {error}'
print('认证配置验证通过')
"

    if python3 -c "$test_script" 2>&1; then
        test_pass "Python代理配置验证"
    else
        test_fail "Python代理配置验证" "执行失败"
    fi
}

# ========================================
# 运行所有测试
# ========================================

echo "========================================="
echo "代理配置测试套件"
echo "========================================="

test_env_proxy_parsing
test_proxy_args_building
test_python_config_validation

# ========================================
# 测试总结
# ========================================

echo ""
echo "========================================="
echo "测试总结"
echo "========================================="
echo "总测试数: $TOTAL_TESTS"
echo "通过: $PASSED_TESTS"
echo "失败: $FAILED_TESTS"
echo "========================================="

if [ $FAILED_TESTS -gt 0 ]; then
    echo "✗ 测试未全部通过"
    exit 1
else
    echo "✓ 所有测试通过"
    exit 0
fi
