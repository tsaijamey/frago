#!/bin/bash
# AuViMa项目 - 自动化视觉管理系统
# 功能: CDP脚本帮助
# 背景: 本脚本是AuViMa项目的一部分，用于自动化控制Chrome浏览器进行网页操作和测试
#      显示所有可用的Chrome DevTools Protocol脚本的使用说明和示例
# 用法: ./cdp_help.sh

echo "=== Chrome CDP 操作脚本 ==="
echo ""
echo "基础操作："
echo "  cdp_status.sh          - 查看Chrome和页面状态"
echo "  cdp_navigate.sh <url>  - 导航到URL"
echo "  cdp_get_title.sh       - 获取页面标题"
echo "  cdp_get_content.sh [selector] - 获取文本内容"
echo ""
echo "页面交互："
echo "  cdp_click.sh <selector>    - 点击元素"
echo "  cdp_scroll.sh [pixels] [up/down] - 滚动页面"
echo "  cdp_wait.sh <selector> [timeout] - 等待元素"
echo ""
echo "高级功能："
echo "  cdp_screenshot.sh [output.png] - 页面截图"
echo "  cdp_exec_js.sh \"<js_code>\"    - 执行JavaScript"
echo ""
echo "环境变量："
echo "  CDP_PORT=9222  - 指定CDP端口（默认9222）"
echo ""
echo "示例："
echo "  ./cdp_navigate.sh https://github.com"
echo "  ./cdp_screenshot.sh github.png"
echo "  ./cdp_click.sh 'button.btn-primary'"
echo "  ./cdp_exec_js.sh \"alert('Hello')\""