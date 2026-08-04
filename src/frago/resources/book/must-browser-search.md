# browser-search

分类: 替代（MUST）

## 是什么
在 frago 环境中搜索信息，必须通过 frago browser navigate 打开 Google 搜索页面，然后用 get-content 提取结果。WebSearch 工具在 frago agent 中不可用/不稳定。

## 怎么用
  frago browser navigate "https://www.google.com/search?q=your+query" --group <name>
  frago browser get-content --group <name> "#search"

`--group <name>` 必带（recipe/run 环境里有 `FRAGO_CURRENT_RUN` 时可省）；缺了直接报错退出。
选择器是**位置参数**，不是 `--selector`——`get-content` 没有这个 flag。

## 什么时候用

适用范畴是**与搜索有关、与使用浏览器有关、与使用网页或网页数据有关的一切行为**，不限于「打开一个网站看内容」这一种形态。判定按行为落在哪个范畴，NEVER 按目的、按页面是本地还是远程、按是否只截一张图来给自己开口子。

落在范畴内的例子：
- 搜索任何信息、查文档与 API 参考、验证在线说法
- 渲染任何 html（含 `file://` 本地文件）、截图、测页面动效、量元素尺寸
- 跑一段 JS、读 DOM、调 CDP、抓页面数据

## 不要做
- 不要使用 WebSearch 工具
- 不要使用 WebFetch 获取搜索结果
- 不要直接构造搜索 API 请求
- 不要自己起浏览器进程（`chrome --headless`、`--screenshot`、`--remote-debugging-port` 等一律禁止），一切经 `frago browser`；端口白名单见 `frago book browser-backend-choice`
