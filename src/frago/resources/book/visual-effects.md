# visual-effects

分类: 效率（AVAILABLE）

## 是什么
frago chrome 提供一组视觉辅助命令，用于在页面上高亮元素、标注信息、指示位置。适合调试、录制演示和截图标注。

## 怎么用
  frago chrome highlight <selector>                    # 高亮元素（红色边框）
  frago chrome pointer <selector>                      # 在元素旁显示指针标记
  frago chrome spotlight <selector>                    # 聚光灯效果，突出元素
  frago chrome annotate <selector> --text "说明文字"   # 添加文字标注
  frago chrome underline <selector>                    # 下划线标记
  frago chrome clear-effects                           # 清除所有视觉效果

## 什么时候用
- 截图前标注需要关注的元素
- 调试时确认选择器是否匹配了正确的元素
- 录制操作演示，需要视觉引导

## 不要做
- 不要用 exec-js 手写 CSS 注入来实现高亮效果
- 不要忘记在截图后 clear-effects（避免影响后续操作）
