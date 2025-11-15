#!/bin/bash
# AuViMa项目 - 自动化视觉管理系统
# 功能: 给指定元素添加边框高亮
# 背景: 本脚本是AuViMa项目的一部分，用于自动化控制Chrome浏览器进行网页操作和测试
#      通过给元素加边框来标注"当前看这里"的位置，用于界面说明和用户指导
# 用法: ./cdp_annotate.sh <selector>

SELECTOR="${1}"
PORT="${CDP_PORT:-9222}"

if [ -z "$SELECTOR" ]; then
    echo "错误: 必须提供CSS选择器"
    echo "用法: $0 <selector>"
    echo "示例: $0 'button'"
    echo "示例: $0 '.class-name'"
    echo "示例: $0 '#id'"
    exit 1
fi

echo "=== Chrome CDP 高亮元素 ==="
echo "端口: $PORT"
echo "选择器: $SELECTOR"

# 检查CDP是否运行
if ! curl -s --noproxy '*' "127.0.0.1:${PORT}/json/version" > /dev/null 2>&1; then
    echo "✗ CDP未运行"
    echo "请先运行: python src/chrome_cdp_launcher_v2.py"
    exit 1
fi

# 检查websocat是否安装
if ! command -v websocat &> /dev/null; then
    echo "✗ 需要安装 websocat"
    echo "请运行: brew install websocat"
    exit 1
fi

# 获取第一个页面的WebSocket URL
WS_URL=$(curl -s --noproxy '*' "127.0.0.1:${PORT}/json" | jq -r '.[0].webSocketDebuggerUrl // ""')

if [ -z "$WS_URL" ]; then
    echo "✗ 无法获取WebSocket URL"
    exit 1
fi

# 转义选择器中的特殊字符
ESCAPED_SELECTOR=$(echo "$SELECTOR" | sed "s/'/\\\'/g")

# 简单的JavaScript：给元素加2px红色边框
JS_CODE="(function(){var el=document.querySelector('${ESCAPED_SELECTOR}');if(!el)return 'Error: Element not found';el.style.border='2px solid red';return 'Success';})()"

# 构建CDP命令
CDP_CMD="{\"id\":1,\"method\":\"Runtime.evaluate\",\"params\":{\"expression\":\"${JS_CODE}\",\"returnByValue\":true}}"

# 发送命令
RESULT=$(echo "$CDP_CMD" | websocat -t -n1 "$WS_URL" 2>/dev/null)

if [ -n "$RESULT" ]; then
    # 获取执行结果
    EVAL_RESULT=$(echo "$RESULT" | jq -r '.result.result.value // ""')
    
    if [ "$EVAL_RESULT" = "Success" ]; then
        echo "✓ 元素已高亮: $SELECTOR"
    elif [ "$EVAL_RESULT" = "Error: Element not found" ]; then
        echo "✗ 找不到元素: $SELECTOR"
        exit 1
    else
        echo "✗ 执行失败"
        exit 1
    fi
else
    echo "✗ WebSocket通信失败"
    exit 1
fi