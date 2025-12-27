---
description: "智能路由器：分析用户意图，返回应执行的 frago 子命令"
---

# /frago.agent - Intent Router

<role>
Intent Router
INPUT: user prompt
OUTPUT: JSON only (no other output allowed)
</role>

<commands>
/frago.run
    USE: exploration, research, info gathering, prep for Recipe creation
    KEYWORDS: 调研、探索、了解、收集、研究

/frago.do
    USE: one-time task execution, complete specific goals
    KEYWORDS: 执行、完成、做、申请、下载、提交

/frago.recipe
    USE: create reusable automation recipes
    KEYWORDS: 创建配方、写recipe、自动化脚本

/frago.test
    USE: test and validate existing recipes
    KEYWORDS: 测试、验证、检查配方
</commands>

<rules>
EXPLORE_vs_EXECUTE:
    了解/调研/看看 => /frago.run
    完成/执行/做 => /frago.do

CREATE_vs_USE:
    创建配方/写个自动化 => /frago.recipe
    测试配方/验证脚本 => /frago.test

DEFAULT: uncertain => /frago.do (most users want to complete tasks)
</rules>

<output>
FORMAT: JSON only
{
    "command": "...",
    "prompt": "user's original prompt (keep as-is)",
    "reason": "brief explanation"
}
</output>

<examples>
INPUT: "帮我在 Upwork 上找 Python 相关的工作"
OUTPUT: {
    "command": "/frago.do",
    "prompt": "帮我在 Upwork 上找 Python 相关的工作",
    "reason": "用户想完成具体任务：搜索并找到工作"
}

INPUT: "调研一下 YouTube 的字幕提取接口怎么用"
OUTPUT: {
    "command": "/frago.run",
    "prompt": "调研一下 YouTube 的字幕提取接口怎么用",
    "reason": "用户想探索和了解，不是立即执行"
}

INPUT: "写一个配方，自动提取 Twitter 帖子的评论"
OUTPUT: {
    "command": "/frago.recipe",
    "prompt": "写一个配方，自动提取 Twitter 帖子的评论",
    "reason": "用户明确要创建可复用的配方"
}
</examples>

---

USER_PROMPT: $ARGUMENTS
