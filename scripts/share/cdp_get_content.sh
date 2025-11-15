#!/bin/bash
# AuViMa项目 - 自动化视觉管理系统
# 功能: 获取页面文本内容
# 背景: 本脚本是AuViMa项目的一部分，用于自动化控制Chrome浏览器进行网页操作和测试
#      提取页面或指定元素的文本内容，支持CSS选择器，用于内容验证、数据抓取等场景
# 用法: ./cdp_get_content.sh [selector]

SELECTOR="${1:-body}"
PORT="${CDP_PORT:-9222}"

# 检查CDP是否运行
if ! curl -s --noproxy '*' "127.0.0.1:${PORT}/json/version" > /dev/null 2>&1; then
    echo "✗ CDP未运行" >&2
    echo "请先运行: python src/chrome_cdp_launcher_v2.py" >&2
    exit 1
fi

# 检查websocat是否安装
if ! command -v websocat &> /dev/null; then
    echo "✗ 需要安装 websocat" >&2
    echo "请运行: brew install websocat" >&2
    exit 1
fi

# 获取第一个页面的WebSocket URL
WS_URL=$(curl -s --noproxy '*' "127.0.0.1:${PORT}/json" | jq -r '.[0].webSocketDebuggerUrl // ""')

if [ -z "$WS_URL" ]; then
    echo "✗ 无法获取WebSocket URL" >&2
    exit 1
fi

# 转义选择器中的特殊字符
ESCAPED_SELECTOR=$(echo "$SELECTOR" | sed "s/'/\\\'/g")

# JavaScript获取内容
JS_CODE="(function(){var el=document.querySelector('${ESCAPED_SELECTOR}');if(!el)return 'Error: Element not found';return el.innerText||el.textContent||'';})()"

# 构建CDP命令
CDP_CMD="{\"id\":1,\"method\":\"Runtime.evaluate\",\"params\":{\"expression\":\"${JS_CODE}\",\"returnByValue\":true}}"

# 发送命令
RESULT=$(echo "$CDP_CMD" | websocat -t -n1 "$WS_URL" 2>/dev/null)

if [ -n "$RESULT" ]; then
    # 获取执行结果
    CONTENT=$(echo "$RESULT" | jq -r '.result.result.value // ""')
    
    if [ "$CONTENT" = "Error: Element not found" ]; then
        echo "✗ 找不到元素: $SELECTOR" >&2
        exit 1
    else
        echo "$CONTENT"
    fi
else
    echo "✗ WebSocket通信失败" >&2
    exit 1
fi