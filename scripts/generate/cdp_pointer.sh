#!/bin/bash
# AuViMa项目 - 自动化视觉管理系统
# 功能: 添加动态指针效果，模拟鼠标移动到元素
# 背景: 本脚本是AuViMa项目的一部分，用于自动化控制Chrome浏览器进行网页操作和测试
#      创建动态鼠标指针动画，模拟从屏幕角落移动到目标元素的过程，用于操作演示和用户指导
# 用法: ./cdp_pointer.sh <selector> [duration]

SELECTOR="${1}"
DURATION="${2:-2}"  # 动画持续时间（秒）
PORT="${CDP_PORT:-9222}"

if [ -z "$SELECTOR" ]; then
    echo "用法: $0 <selector> [duration]"
    echo "例如: $0 'button.submit' 3"
    exit 1
fi

JS_CODE="
(() => {
    // 获取目标元素
    const element = document.querySelector('${SELECTOR}');
    if (!element) return 'Element not found';
    
    const rect = element.getBoundingClientRect();
    const targetX = rect.left + rect.width/2;
    const targetY = rect.top + rect.height/2;
    
    // 创建指针
    const pointer = document.createElement('div');
    pointer.className = 'auvima-pointer';
    pointer.innerHTML = \`
        <svg width='30' height='30' viewBox='0 0 30 30'>
            <path d='M 5 5 L 25 12 L 12 25 Z' fill='#ff4444' stroke='#fff' stroke-width='2'/>
        </svg>
    \`;
    
    // 起始位置（屏幕右上角）
    const startX = window.innerWidth - 100;
    const startY = 100;
    
    pointer.style.cssText = \`
        position: fixed;
        left: \${startX}px;
        top: \${startY}px;
        width: 30px;
        height: 30px;
        z-index: 100000;
        pointer-events: none;
        filter: drop-shadow(0 2px 4px rgba(0,0,0,0.5));
        animation: auvima-move-pointer ${DURATION}s ease-in-out;
    \`;
    
    document.body.appendChild(pointer);
    
    // 添加动画样式
    const style = document.createElement('style');
    style.textContent = \`
        @keyframes auvima-move-pointer {
            0% {
                left: \${startX}px;
                top: \${startY}px;
                opacity: 0;
            }
            10% {
                opacity: 1;
            }
            90% {
                left: \${targetX - 15}px;
                top: \${targetY - 15}px;
                opacity: 1;
            }
            100% {
                left: \${targetX - 15}px;
                top: \${targetY - 15}px;
                opacity: 0;
            }
        }
    \`;
    document.head.appendChild(style);
    
    // 移除指针
    setTimeout(() => {
        pointer.remove();
        style.remove();
    }, ${DURATION}000 + 500);
    
    // 滚动到元素
    element.scrollIntoView({behavior: 'smooth', block: 'center'});
    
    return 'Pointer animation to: ${SELECTOR}';
})()
"

RESULT=$(curl -s --noproxy '*' -X POST "127.0.0.1:${PORT}/json/runtime/evaluate" \
    -d "{\"expression\": \"${JS_CODE}\"}" \
    -H "Content-Type: application/json" | \
    python3 -c "import sys,json; r=json.load(sys.stdin); print(r.get('result',{}).get('result',{}).get('value',''))" 2>/dev/null)

echo "✓ $RESULT"