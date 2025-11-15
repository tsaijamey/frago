#!/bin/bash
# AuViMa项目 - 自动化视觉管理系统
# 功能: 缩放到特定元素（适合展示代码或细节）
# 背景: 本脚本是AuViMa项目的一部分，用于自动化控制Chrome浏览器进行网页操作和测试
#      将指定元素放大显示在全屏模式下，支持自定义缩放比例，用于代码展示和细节查看
# 用法: ./cdp_zoom.sh <selector> [scale]

SELECTOR="${1}"
SCALE="${2:-1.5}"  # 缩放比例
PORT="${CDP_PORT:-9222}"

if [ -z "$SELECTOR" ]; then
    echo "用法: $0 <selector> [scale]"
    echo "例如: $0 'pre.code-block' 2"
    exit 1
fi

JS_CODE="
(() => {
    const element = document.querySelector('${SELECTOR}');
    if (!element) return 'Element not found';
    
    const rect = element.getBoundingClientRect();
    
    // 创建缩放容器
    const zoomContainer = document.createElement('div');
    zoomContainer.className = 'auvima-zoom';
    zoomContainer.style.cssText = \`
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: rgba(255,255,255,0.95);
        z-index: 99999;
        display: flex;
        align-items: center;
        justify-content: center;
        animation: auvima-fadein 0.3s ease-out;
    \`;
    
    // 克隆并缩放元素
    const cloned = element.cloneNode(true);
    cloned.style.cssText = \`
        transform: scale(${SCALE});
        transform-origin: center;
        max-width: 90vw;
        max-height: 90vh;
        overflow: auto;
        box-shadow: 0 10px 40px rgba(0,0,0,0.2);
        background: white;
        padding: 20px;
        border-radius: 10px;
    \`;
    
    zoomContainer.appendChild(cloned);
    document.body.appendChild(zoomContainer);
    
    // 添加关闭提示
    const closeHint = document.createElement('div');
    closeHint.textContent = 'ESC to close';
    closeHint.style.cssText = \`
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 10px 20px;
        background: #333;
        color: white;
        border-radius: 5px;
        font-size: 14px;
        z-index: 100000;
    \`;
    zoomContainer.appendChild(closeHint);
    
    // ESC键关闭
    const closeHandler = (e) => {
        if (e.key === 'Escape') {
            zoomContainer.remove();
            document.removeEventListener('keydown', closeHandler);
        }
    };
    document.addEventListener('keydown', closeHandler);
    
    // 添加动画
    if (!document.getElementById('auvima-zoom-styles')) {
        const style = document.createElement('style');
        style.id = 'auvima-zoom-styles';
        style.textContent = \`
            @keyframes auvima-fadein {
                from { opacity: 0; }
                to { opacity: 1; }
            }
        \`;
        document.head.appendChild(style);
    }
    
    return 'Zoomed to: ${SELECTOR} (${SCALE}x)';
})()
"

RESULT=$(curl -s --noproxy '*' -X POST "127.0.0.1:${PORT}/json/runtime/evaluate" \
    -d "{\"expression\": \"${JS_CODE}\"}" \
    -H "Content-Type: application/json" | \
    python3 -c "import sys,json; r=json.load(sys.stdin); print(r.get('result',{}).get('result',{}).get('value',''))" 2>/dev/null)

echo "✓ $RESULT"