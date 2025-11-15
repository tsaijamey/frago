#!/bin/bash
# AuViMa项目 - 自动化视觉管理系统
# 功能: 聚光灯效果 - 突出显示元素，其他区域变暗
# 背景: 本脚本是AuViMa项目的一部分，用于自动化控制Chrome浏览器进行网页操作和测试
#      为指定元素创建聚光灯效果，突出显示目标区域同时将周围区域变暗，用于焦点展示
# 用法: ./cdp_spotlight.sh <selector> [opacity]

SELECTOR="${1}"
OPACITY="${2:-0.8}"  # 遮罩透明度
PORT="${CDP_PORT:-9222}"

if [ -z "$SELECTOR" ]; then
    echo "用法: $0 <selector> [opacity]"
    echo "例如: $0 '#main-content' 0.7"
    exit 1
fi

JS_CODE="
(() => {
    // 移除之前的遮罩
    document.querySelectorAll('.auvima-spotlight').forEach(el => el.remove());
    
    // 获取目标元素
    const element = document.querySelector('${SELECTOR}');
    if (!element) return 'Element not found';
    
    const rect = element.getBoundingClientRect();
    
    // 创建全屏遮罩
    const overlay = document.createElement('div');
    overlay.className = 'auvima-spotlight';
    overlay.style.cssText = \`
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: rgba(0, 0, 0, ${OPACITY});
        pointer-events: none;
        z-index: 99998;
    \`;
    
    // 创建镂空区域（使用box-shadow）
    const spotlight = document.createElement('div');
    spotlight.style.cssText = \`
        position: fixed;
        top: \${rect.top - 10}px;
        left: \${rect.left - 10}px;
        width: \${rect.width + 20}px;
        height: \${rect.height + 20}px;
        box-shadow: 0 0 0 9999px rgba(0, 0, 0, ${OPACITY});
        border-radius: 5px;
        pointer-events: none;
        z-index: 99997;
    \`;
    
    document.body.appendChild(spotlight);
    
    // 滚动到元素
    element.scrollIntoView({behavior: 'smooth', block: 'center'});
    
    return 'Spotlight on: ${SELECTOR}';
})()
"

RESULT=$(curl -s --noproxy '*' -X POST "127.0.0.1:${PORT}/json/runtime/evaluate" \
    -d "{\"expression\": \"${JS_CODE}\"}" \
    -H "Content-Type: application/json" | \
    python3 -c "import sys,json; r=json.load(sys.stdin); print(r.get('result',{}).get('result',{}).get('value',''))" 2>/dev/null)

echo "✓ $RESULT"