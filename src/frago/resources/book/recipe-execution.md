# recipe-execution

分类: 效率（AVAILABLE）

## 是什么
frago recipe 系统提供可复用的自动化脚本。执行前先查询可用 recipe，避免重复造轮子。支持同步和异步执行。

## 怎么用
  {{frago_launcher}} recipe list                                            # 查看所有可用 recipe
  {{frago_launcher}} recipe info <name>                                     # 查看 recipe 详情（参数、用法、来源）
  {{frago_launcher}} recipe run <name> --params '{"key": "value"}'          # 同步执行
  {{frago_launcher}} recipe run <name> --params '{"key": "value"}' --async  # 异步执行

## 什么时候用
- 开始一个浏览器自动化任务前，先查看是否已有对应 recipe
- 需要重复执行的操作，应封装为 recipe
- 长时间运行的任务用 --async 异步执行

## 不要做
- 不要直接 python 执行 recipe 脚本文件
- 不要在不查看已有 recipe 的情况下从头写自动化逻辑
- 不要用 2>&1 重定向 recipe 输出（会丢失结构化返回值）
