---
name: x_extract_tweet_with_comments
type: atomic
runtime: chrome-js
version: "1.0"
description: "从X.com推文页面提取完整推文信息及评论列表"
use_cases:
  - "收集特定推文的讨论内容进行分析"
  - "监控品牌推文的用户反馈"
  - "研究热门话题的评论趋势"
  - "构建推文数据集用于NLP研究"
output_targets:
  - stdout
  - file
tags:
  - twitter
  - x-com
  - social-media
  - web-scraping
  - comments
inputs: {}
outputs:
  tweet_data:
    type: object
    description: "包含推文和评论的JSON对象"
dependencies: []
---

# x_extract_tweet_with_comments

## 功能描述

从X.com（Twitter）推文页面提取完整的推文信息及其评论列表。该配方能够：
- 提取推文作者、用户名、完整内容和统计数据（评论数、转发数、点赞数、书签数、浏览数）
- 自动滚动页面加载评论，直到获取40条评论或所有可用评论
- 提取每条评论的作者、用户名、内容和浏览数
- 返回结构化的JSON数据，便于后续处理

适用场景：
- 收集特定推文的讨论内容进行分析
- 监控品牌推文的用户反馈
- 研究热门话题的评论趋势
- 构建推文数据集用于NLP研究

## 使用方法

**配方执行器说明**：生成的配方本质上是JavaScript代码，通过CDP的Runtime.evaluate接口注入到浏览器中执行。因此，执行配方的标准方式是使用 `uv run frago chrome exec-js` 命令。

1. 确保Chrome已启动并开启CDP调试端口（默认9222）
2. 导航到目标推文页面：
   ```bash
   uv run frago chrome navigate "https://x.com/username/status/123456789"
   ```
3. 执行配方：
   ```bash
   # 将配方JS文件作为脚本注入浏览器执行，并获取返回值
   uv run frago chrome exec-js src/frago/recipes/x_extract_tweet_with_comments.js --return-value
   ```
4. 配方将返回JSON格式的数据，包含：
   - `tweet`: 主推文信息（作者、内容、统计数据）
   - `comments`: 评论列表（最多40条）
   - `meta`: 元数据（实际提取的评论数量等）

**注意**：AI调试时请记住，你生成的 `.js` 文件不是在 Node.js 环境中运行，而是在浏览器的上下文中运行（类似 Chrome Console）。因此：
- 不能使用 `require()` 或 `import`
- 可以直接使用 `document`, `window` 等浏览器 API
- `console.log` 的输出通常需要查看 `--return-value` 或浏览器控制台

## 前置条件

- Chrome浏览器已启动CDP调试（`google-chrome --remote-debugging-port=9222`）
- 已导航到具体的推文页面（`https://x.com/username/status/[tweet_id]`）
- **假定已登录X.com账户**（某些推文的评论可能需要登录才能查看完整内容）
- 网络连接稳定，能够正常加载推文和评论

## 预期输出

配方成功执行后，将返回如下JSON结构：

```json
{
  "tweet": {
    "author": "Google AI Studio",
    "username": "@GoogleAIStudio",
    "content": "gemini 3 pro\n\n• our most intelligent model yet\n• SOTA reasoning\n• 1501 Elo on LMArena\n• next-level vibe coding capabilities\n• complex multimodal understanding\n\navailable now in Google AI Studio and the Gemini API",
    "stats": {
      "replies": "266",
      "retweets": "1.6K",
      "likes": "12K",
      "bookmarks": "1.4K",
      "views": "466.8K"
    }
  },
  "comments": [
    {
      "author": "Robert Boehme",
      "username": "@RBoehme86",
      "content": "How does it compare to Grok-4.1 @xai ?",
      "stats": {
        "views": "9.7K"
      }
    },
    {
      "author": "Chidera Achinikee",
      "username": "@aichidera",
      "content": "@grok is it better than you?",
      "stats": {
        "views": "1.9K"
      }
    }
    // ... 最多40条评论
  ],
  "meta": {
    "totalCommentsExtracted": 40,
    "targetComments": 40
  }
}
```

## 注意事项

- **选择器稳定性**：使用了1个data属性选择器（`article` 元素，无特定data-testid依赖），优先级中等
- **文本解析方式**：配方通过解析 `innerText` 提取数据，而非依赖CSS选择器定位具体字段。这种方式对DOM结构变化有一定容错性，但需要假定X.com的article文本格式相对稳定
- **脆弱点**：
  - 依赖 `innerText` 的固定格式（作者名、用户名、内容、统计数据的顺序）
  - X.com改版调整article内部结构可能导致解析错误
  - 统计数据的顺序假设（评论数、转发数、点赞数、书签数、浏览数）可能因页面类型不同而变化
- **滚动加载限制**：
  - 配方最多滚动20次（防止无限循环）
  - 连续3次未加载新评论时停止（判定已到底部）
  - 如果评论加载缓慢，可能无法达到40条目标
- **登录状态**：配方假定用户已登录，未登录状态下某些评论可能不可见
- **速率限制**：频繁执行配方可能触发X.com的速率限制，建议适当间隔
- 如X.com改版导致脚本失效，使用 `/frago.recipe update x_extract_tweet_with_comments` 更新配方

## 更新历史

| 日期 | 版本 | 变更说明 |
|------|------|----------|
| 2025-11-19 | v1 | 初始版本，基于探索实测创建 |
