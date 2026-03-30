# browser-search

分类: 替代（MUST）

## 是什么
在 frago 环境中搜索信息，必须通过 frago chrome navigate 打开 Google 搜索页面，然后用 get-content 提取结果。WebSearch 工具在 frago agent 中不可用/不稳定。

## 怎么用
  frago chrome navigate "https://www.google.com/search?q=your+query"
  frago chrome get-content --selector "#search"

## 什么时候用
- 需要搜索任何网页信息时
- 需要查找文档、API 参考时
- 需要验证在线内容时

## 不要做
- 不要使用 WebSearch 工具
- 不要使用 WebFetch 获取搜索结果
- 不要直接构造搜索 API 请求
