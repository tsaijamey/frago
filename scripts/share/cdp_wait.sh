#!/bin/bash
# AuViMa项目 - 自动化视觉管理系统
# 功能: 等待元素出现
# 背景: 本脚本是AuViMa项目的一部分，用于自动化控制Chrome浏览器进行网页操作和测试
#      等待指定CSS选择器的元素在页面上出现，支持超时设置，用于同步等待动态加载内容
# 用法: ./cdp_wait.sh <selector> [timeout_seconds]

SELECTOR="${1}"
TIMEOUT="${2:-10}"
PORT="${CDP_PORT:-9222}"

if [ -z "$SELECTOR" ]; then
    echo "用法: $0 <selector> [timeout]"
    exit 1
fi

echo "等待元素: $SELECTOR (最多${TIMEOUT}秒)"

for i in $(seq 1 $TIMEOUT); do
    EXISTS=$(curl -s --noproxy '*' -X POST "127.0.0.1:${PORT}/json/runtime/evaluate" \
        -d "{\"expression\": \"!!document.querySelector('${SELECTOR}')\"}" \
        -H "Content-Type: application/json" | \
        python3 -c "import sys,json; r=json.load(sys.stdin); print(r.get('result',{}).get('result',{}).get('value',False))" 2>/dev/null)
    
    if [ "$EXISTS" = "True" ]; then
        echo "✓ 元素已出现"
        exit 0
    fi
    
    sleep 1
done

echo "✗ 等待超时"
exit 1