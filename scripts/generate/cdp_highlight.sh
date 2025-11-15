#!/bin/bash
# AuViMa项目 - 自动化视觉管理系统
# 功能: 高亮页面元素
# 背景: 本脚本是AuViMa项目的一部分，用于自动化控制Chrome浏览器进行网页操作和测试
#      为指定元素添加彩色边框高亮效果，支持自定义颜色和边框宽度，用于元素识别和重点展示
# 用法: ./cdp_highlight.sh <selector> [color] [width]

SELECTOR="${1}"
COLOR="${2:-#ff0000}"  # 默认红色
WIDTH="${3:-3}"         # 边框宽度
PORT="${CDP_PORT:-9222}"

if [ -z "$SELECTOR" ]; then
    echo "用法: $0 <selector> [color] [width]"
    echo "例如: $0 '.btn-primary' '#00ff00' 5"
    exit 1
fi

JS_CODE="
(() => {
    // 移除之前的高亮
    document.querySelectorAll('.auvima-highlight').forEach(el => el.remove());
    
    // 获取目标元素
    const elements = document.querySelectorAll('${SELECTOR}');
    let count = 0;
    
    elements.forEach(el => {
        const rect = el.getBoundingClientRect();
        const highlight = document.createElement('div');
        highlight.className = 'auvima-highlight';
        highlight.style.cssText = \`
            position: fixed;
            top: \${rect.top}px;
            left: \${rect.left}px;
            width: \${rect.width}px;
            height: \${rect.height}px;
            border: ${WIDTH}px solid ${COLOR};
            box-shadow: 0 0 10px ${COLOR};
            pointer-events: none;
            z-index: 99999;
            animation: auvima-pulse 1s infinite;
        \`;
        document.body.appendChild(highlight);
        count++;
    });
    
    // 添加动画
    if (!document.getElementById('auvima-styles')) {
        const style = document.createElement('style');
        style.id = 'auvima-styles';
        style.textContent = \`
            @keyframes auvima-pulse {
                0% { opacity: 1; }
                50% { opacity: 0.5; }
                100% { opacity: 1; }
            }
        \`;
        document.head.appendChild(style);
    }
    
    return count + ' elements highlighted';
})()
"

RESULT=$(curl -s --noproxy '*' -X POST "127.0.0.1:${PORT}/json/runtime/evaluate" \
    -d "{\"expression\": \"${JS_CODE}\"}" \
    -H "Content-Type: application/json" | \
    python3 -c "import sys,json; r=json.load(sys.stdin); print(r.get('result',{}).get('result',{}).get('value',''))" 2>/dev/null)

echo "✓ $RESULT"