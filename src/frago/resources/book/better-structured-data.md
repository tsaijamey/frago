# better-structured-data

分类: 偏好（BETTER）

⚠️ 状态: 开发中 — frago def 命令尚未实现，spec plan 见 20260328-def-structured-knowledge-query.md

## 解决什么问题
agent 从浏览器调研、工具操作中获取的信息，没有统一的结构化存档机制。每次查询靠 grep 文件，token 开销是 O(文件数 × 文件大小)。def 将提供 O(结果集 × 字段数) 的精确输出。

## 设计意图
- agent 能自己定义信息类别（frago def add）
- 每个类别自动生成 find / schema / save 子命令
- find 支持字段筛选、投影、排序、聚合
- 信息密度优先：命令输出的每个 token 都是有效决策信息

## 当前替代方案
在 def 实现之前，使用以下方式存取结构化数据：
- frago run log --data '{"key": "value"}' — 结构化日志
- workspace/outputs/ 下的 JSON 文件 — 任务产出物
- frago recipe run — 通过 recipe 参数传递数据
