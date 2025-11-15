#!/bin/bash
# AuViMa项目 - 自动化视觉管理系统
# 功能: 执行JavaScript代码
# 背景: 本脚本是AuViMa项目的一部分，用于自动化控制Chrome浏览器进行网页操作和测试
#      在当前页面上下文中执行自定义JavaScript代码，提供灵活的页面操作和数据获取能力
# 用法: ./cdp_exec_js.sh "<javascript_code>"

JS_CODE="${1}"
PORT="${CDP_PORT:-9222}"

if [ -z "$JS_CODE" ]; then
    echo "用法: $0 \"<javascript_code>\""
    echo "例如: $0 \"document.body.style.backgroundColor='red'\""
    exit 1
fi

# 获取第一个页面的WebSocket URL
WS_INFO=$(curl -s --noproxy '*' "127.0.0.1:${PORT}/json" | python3 -c "
import sys,json
pages = json.load(sys.stdin)
page = next((p for p in pages if p.get('type') == 'page'), None)
if page:
    # 提取页面ID和WebSocket路径
    ws_url = page.get('webSocketDebuggerUrl', '')
    if ws_url:
        # ws://127.0.0.1:9222/devtools/page/XXX -> /devtools/page/XXX
        path = ws_url.split('9222')[1] if '9222' in ws_url else ''
        print(path)
")

if [ -z "$WS_INFO" ]; then
    echo "错误: 无法获取页面信息"
    exit 1
fi

# 使用纯bash和nc发送WebSocket消息
(
# WebSocket握手
echo -ne "GET ${WS_INFO} HTTP/1.1\r\n"
echo -ne "Host: 127.0.0.1:${PORT}\r\n"
echo -ne "Upgrade: websocket\r\n"
echo -ne "Connection: Upgrade\r\n"
echo -ne "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
echo -ne "Sec-WebSocket-Version: 13\r\n"
echo -ne "\r\n"

# 等待握手完成
sleep 0.2

# 构建CDP命令
CDP_CMD="{\"id\":1,\"method\":\"Runtime.evaluate\",\"params\":{\"expression\":$(echo "$JS_CODE" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read().strip()))")}}"

# WebSocket frame: FIN=1, opcode=1(text), mask=0
# 简单起见，对于小消息直接发送
LEN=${#CDP_CMD}
if [ $LEN -lt 126 ]; then
    # 0x81 = FIN + text frame
    printf "\x81"
    # length without mask
    printf "\\x$(printf '%02x' $LEN)"
    # payload
    echo -n "$CDP_CMD"
fi

sleep 0.2
) | nc 127.0.0.1 ${PORT} | tail -n1 | python3 -c "
import sys,json
try:
    # 读取WebSocket帧响应
    data = sys.stdin.buffer.read()
    # 跳过WebSocket帧头，提取JSON
    start = data.find(b'{')
    if start != -1:
        json_data = data[start:]
        result = json.loads(json_data)
        if 'result' in result and 'result' in result['result']:
            value = result['result']['result'].get('value')
            if value is not None:
                print(value)
except:
    pass
" 2>/dev/null