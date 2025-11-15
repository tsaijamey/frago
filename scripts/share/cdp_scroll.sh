#!/bin/bash
# AuViMa项目 - 自动化视觉管理系统
# 功能: 滚动页面
# 背景: 本脚本是AuViMa项目的一部分，用于自动化控制Chrome浏览器进行网页操作和测试
#      控制页面垂直滚动，支持向上和向下滚动指定像素距离，用于页面导航和内容展示
# 用法: ./cdp_scroll.sh [pixels] [direction]

PIXELS="${1:-500}"
DIRECTION="${2:-down}"  # up/down
PORT="${CDP_PORT:-9222}"

if [ "$DIRECTION" = "up" ]; then
    PIXELS="-${PIXELS}"
fi

curl -s --noproxy '*' -X POST "127.0.0.1:${PORT}/json/runtime/evaluate" \
    -d "{\"expression\": \"window.scrollBy(0, ${PIXELS}); window.scrollY\"}" \
    -H "Content-Type: application/json" | \
    python3 -c "import sys,json; r=json.load(sys.stdin); pos=r.get('result',{}).get('result',{}).get('value',0); print(f'✓ Scrolled to: {pos}px')" 2>/dev/null