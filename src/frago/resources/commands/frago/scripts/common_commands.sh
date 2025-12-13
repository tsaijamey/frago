#!/bin/bash
# Frago 通用命令速查
# 适用于: /frago.run, /frago.do, /frago.recipe, /frago.test

# === Chrome 管理（首先执行）===
# 检查 CDP 连接状态
frago chrome status

# 启动 Chrome（两种模式）
frago chrome start              # 正常窗口模式
frago chrome start --headless   # 无头模式（无界面）

# 常用启动选项
frago chrome start --port 9333        # 使用其他端口
frago chrome start --keep-alive       # 启动后保持运行，直到 Ctrl+C
frago chrome start --no-kill          # 不关闭已存在的 CDP Chrome 进程

# 停止 Chrome
frago chrome stop

# === 发现资源 ===
# 列出所有配方
frago recipe list
frago recipe list --format json  # AI 格式

# 查看配方详情
frago recipe info <recipe_name>

# 搜索相关项目记录
rg -l "关键词" projects/

# === 浏览器操作 ===
# 导航
frago chrome navigate <url>
frago chrome navigate <url> --wait-for <selector>

# 点击
frago chrome click <selector>
frago chrome click <selector> --wait-timeout 10

# 滚动
frago chrome scroll <pixels>  # 正数向下，负数向上
frago chrome scroll-to --text "目标文本"

# 等待
frago chrome wait <seconds>

# === 信息提取 ===
# 获取标题
frago chrome get-title

# 获取内容
frago chrome get-content
frago chrome get-content <selector>

# 执行 JavaScript
frago chrome exec-js <expression>
frago chrome exec-js <expression> --return-value
frago chrome exec-js "window.location.href" --return-value  # 获取 URL

# 截图
frago chrome screenshot output.png
frago chrome screenshot output.png --full-page

# === 视觉效果 ===
frago chrome highlight <selector>
frago chrome pointer <selector>
frago chrome spotlight <selector>
frago chrome annotate <selector> --text "说明"

# === Run/Project 管理 ===
# 列出项目
frago run list
frago run list --format json

# 初始化项目
frago run init "task description"

# 设置上下文
frago run set-context <project_id>

# 释放上下文
frago run release

# 记录日志
frago run log \
  --step "步骤描述" \
  --status "success" \
  --action-type "analysis" \
  --execution-method "analysis" \
  --data '{"key": "value"}'

# 截图（在上下文中）
frago run screenshot "步骤描述"

# === Recipe 执行 ===
frago recipe run <name>
frago recipe run <name> --params '{"key": "value"}'
frago recipe run <name> --output-file result.json
