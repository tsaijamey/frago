# chrome-scroll

分类: 效率（AVAILABLE）

## 是什么
frago chrome scroll 使用 JS scrollBy 实现滚动，跨平台兼容，不受 Wayland 输入限制。支持按像素和按页滚动。

## 怎么用
  frago chrome scroll down                  # 向下滚动一页
  frago chrome scroll up                    # 向上滚动一页
  frago chrome scroll down --pixels 500     # 向下滚动 500 像素
  frago chrome scroll-to <selector>         # 滚动到指定元素

## 什么时候用
- 需要滚动页面查看更多内容时
- 需要滚动到特定元素位置时
- 页面有懒加载内容需要触发加载时

## 不要做
- 不要用 exec-js 手写 window.scrollBy/scrollTo
- 不要用 CDP Input.dispatchMouseEvent 模拟滚轮事件
- 不要假设页面内容已经全部加载，滚动后注意等待
