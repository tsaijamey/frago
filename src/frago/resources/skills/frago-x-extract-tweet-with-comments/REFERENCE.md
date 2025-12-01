# Twitter 元素特征与定位参考

本文档提供 Twitter/X 平台的 DOM 结构、元素特征、选择器稳定性等技术细节，供素材收集和视频录制时参考。

---

## 目录

- [元素特征记录](#元素特征记录)
- [scroll_to 文本定位](#scroll_to-文本定位)
- [选择器稳定性分析](#选择器稳定性分析)
- [常见问题与解决方案](#常见问题与解决方案)

---

## 元素特征记录

### 为什么需要元素特征

Twitter 使用虚拟列表渲染，DOM 元素会动态创建/销毁。传统的 CSS 选择器（如 `.css-abc123`）极不稳定。

**推荐方案**：记录内容文本的唯一片段作为特征，后续通过文本搜索定位。

### 记录格式

```json
{
  "tweet_url": "https://x.com/user/status/123456",
  "element_feature": "AI 将改变工作方式，但我们需要",
  "feature_type": "text_content",
  "context": {
    "author": "@username",
    "is_comment": false,
    "comment_depth": 0
  }
}
```

### 特征选取原则

1. **唯一性**：选取在页面中唯一出现的文本片段
2. **稳定性**：避免包含动态内容（如时间戳、数字）
3. **足够长度**：至少 10 个字符，推荐 15-25 个字符
4. **完整词汇**：不要在词语中间截断

**好的特征**：
```
✅ "AI 将改变工作方式，但我们需要"
✅ "这个观点我完全不同意，因为"
✅ "The future of programming is"
```

**差的特征**：
```
❌ "AI"  // 太短，不唯一
❌ "2.3K likes"  // 包含动态数字
❌ "12:30 PM"  // 时间戳
❌ "改变工"  // 在词语中间截断
```

---

## scroll_to 文本定位

### 基本用法

```bash
# 滚动到包含指定文本的元素
uv run frago scroll-to "AI 将改变工作方式"
```

### 在分镜脚本中使用

```json
{
  "action": "scroll_to",
  "text": "AI 将改变工作方式，但我们需要",
  "wait": 1.5
}
```

### 定位失败的处理

当 `scroll_to` 找不到元素时：

1. **检查文本是否准确**：复制原文，避免手打错误
2. **尝试更长的片段**：增加特征文本长度
3. **使用备用定位**：
   ```json
   {
     "action": "scroll_to",
     "text": "备用文本片段",
     "fallback": {
       "action": "scroll",
       "direction": "down",
       "pixels": 500
     },
     "wait": 1.5
   }
   ```

### 评论定位技巧

评论区元素更不稳定，建议：

1. **使用评论内容的核心句子**（非开头，避免与其他评论重复）
2. **结合作者用户名**：`@username: 评论内容`
3. **优先使用截图备份**：热门推文评论排序会变化

---

## 选择器稳定性分析

### Twitter DOM 结构特点

| 元素 | 选择器 | 稳定性 | 说明 |
|-----|--------|-------|------|
| 推文容器 | `article[data-testid="tweet"]` | ✅ 稳定 | 官方测试用 |
| 用户头像 | `[data-testid="Tweet-User-Avatar"]` | ✅ 稳定 | |
| 推文文本 | `[data-testid="tweetText"]` | ✅ 稳定 | |
| 回复按钮 | `[data-testid="reply"]` | ✅ 稳定 | |
| 转发按钮 | `[data-testid="retweet"]` | ✅ 稳定 | |
| 点赞按钮 | `[data-testid="like"]` | ✅ 稳定 | |
| 分享按钮 | `[data-testid="share"]` | ⚠️ 中等 | |
| CSS 类名 | `.css-*`, `.r-*` | ❌ 不稳定 | CSS-in-JS 生成 |

### 推荐的高亮选择器

```json
{
  "action": "highlight",
  "selector": "article[data-testid='tweet']:has([data-testid='tweetText']:contains('目标文本'))",
  "duration": 2
}
```

**注意**：`:contains()` 是非标准选择器，需要通过 JavaScript 实现。实际使用时推荐 `scroll_to` + `highlight` 组合。

---

## 视觉效果组合

### 展示推文的推荐序列

```json
{
  "actions": [
    {"action": "scroll_to", "text": "目标推文的文本特征", "wait": 0.5},
    {"action": "highlight", "selector": "article:has(:scope *:contains('目标文本'))", "duration": 2},
    {"action": "wait", "seconds": 0.5}
  ]
}
```

### 展示评论的推荐序列

```json
{
  "actions": [
    {"action": "scroll_to", "text": "评论文本特征", "wait": 0.5},
    {"action": "pointer", "selector": "[data-testid='tweetText']", "duration": 1.5},
    {"action": "wait", "seconds": 0.5}
  ]
}
```

---

## 常见问题与解决方案

### Q1: 推文/评论加载慢

**原因**：网络延迟、Twitter 速率限制

**解决**：
```json
{
  "action": "navigate",
  "url": "https://x.com/user/status/123",
  "wait": 5  // 增加等待时间
}
```

### Q2: scroll_to 找不到元素

**可能原因**：
1. 文本被省略显示（`...`）
2. 文本包含特殊字符
3. 页面还未完全加载

**解决**：
```bash
# 先等待页面稳定
uv run frago wait 2

# 使用更短的核心文本片段
uv run frago scroll-to "核心关键词"
```

### Q3: 评论位置在不同时间不同

**原因**：热门推文评论按热度排序，会动态变化

**解决**：
1. 收集素材时立即截图
2. 录制时使用截图作为备份画面
3. 或接受"展示不同评论"的灵活性

### Q4: 高亮效果覆盖错误元素

**原因**：选择器不够精确

**解决**：
```json
{
  "action": "highlight",
  "selector": "article[data-testid='tweet']:nth-of-type(3)",  // 指定第几个
  "duration": 2
}
```

或使用 `scroll_to` 先定位，再对当前视口中心的元素高亮。

---

## 参考资料

- Twitter DOM 结构变化追踪：观察 `data-testid` 属性的变化
- Frago scroll-to 命令：`uv run frago scroll-to --help`
- 视频生产配方：`examples/workflows/video_produce_from_script/recipe.md`

---

**最后更新**：2025-11-28
