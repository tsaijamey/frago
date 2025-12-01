#!/bin/bash
# Frago CDP 命令示例

# === 导航 ===
uv run frago navigate "https://x.com/search?q=AI"

# === 滚动定位 ===
# 滚动到包含指定文本的元素
uv run frago scroll-to --text "AI 将改变工作方式"

# === 截图 ===
uv run frago screenshot "screenshots/001.png"

# === 等待 ===
uv run frago wait 2

# === 获取页面内容 ===
uv run frago get-content

# === 执行 JavaScript ===
uv run frago exec-js "document.querySelector('[data-testid=\"tweetText\"]').innerText"

# === 配方执行 ===
# 提取推文+评论
uv run frago recipe run x_extract_tweet_with_comments \
  --params '{"url": "https://x.com/user/status/123456"}'

# 提取 Timeline
uv run frago recipe run x_extract_timeline_with_scroll \
  --params '{"query": "AI", "max_tweets": 20}'
