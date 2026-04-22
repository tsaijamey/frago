# browser-fetch

分类: 替代（MUST）

## 是什么
获取网页内容必须通过 {{frago_launcher}} chrome navigate 导航到目标页面，再用 get-content 提取内容。WebFetch 工具在 frago 环境中不可靠，且无法处理需要 JS 渲染的页面。

## 怎么用
  {{frago_launcher}} chrome navigate "https://example.com/page"
  {{frago_launcher}} chrome get-content                           # 获取整页内容
  {{frago_launcher}} chrome get-content --selector ".article"     # 获取指定区域

## 什么时候用
- 需要读取任何网页内容时
- 需要提取页面上的特定数据时
- 需要与需要 JS 渲染的 SPA 页面交互时

## 不要做
- 不要使用 WebFetch 工具
- 不要使用 curl 获取网页内容
- 不要假设页面是静态 HTML，始终通过浏览器渲染后获取
