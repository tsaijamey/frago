#!/bin/bash
# AuViMa项目 - 自动化视觉管理系统
# 功能: 通过Chrome DevTools Protocol (CDP)控制浏览器导航到指定URL
# 背景: 本脚本是AuViMa项目的一部分，用于自动化控制Chrome浏览器进行网页操作和测试
#      AuViMa通过CDP协议与Chrome实例通信，实现无头浏览器自动化任务
# 用法: ./cdp_navigate.sh <url>

if [ -z "$1" ]; then
    echo "错误: 必须提供URL参数"
    echo "用法: $0 <url>"
    echo "示例: $0 https://www.google.com"
    exit 1
fi

URL="$1"
PORT="${CDP_PORT:-9222}"

# 自动补全URL协议
if [[ ! "$URL" =~ ^https?:// ]]; then
    URL="https://${URL}"
fi

echo "=== Chrome CDP 导航 ==="
echo "端口: $PORT"
echo "目标URL: $URL"

# 检查CDP是否运行
if ! curl -s --noproxy '*' "127.0.0.1:${PORT}/json/version" > /dev/null 2>&1; then
    echo "✗ CDP未运行"
    echo "请先运行: python src/chrome_cdp_launcher_v2.py"
    exit 1
fi

# 检查websocat是否安装
if ! command -v websocat &> /dev/null; then
    echo "✗ 导航需要安装 websocat"
    echo "请运行: brew install websocat"
    exit 1
fi

# 获取第一个页面的WebSocket URL
PAGE_INFO=$(curl -s --noproxy '*' "127.0.0.1:${PORT}/json" | jq -c '.[0] | select(.type == "page")')

if [ -z "$PAGE_INFO" ]; then
    echo "创建新页面..."
    curl -s --noproxy '*' -X PUT "127.0.0.1:${PORT}/json/new" > /dev/null 2>&1
    sleep 1
    PAGE_INFO=$(curl -s --noproxy '*' "127.0.0.1:${PORT}/json" | jq -c '.[0] | select(.type == "page")')
fi

WS_URL=$(echo "$PAGE_INFO" | jq -r '.webSocketDebuggerUrl // ""')
CURRENT_URL=$(echo "$PAGE_INFO" | jq -r '.url // ""')

if [ -z "$WS_URL" ]; then
    echo "✗ 无法获取WebSocket URL"
    exit 1
fi

echo "当前页面: $CURRENT_URL"
echo "导航中..."

# 使用CDP Page.navigate方法进行导航
NAVIGATE_CMD="{\"id\":1,\"method\":\"Page.navigate\",\"params\":{\"url\":\"${URL}\"}}"
RESULT=$(echo "$NAVIGATE_CMD" | websocat -t -n1 "$WS_URL" 2>/dev/null)

if [ -n "$RESULT" ]; then
    # 检查是否有错误
    ERROR=$(echo "$RESULT" | jq -r '.error.message // ""')
    if [ -n "$ERROR" ] && [ "$ERROR" != "" ]; then
        echo "✗ 导航失败: $ERROR"
        exit 1
    fi
    
    # 获取frame ID
    FRAME_ID=$(echo "$RESULT" | jq -r '.result.frameId // ""')
    if [ -n "$FRAME_ID" ] && [ "$FRAME_ID" != "" ]; then
        echo "✓ 导航成功"
        echo "Frame ID: $FRAME_ID"
        
        # 等待页面加载
        echo "等待页面加载..."
        sleep 2
        
        # 获取更新后的页面信息
        UPDATED_INFO=$(curl -s --noproxy '*' "127.0.0.1:${PORT}/json" | jq -c '.[0] | select(.type == "page")')
        NEW_URL=$(echo "$UPDATED_INFO" | jq -r '.url // ""')
        NEW_TITLE=$(echo "$UPDATED_INFO" | jq -r '.title // ""')
        
        echo "当前URL: $NEW_URL"
        echo "页面标题: $NEW_TITLE"
    else
        echo "✓ 导航命令已发送"
    fi
else
    echo "✗ WebSocket通信失败"
    exit 1
fi