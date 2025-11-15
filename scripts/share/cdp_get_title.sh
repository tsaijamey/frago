#!/bin/bash
# AuViMa项目 - 自动化视觉管理系统
# 功能: 获取页面标题
# 背景: 本脚本是AuViMa项目的一部分，用于自动化控制Chrome浏览器进行网页操作和测试
#      通过Chrome DevTools Protocol获取当前页面的标题，用于页面验证、状态检查等场景
# 用法: ./cdp_get_title.sh

PORT="${CDP_PORT:-9222}"

curl -s --noproxy '*' -X POST "127.0.0.1:${PORT}/json/runtime/evaluate" \
    -d '{"expression": "document.title"}' \
    -H "Content-Type: application/json" | \
    python3 -c "import sys,json; r=json.load(sys.stdin); print(r.get('result',{}).get('result',{}).get('value',''))" 2>/dev/null