# scene-recipe-development

场景类型: Recipe 开发

## 问题特征
把一个手动操作流程固化为可复用的 Recipe 脚本。通常在成功完成几次手动操作后，提炼为自动化。

## 典型触发
- 重复操作超过 2 次
- 用户明确要求创建 Recipe
- 同一套手动流程已经跑通过几次，坑和关键决策都摸清了

## 推荐路径

  1. frago context data:<recipe 关键词>         # 找历史落盘产出
  2. frago session search "<一句话说清要找什么>"  # 按意思翻历史会话
  3. frago recipe list                         # 确认不存在类似 recipe
  4. frago <域名> find                          # 回顾这套流程已沉淀的坑与决策
  5. frago recipe plan <name> --prompt "..."   # 生成 spec.md（需求定义）
  6. 审阅 spec.md，必要时手动修改
  7. frago recipe create <name>                # 根据 spec 生成代码 + 自动 validate
  8. frago recipe run <name> --params '...'    # 测试

简单 recipe 可跳过 plan，直接一步创建：
  frago recipe create <name> --prompt "..."

第 5 步和第 7 步 MUST 后台跑（Bash 工具 `run_in_background: true`）：两条命令都
阻塞在一个 worker 上，认真的任务书要写十几到几十分钟，而前台命令有 10 分钟硬
上限，砍掉的只是 CLI、worker 还在写同一个目录。详见 recipe-creation。

## 关键约束
- recipe-fields — 必填字段、schema 规范
- browser-usage — JS recipe 中的选择器稳定性与交互规范
- must-tool-priority — Recipe 在工具优先级最高层
- interactive-recipe — 需要人机协作时的架构模式

## 常见陷阱
- 跳过 validate 直接 run → 格式错误运行时才暴露
- 选择器用脆弱 class → Recipe 几天后失效
- 不写 fallback selector → 页面小改就整个 recipe 挂掉
- workflow recipe 忘记声明 dependencies → 子 recipe 找不到
