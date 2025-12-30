#!/bin/bash
# frago CDP Command Examples

# === Navigation ===
uv run frago navigate "https://x.com/search?q=AI"

# === Scroll to Element ===
# Scroll to element containing specified text
uv run frago scroll-to --text "AI will change the way we work"

# === Screenshot ===
uv run frago screenshot "screenshots/001.png"

# === Wait ===
uv run frago wait 2

# === Get Page Content ===
uv run frago get-content

# === Execute JavaScript ===
uv run frago exec-js "document.querySelector('[data-testid=\"tweetText\"]').innerText"

# === Recipe Execution ===
# Extract tweet + comments
uv run frago recipe run x_extract_tweet_with_comments \
  --params '{"url": "https://x.com/user/status/123456"}'

# Extract Timeline
uv run frago recipe run x_extract_timeline_with_scroll \
  --params '{"query": "AI", "max_tweets": 20}'
