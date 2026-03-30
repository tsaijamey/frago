# scene-recipe-development

场景类型: Recipe 开发

## 问题特征
把一个手动操作流程固化为可复用的 Recipe 脚本。通常在成功完成几次手动操作后，提炼为自动化。

## 典型触发
- 重复操作超过 2 次
- 用户明确要求创建 Recipe
- Run 日志中积累了足够的 _insights（ready_for_recipe: true）

## 推荐路径

  1. frago run find <recipe 关键词>             # 搜索历史类似任务
  2. frago recipe list                         # 确认不存在类似 recipe
  2. 回顾 Run 日志中的 _insights
  3. 确定 Recipe 类型（atomic / workflow）
  4. 确定 runtime（chrome-js / python / shell）
  5. 按 recipe-fields 规范写 recipe.md
  6. 写 recipe.js/py/sh 实现脚本
  7. frago recipe validate <path>              # 校验
  8. frago recipe run <name> --params '...'    # 测试

## 关键约束
- recipe-fields — 必填字段、schema 规范
- selector-priority — JS recipe 中的选择器稳定性
- must-tool-priority — Recipe 在工具优先级最高层
- interactive-recipe — 需要人机协作时的架构模式

## 常见陷阱
- 跳过 validate 直接 run → 格式错误运行时才暴露
- 选择器用脆弱 class → Recipe 几天后失效
- 不写 fallback selector → 页面小改就整个 recipe 挂掉
- workflow recipe 忘记声明 dependencies → 子 recipe 找不到
