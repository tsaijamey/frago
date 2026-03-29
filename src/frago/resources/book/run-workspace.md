# run-workspace

分类: 偏好（BETTER）

## 是什么
frago run workspace 是每个 Run 实例的专属工作目录，用于存放任务执行过程中的产出物（截图、数据、日志等）。产出物放在 workspace 里，方便归档、审计和后续引用。

## 怎么用
  frago run workspace                  # 查看当前 Run 的 workspace 路径
  frago run workspace --open           # 打开 workspace 目录

  # 在任务中，将产出物保存到 workspace
  # workspace 路径通常为 ~/.frago/projects/<run-id>/

## 什么时候用
- 保存截图、导出数据、生成报告时
- 需要在任务步骤之间共享文件时
- 需要保留可追溯的执行记录时

## 不要做
- 不要把产出物保存到 /tmp 或随机目录
- 不要把产出物保存到用户的 home 目录根下
- 不要在任务结束后忘记记录产出物的位置
