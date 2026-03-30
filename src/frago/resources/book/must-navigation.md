# must-navigation

分类: 替代（MUST）

## 解决什么问题
agent 凭预训练知识构造看似合理但不存在的 URL，导致 404、操作错误页面、或泄露意图。必须逐层探索获取真实链接。

## 错误示例

  # ❌ 你怎么知道有 v2？
  frago chrome navigate "https://example.com/api/v2/docs"

  # ❌ 你验证过参数吗？
  frago chrome navigate "https://upwork.com/search?q=python&sort=relevance"

  # ❌ 编造的状态 ID
  frago chrome navigate "https://twitter.com/elonmusk/status/123456789"

## 正确做法：洋葱剥皮逐层探索

  # Step 1: 导航到已知首页
  frago chrome navigate "https://example.com"

  # Step 2: 从页面提取真实链接
  frago chrome exec-js "Array.from(document.querySelectorAll('a')).map(a => ({text: a.textContent.trim(), href: a.href})).filter(a => a.text)" --return-value

  # Step 3: 使用上一步获取的真实 URL
  frago chrome navigate "<上一步获取的真实 URL>"

## 允许直接导航的 URL 来源

| 来源 | 示例 |
|------|------|
| 用户明确提供 | "请打开 https://example.com/page" |
| 上下文中的链接 | 用户在对话中粘贴的 URL |
| 页面中提取的 | exec-js 提取的 href |
| 搜索结果 | Google 搜索结果中的链接 |
| Recipe 输出 | Recipe 返回的 URL 字段 |

## 搜索的正确方式

  # ✅ 用 Google 搜索
  frago chrome navigate "https://google.com/search?q=site:example.com+api+documentation"

  # 然后从搜索结果提取链接
  frago chrome exec-js "Array.from(document.querySelectorAll('a[href]')).filter(a => a.href.includes('example.com')).map(a => a.href)" --return-value
