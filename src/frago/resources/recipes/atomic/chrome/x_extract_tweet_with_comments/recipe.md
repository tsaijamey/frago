---
name: x_extract_tweet_with_comments
type: atomic
runtime: chrome-js
version: "1.0"
description: "Extract complete tweet information and comment list from X.com tweet pages"
use_cases:
  - "Collect discussion content from specific tweets for analysis"
  - "Monitor user feedback on brand tweets"
  - "Research comment trends on trending topics"
  - "Build tweet datasets for NLP research"
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
    description: "JSON object containing tweet and comments"
dependencies: []
---

# x_extract_tweet_with_comments

## Description

Extract complete tweet information and comment lists from X.com (Twitter) tweet pages. This recipe can:
- Extract tweet author, username, full content, and statistics (replies, retweets, likes, bookmarks, views)
- Automatically scroll the page to load comments until 40 comments or all available comments are retrieved
- Extract author, username, content, and view count for each comment
- Return structured JSON data for easy subsequent processing

Use Cases:
- Collect discussion content from specific tweets for analysis
- Monitor user feedback on brand tweets
- Research comment trends on trending topics
- Build tweet datasets for NLP research

## Usage

**Recipe Executor Note**: The generated recipe is essentially JavaScript code that is injected into the browser via CDP's Runtime.evaluate interface. Therefore, the standard way to execute the recipe is to use the `uv run frago chrome exec-js` command.

1. Ensure Chrome is started with CDP debugging port enabled (default 9222)
2. Navigate to the target tweet page:
   ```bash
   uv run frago chrome navigate "https://x.com/username/status/123456789"
   ```
3. Execute the recipe:
   ```bash
   # Inject the recipe JS file as a script into the browser and get the return value
   uv run frago chrome exec-js src/frago/recipes/x_extract_tweet_with_comments.js --return-value
   ```
4. The recipe will return JSON-formatted data containing:
   - `tweet`: Main tweet information (author, content, statistics)
   - `comments`: Comment list (up to 40 items)
   - `meta`: Metadata (actual number of comments extracted, etc.)

**Note**: When debugging as AI, remember that the `.js` files you generate do not run in a Node.js environment, but in the browser context (similar to Chrome Console). Therefore:
- Cannot use `require()` or `import`
- Can directly use browser APIs like `document`, `window`
- `console.log` output typically needs to be viewed with `--return-value` or in the browser console

## Prerequisites

- Chrome browser is started with CDP debugging enabled (`google-chrome --remote-debugging-port=9222`)
- Navigated to a specific tweet page (`https://x.com/username/status/[tweet_id]`)
- **Assumed to be logged into X.com account** (some tweet comments may require login to view full content)
- Stable network connection, able to load tweets and comments normally

## Expected Output

After successful execution, the recipe will return the following JSON structure:

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
    // ... up to 40 comments
  ],
  "meta": {
    "totalCommentsExtracted": 40,
    "targetComments": 40
  }
}
```

## Notes

- **Selector Stability**: Uses 1 data attribute selector (`article` element, no specific data-testid dependency), medium priority
- **Text Parsing Method**: The recipe extracts data by parsing `innerText` rather than relying on CSS selectors to locate specific fields. This approach has some tolerance for DOM structure changes, but assumes X.com's article text format is relatively stable
- **Fragile Points**:
  - Depends on the fixed format of `innerText` (order of author name, username, content, statistics)
  - X.com redesigns that adjust article internal structure may cause parsing errors
  - Statistical data order assumptions (replies, retweets, likes, bookmarks, views) may vary by page type
- **Scroll Loading Limitations**:
  - Recipe scrolls at most 20 times (to prevent infinite loops)
  - Stops when no new comments are loaded 3 consecutive times (judged to have reached the bottom)
  - If comment loading is slow, may not reach the 40-comment target
- **Login Status**: Recipe assumes user is logged in; some comments may not be visible when not logged in
- **Rate Limiting**: Frequent execution may trigger X.com's rate limiting, recommend appropriate intervals
- If X.com redesign causes script failure, use `/frago.recipe update x_extract_tweet_with_comments` to update the recipe

## Update History

| Date | Version | Change Description |
|------|---------|-------------------|
| 2025-11-19 | v1 | Initial version, created based on exploratory testing |
