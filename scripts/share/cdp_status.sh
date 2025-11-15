#!/bin/bash
# AuViMa项目 - 自动化视觉管理系统
# 功能: 获取Chrome和页面状态，检查CDP连接，并截图保存
# 背景: 本脚本是AuViMa项目的一部分，用于自动化控制Chrome浏览器进行网页操作和测试
#      用于诊断和确认Chrome DevTools Protocol接口的可用性及浏览器状态
# 用法: ./cdp_status.sh

PORT="${CDP_PORT:-9222}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP_DIR="${SCRIPT_DIR}/tmp"

# 创建tmp目录
mkdir -p "${TMP_DIR}"

echo "=== Chrome CDP 状态 ==="
echo "端口: $PORT"

# 检查CDP是否运行
if curl -s --noproxy '*' "127.0.0.1:${PORT}/json/version" > /dev/null 2>&1; then
    echo "✓ CDP运行中"
    
    # 获取版本信息
    VERSION=$(curl -s --noproxy '*' "127.0.0.1:${PORT}/json/version" | jq -r '.Browser' 2>/dev/null || echo "未知")
    echo "浏览器: $VERSION"
    
    # 获取页面列表
    echo -e "\n=== 打开的页面 ==="
    
    # 获取所有页面信息
    PAGES=$(curl -s --noproxy '*' "127.0.0.1:${PORT}/json")
    
    # 解析并显示页面
    PAGE_COUNT=0
    echo "$PAGES" | jq -c '.[] | select(.type == "page")' | while IFS= read -r page; do
        PAGE_COUNT=$((PAGE_COUNT + 1))
        TITLE=$(echo "$page" | jq -r '.title // "Untitled"')
        URL=$(echo "$page" | jq -r '.url // ""')
        PAGE_ID=$(echo "$page" | jq -r '.id // ""')
        WS_URL=$(echo "$page" | jq -r '.webSocketDebuggerUrl // ""')
        
        echo "$PAGE_COUNT. $TITLE"
        echo "   URL: $URL"
        
        # 通过CDP WebSocket进行截图
        if [ -n "$WS_URL" ]; then
            # 生成截图文件名
            TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
            SAFE_TITLE=$(echo "$TITLE" | sed 's/[^a-zA-Z0-9_-]/_/g' | cut -c1-30)
            FILENAME="${TMP_DIR}/screenshot_${TIMESTAMP}_${SAFE_TITLE}.png"
            
            # 使用websocat进行WebSocket通信
            if command -v websocat &> /dev/null; then
                # 方法1: 使用Page.captureScreenshot (标准CDP方法)
                # 使用更大的缓冲区来处理大的截图数据
                SCREENSHOT_RESULT=$(echo '{"id":1,"method":"Page.captureScreenshot","params":{"format":"png"}}' | \
                    websocat -B 10485760 -t -n1 "$WS_URL" 2>/dev/null)
                
                # 提取base64数据
                if [ -n "$SCREENSHOT_RESULT" ]; then
                    # 先保存到临时文件，避免命令行长度限制
                    TEMP_JSON="${TMP_DIR}/temp_screenshot.json"
                    echo "$SCREENSHOT_RESULT" > "$TEMP_JSON"
                    
                    # 从文件中提取base64数据
                    SCREENSHOT_DATA=$(jq -r '.result.data // empty' < "$TEMP_JSON" 2>/dev/null)
                    rm -f "$TEMP_JSON"
                    
                    if [ -n "$SCREENSHOT_DATA" ] && [ "$SCREENSHOT_DATA" != "empty" ]; then
                        echo "$SCREENSHOT_DATA" | base64 -d > "$FILENAME" 2>/dev/null
                        if [ -s "$FILENAME" ]; then
                            echo "   ✓ 截图已保存: $FILENAME"
                            
                            # 使用Claude CLI分析截图
                            if command -v ccr &> /dev/null; then
                                echo "   分析截图中..."
                                ANALYSIS=$(ccr claude "读取${FILENAME}图片一句话描述该图片在哪个网站什么状态" 2>/dev/null)
                                if [ -n "$ANALYSIS" ]; then
                                    echo "   📖 $ANALYSIS"
                                fi
                                # 分析完成后删除截图
                                rm -f "$FILENAME"
                            elif command -v claude &> /dev/null; then
                                echo "   分析截图中..."
                                ANALYSIS=$(claude "读取${FILENAME}图片一句话描述该图片在哪个网站什么状态" 2>/dev/null)
                                if [ -n "$ANALYSIS" ]; then
                                    echo "   📖 $ANALYSIS"
                                fi
                                # 分析完成后删除截图
                                rm -f "$FILENAME"
                            else
                                # 如果没有Claude CLI，也删除截图
                                rm -f "$FILENAME"
                            fi
                        else
                            rm -f "$FILENAME"
                            echo "   ⚠ 截图失败: 解码错误"
                        fi
                    else
                        # 方法2: 通过执行JavaScript来截图
                        echo "   尝试JS方法截图..."
                        
                        # 先启用Page domain
                        echo '{"id":1,"method":"Page.enable","params":{}}' | websocat -t -n1 "$WS_URL" > /dev/null 2>&1
                        sleep 0.2
                        
                        # 执行JS代码获取页面截图
                        JS_CODE='
                        (async () => {
                            const canvas = document.createElement("canvas");
                            const ctx = canvas.getContext("2d");
                            canvas.width = window.innerWidth;
                            canvas.height = window.innerHeight;
                            
                            // 尝试使用html2canvas如果存在
                            if (typeof html2canvas !== "undefined") {
                                const tempCanvas = await html2canvas(document.body);
                                ctx.drawImage(tempCanvas, 0, 0);
                            } else {
                                // 简单填充背景色作为测试
                                ctx.fillStyle = "#f0f0f0";
                                ctx.fillRect(0, 0, canvas.width, canvas.height);
                                ctx.fillStyle = "#333";
                                ctx.font = "20px Arial";
                                ctx.fillText("CDP Screenshot Test", 20, 40);
                            }
                            
                            return canvas.toDataURL("image/png").split(",")[1];
                        })()
                        '
                        
                        # 转义JS代码并执行
                        ESCAPED_JS=$(echo "$JS_CODE" | sed 's/"/\\"/g' | tr -d '\n')
                        EVAL_CMD="{\"id\":2,\"method\":\"Runtime.evaluate\",\"params\":{\"expression\":\"$ESCAPED_JS\",\"awaitPromise\":true,\"returnByValue\":true}}"
                        
                        JS_RESULT=$(echo "$EVAL_CMD" | websocat -t -n1 "$WS_URL" 2>/dev/null)
                        
                        if [ -n "$JS_RESULT" ]; then
                            JS_DATA=$(echo "$JS_RESULT" | jq -r '.result.result.value // empty')
                            if [ -n "$JS_DATA" ] && [ "$JS_DATA" != "empty" ]; then
                                echo "$JS_DATA" | base64 -d > "$FILENAME" 2>/dev/null
                                if [ -s "$FILENAME" ]; then
                                    echo "   ✓ JS截图已保存: $FILENAME"
                                else
                                    rm -f "$FILENAME"
                                    echo "   ⚠ JS截图失败: 解码错误"
                                fi
                            else
                                echo "   ⚠ JS截图失败: 无返回数据"
                            fi
                        fi
                    fi
                fi
            else
                echo "   ⚠ 截图需要安装 websocat: brew install websocat"
                echo "   请运行: brew install websocat"
            fi
        fi
    done
    
    # 如果没有页面
    if [ $(echo "$PAGES" | jq '[.[] | select(.type == "page")] | length') -eq 0 ]; then
        echo "没有打开的页面"
    fi
    
else
    echo "✗ CDP未运行"
    echo "请先运行: python src/chrome_cdp_launcher_v2.py"
fi