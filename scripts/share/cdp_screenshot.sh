#!/bin/bash
# AuViMa项目 - 自动化视觉管理系统
# 功能: 截图当前页面
# 背景: 本脚本是AuViMa项目的一部分，用于自动化控制Chrome浏览器进行网页操作和测试
#      提供网页截图功能，支持保存为PNG格式图片，用于文档记录、自动化测试验证等场景
# 用法: ./cdp_screenshot.sh <save_directory>
# 参数: save_directory - 保存截图的目录路径（必需，不包含文件名）

PORT="${CDP_PORT:-9222}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 检查保存目录参数
if [ -z "$1" ]; then
    echo "错误: 必须提供保存目录参数"
    echo "该脚本仅用于收集数据/创建分镜/执行录制阶段(收集素材)"
    echo "用法: $0 <save_directory>"
    echo "示例: $0 /path/to/screenshots"
    exit 1
fi

SAVE_DIR="$1"

# 创建保存目录
mkdir -p "${SAVE_DIR}"

echo "=== Chrome CDP 截图 ==="
echo "端口: $PORT"
echo "保存目录: $SAVE_DIR"

# 检查CDP是否运行
if ! curl -s --noproxy '*' "127.0.0.1:${PORT}/json/version" > /dev/null 2>&1; then
    echo "✗ CDP未运行"
    echo "请先运行: python src/chrome_cdp_launcher_v2.py"
    exit 1
fi

# 检查websocat是否安装
if ! command -v websocat &> /dev/null; then
    echo "✗ 截图需要安装 websocat"
    echo "请运行: brew install websocat"
    exit 1
fi

# 获取第一个页面信息
PAGE_INFO=$(curl -s --noproxy '*' "127.0.0.1:${PORT}/json" | jq -c '.[0] | select(.type == "page")')

if [ -z "$PAGE_INFO" ]; then
    echo "✗ 没有打开的页面"
    exit 1
fi

# 解析页面信息
TITLE=$(echo "$PAGE_INFO" | jq -r '.title // "Untitled"')
URL=$(echo "$PAGE_INFO" | jq -r '.url // ""')
WS_URL=$(echo "$PAGE_INFO" | jq -r '.webSocketDebuggerUrl // ""')

echo -e "\n页面信息:"
echo "标题: $TITLE"
echo "URL: $URL"

if [ -z "$WS_URL" ]; then
    echo "✗ 无法获取WebSocket URL"
    exit 1
fi

# 生成截图文件名
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
SAFE_TITLE=$(echo "$TITLE" | sed 's/[^a-zA-Z0-9_-]/_/g' | cut -c1-30)
FILENAME="${SAVE_DIR}/screenshot_${TIMESTAMP}_${SAFE_TITLE}.png"

echo -e "\n开始截图..."

# 使用websocat进行WebSocket通信（与cdp_status.sh相同的方法）
# 使用Page.captureScreenshot (标准CDP方法)
SCREENSHOT_RESULT=$(echo '{"id":1,"method":"Page.captureScreenshot","params":{"format":"png"}}' | \
    websocat -B 10485760 -t -n1 "$WS_URL" 2>/dev/null)

if [ -n "$SCREENSHOT_RESULT" ]; then
    # 先保存到临时文件，避免命令行长度限制
    TEMP_JSON="${SAVE_DIR}/temp_screenshot.json"
    echo "$SCREENSHOT_RESULT" > "$TEMP_JSON"
    
    # 从文件中提取base64数据
    SCREENSHOT_DATA=$(jq -r '.result.data // empty' < "$TEMP_JSON" 2>/dev/null)
    rm -f "$TEMP_JSON"
    
    if [ -n "$SCREENSHOT_DATA" ] && [ "$SCREENSHOT_DATA" != "empty" ]; then
        echo "$SCREENSHOT_DATA" | base64 -d > "$FILENAME" 2>/dev/null
        if [ -s "$FILENAME" ]; then
            echo "✓ 截图已保存: $FILENAME"
            
            # 显示文件信息
            FILE_SIZE=$(ls -lh "$FILENAME" | awk '{print $5}')
            echo "文件大小: $FILE_SIZE"
        else
            rm -f "$FILENAME"
            echo "✗ 截图失败: 解码错误"
            exit 1
        fi
    else
        echo "✗ 截图失败: 无返回数据"
        exit 1
    fi
else
    echo "✗ 截图失败: WebSocket通信错误"
    exit 1
fi