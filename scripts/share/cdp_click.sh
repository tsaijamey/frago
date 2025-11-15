#!/bin/bash
# AuViMa项目 - 自动化视觉管理系统
# 功能: 通过CDP接口点击页面中的指定元素
# 背景: 本脚本是AuViMa项目的一部分，用于自动化控制Chrome浏览器进行网页操作和测试
#      通过CSS选择器定位元素并触发点击事件，实现UI自动化测试
# 用法: ./cdp_click.sh <selector>

SELECTOR="${1}"
PORT="${CDP_PORT:-9222}"

if [ -z "$SELECTOR" ]; then
    echo "用法: $0 <selector>"
    exit 1
fi

JS_CODE="
try {
    const el = document.querySelector('${SELECTOR}');
    if (el) {
        el.click();
        'clicked: ${SELECTOR}';
    } else {
        'not found: ${SELECTOR}';
    }
} catch(e) {
    'error: ' + e.message;
}
"

RESULT=$(curl -s --noproxy '*' -X POST "127.0.0.1:${PORT}/json/runtime/evaluate" \
    -d "{\"expression\": \"${JS_CODE}\"}" \
    -H "Content-Type: application/json" | \
    python3 -c "import sys,json; r=json.load(sys.stdin); print(r.get('result',{}).get('result',{}).get('value',''))" 2>/dev/null)

echo "✓ $RESULT"