# scene-form-automation

场景类型: 表单自动化

## 问题特征
需要在网页上填写表单、选择下拉选项、勾选复选框、提交数据。可能涉及多步流程。

## 典型触发
- 在管理系统中创建任务/工单
- 注册账号、填写申请
- 批量提交数据
- 多步表单向导

## 推荐路径

  1. frago run find <表单关键词>                # 搜索历史类似任务
  2. frago recipe list | grep form            # 检查已有表单 recipe
  2. frago chrome navigate <目标页面>
  3. frago chrome get-content                  # 了解页面结构
  4. frago chrome exec-js "提取表单字段" --return-value
  5. 逐字段填写，每步验证
  6. frago chrome screenshot verify.png        # 提交前截图确认

## 关键约束
- selector-priority — 优先 aria-label/data-testid，避免脆弱 class
- chrome-click — React 等框架需要 JS 赋值 + 触发 input 事件
- must-navigation — 不要猜测表单提交后的跳转 URL

## 常见陷阱
- 直接 setValue 不触发 React onChange → 表单验证失败
- 用 CSS class 定位下拉选项 → 动态生成 class 导致定位失败
- 填完不验证就提交 → 字段遗漏或格式错误
- 多步表单中间步骤不截图 → 出错后无法定位是哪步的问题
