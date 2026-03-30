#!/bin/bash
# SessionStart hook: 引导 agent 通过 frago book 建立自我认知
#
# 由 frago 自动安装到 ~/.claude/settings.json
# 触发条件：每次 Claude Code session 启动
# 输出：additionalContext 提示 agent 运行 frago book

cat << 'EOF'
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "你刚刚启动，处于零记忆状态。在处理用户请求之前，先运行 `uv run frago book` 了解你的运行环境和能力边界。这是你认识自己的起点。"
  }
}
EOF

exit 0
