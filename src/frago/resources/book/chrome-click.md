# chrome-click

分类: 效率（AVAILABLE）

## 是什么
frago chrome click 默认走 JS element.click()，通过 document capture-phase
listener 自动检测是否生效。未生效时自动 fallback 到坐标级 dispatchMouseEvent。

## 怎么用
  frago chrome click <selector>                    # 默认 JS-first
  frago chrome click <selector> --precise          # 强制坐标级点击
  frago chrome click <selector> --wait-timeout 15  # 自定义等待时间

## 什么时候用 --precise
- 画布点击（Canvas 上没有 DOM 元素）
- 需要精确坐标的拖拽起点
- 注意：Wayland Native 下 --precise 不生成 DOM 事件（已知限制）

## 不要做
- 不要在 recipe.js 里用 CDP Input.dispatchMouseEvent 替代 element.click()
- 不要为了绕 Wayland 问题手动写 JS click，CLI 已经处理了
- 不要用 exec-js "document.querySelector(...).click()" 替代 frago chrome click
