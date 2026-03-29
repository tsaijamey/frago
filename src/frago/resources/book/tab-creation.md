# tab-creation

分类: 替代（MUST）

## 是什么
打开新 URL 必须通过 frago chrome navigate 命令。直接使用 window.open()、raw CDP Target.createTarget 或其他方式会导致 tab 追踪丢失，后续操作无法定位正确的 tab。

## 怎么用
  frago chrome navigate "https://example.com"              # 在当前 tab 打开
  frago chrome navigate "https://example.com" --new-tab    # 在新 tab 打开

## 什么时候用
- 需要打开任何 URL 时
- 需要在新 tab 中打开页面时
- 在 recipe 中需要导航到新页面时

## 不要做
- 不要用 exec-js "window.open('url')"
- 不要用 CDP Target.createTarget 直接创建 tab
- 不要在 recipe.js 中用 window.location.href = 'url'
