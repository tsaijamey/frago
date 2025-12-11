# 禁止幻觉导航

适用于：`/frago.run`、`/frago.do`

## 核心规则

**严禁猜测 URL 直接导航。**

Claude 容易凭空构造看似合理但不存在的链接。

## 错误示例

```bash
# ❌ 禁止：你怎么知道有 v2？
frago chrome navigate "https://example.com/api/v2/docs"

# ❌ 禁止：验证过参数吗？
frago chrome navigate "https://upwork.com/search?q=python&sort=relevance"

# ❌ 禁止：凭空构造的用户页面
frago chrome navigate "https://twitter.com/elonmusk/status/123456789"
```

## 正确做法：剥洋葱式层层深入

```bash
# ✅ 第一步：导航到已知首页
frago chrome navigate "https://example.com"

# ✅ 第二步：从页面获取真实链接
frago chrome exec-js "Array.from(document.querySelectorAll('a')).map(a => ({text: a.textContent.trim(), href: a.href})).filter(a => a.text)" --return-value

# ✅ 第三步：使用从上一步获取的真实 URL
frago chrome navigate "<从上一步获取的真实 URL>"
```

## 允许直接导航的 URL 来源

| 来源 | 示例 |
|------|------|
| 用户明确提供 | "请打开 https://example.com/specific-page" |
| 上下文中的链接 | 之前对话中用户粘贴的 URL |
| 页面上获取的 | 通过 `exec-js` 提取的 `href` |
| 搜索结果返回 | Google 搜索结果中的链接 |
| 配方输出的 | Recipe 返回的 URL 字段 |

## 搜索的正确方式

```bash
# ✅ 使用 Google 搜索
frago chrome navigate "https://google.com/search?q=site:example.com+api+documentation"

# 然后从搜索结果中提取链接
frago chrome exec-js "Array.from(document.querySelectorAll('a[href]')).filter(a => a.href.includes('example.com')).map(a => a.href)" --return-value
```
