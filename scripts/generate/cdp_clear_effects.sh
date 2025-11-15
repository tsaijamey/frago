#!/bin/bash
# AuViMa项目 - 自动化视觉管理系统
# 功能: 清除所有视觉效果
# 背景: 本脚本是AuViMa项目的一部分，用于自动化控制Chrome浏览器进行网页操作和测试
#      清除页面上所有由AuViMa脚本添加的视觉效果元素，如高亮、标注、聚光灯等
# 用法: ./cdp_clear_effects.sh

PORT="${CDP_PORT:-9222}"

JS_CODE="
(() => {
    // 清除所有AuViMa添加的元素
    const elements = document.querySelectorAll([
        '.auvima-highlight',
        '.auvima-spotlight', 
        '.auvima-annotation',
        '.auvima-pointer',
        '.auvima-overlay',
        '.auvima-focus'
    ].join(','));
    
    let count = elements.length;
    elements.forEach(el => el.remove());
    
    // 清除添加的样式
    const styles = document.querySelectorAll([
        '#auvima-styles',
        '#auvima-annotation-styles',
        '#auvima-pointer-styles'
    ].join(','));
    
    styles.forEach(style => style.remove());
    
    return 'Cleared ' + count + ' effects';
})()
"

RESULT=$(curl -s --noproxy '*' -X POST "127.0.0.1:${PORT}/json/runtime/evaluate" \
    -d "{\"expression\": \"${JS_CODE}\"}" \
    -H "Content-Type: application/json" | \
    python3 -c "import sys,json; r=json.load(sys.stdin); print(r.get('result',{}).get('result',{}).get('value',''))" 2>/dev/null)

echo "✓ $RESULT"