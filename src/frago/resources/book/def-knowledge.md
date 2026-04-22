# def-knowledge

分类: 效率（AVAILABLE）

frago def 是结构化知识系统。你可以定义知识领域（domain），在领域下保存和查询知识文档。

## 查看已有知识

```bash
{{frago_launcher}} def list                           # 列出所有领域及文档数
{{frago_launcher}} <domain> find                      # 列出领域下所有文档（多文档=表格）
{{frago_launcher}} <domain> find -- --name=<doc>      # 查看单文档完整内容（自动展开 entries）
{{frago_launcher}} <domain> find -- --tags=<value>    # 按标签筛选
{{frago_launcher}} <domain> find --count              # 只看数量
{{frago_launcher}} <domain> schema                    # 查看字段定义
```

## 保存知识

每条知识用关系标记格式：`[[[关系类型]]][[内容A]][[内容B]]`

四种关系类型：
- `[[[cause]]][[A]][[B]]` — A 导致 B
- `[[[sequence]]][[A]][[B]]` — 先 A 再 B
- `[[[exception]]][[A]][[B]]` — 通常 A，但某些情况 B
- `[[[constraint]]][[A]][[B]]` — A 的限制/约束是 B

```bash
{{frago_launcher}} <domain> save --name=<doc-name> \
  --data='{"tags": ["tag1", "tag2"]}' \
  --content '["[[[cause]]][[ProseMirror 拦截 DOM 变更]][[innerHTML 赋值不触发]]", "[[[sequence]]][[focus 元素]][[Input.insertText]]"]'
```

- --name: 文档名（必填），已存在则更新（upsert）
- --data: frontmatter 字段（JSON），如 tags
- --content: 知识条目数组（JSON array），每条带关系标记。无标记的纯字符串归为 misc

## 注册新领域

```bash
{{frago_launcher}} def add <name> \
  --purpose "领域用途描述" \
  --schema '{"fields": [{"name": "name", "type": "string", "required": true, "description": "主题名"}, {"name": "tags", "type": "list", "required": false, "description": "标签"}]}'
```

## 规则
- 查询知识用 frago def 命令，NEVER 直接 Read ~/.frago/books/ 下的文件
- 保存前先 `{{frago_launcher}} def list` + `{{frago_launcher}} <domain> find` 确认已有内容，避免重复
- 能归入已有领域就不新建领域
