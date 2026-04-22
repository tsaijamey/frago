# better-structured-data

分类: 偏好（BETTER）

结构化数据存取用 {{frago_launcher}} def 系统，比手写 JSON 或 grep 文件更高效。

## 核心命令

```bash
{{frago_launcher}} def list                           # 查看已有知识领域
{{frago_launcher}} <domain> find                      # 列出领域下所有文档
{{frago_launcher}} <domain> find -- --name=<doc>      # 查看单个文档完整内容
{{frago_launcher}} <domain> save --name=<doc> \
  --data='{"tags": ["a", "b"]}' \
  --content '["knowledge entry 1", "entry 2"]'
```

## 何时使用 def 而非直接写文件
- 需要按领域组织、按字段筛选的知识 → {{frago_launcher}} def
- 一次性任务产出 → workspace/outputs/
- 运行时日志 → {{frago_launcher}} run log
