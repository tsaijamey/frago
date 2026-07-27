# domain-insights

分类: 效率（AVAILABLE）

## 一句话：这套形态已退役，别再用

`{{frago_launcher}} run insights --save` / `--update` 已于 2026-07-26 关闭，敲了会直接报错。
知识沉淀的唯一形态是 def 领域文档。本章只保留退役说明和迁移指引。

## 现在往哪沉淀

    {{frago_launcher}} def list                          # 有哪些知识域
    {{frago_launcher}} <域名> find                        # 该域已沉淀了什么
    {{frago_launcher}} <域名> find -- --name=<文档名>      # 看单篇详情
    {{frago_launcher}} <域名> save --name=<文档名> --data='{...}'   # 沉淀新知识

详见 `{{frago_launcher}} book def-knowledge`。

## 为什么退役

同一件事的知识过去被劈成两半：一半是 `<域> save` 写的 books 结构化文档，一半是
`run insights` 写的 projects 流水。两套域名几乎不相交（30 个 def 域 vs 60 个 insight
域，只有 8 个同名），谁也召不回谁。写入端有 hook 天天催记，读取端却没有任何自动通道，
攒了几个月的知识没人读得到。

留着两个写入口，就是持续制造第二套散落知识。所以收敛到一套，写入口封死。

## 历史数据在哪

1355 条历史 insight 里，797 条是 2026-04-26 一次性迁移脚本自动回填的
`Legacy run: <run名>` 占位行（只是"某次跑过某任务"的存在标记，不是知识），
真知识 558 条。

这 558 条已按主题聚类改写成 276 篇 def 文档，分布在 20 个域里，逐域经独立盲测验收。
用 `{{frago_launcher}} <域名> find` 就能查到。

原始文件三层留底，一个字节没删：

    ~/.frago/_archive/insight-migration-20260726-003044/

## 只读入口仍然可用

历史 jsonl 还在，需要查原文时：

    {{frago_launcher}} run insights                                  # 当前 domain 全部
    {{frago_launcher}} run insights --query "API 限流"                # payload 全文搜
    {{frago_launcher}} run insights --domain twitter --format json   # 指定域 + JSON

跨 domain 全文搜：`{{frago_launcher}} run find <keyword>`。

## 操作流水去哪了

没变。执行日志仍走 `{{frago_launcher}} run log` 写 `execution.jsonl`，
详见 `{{frago_launcher}} book run-logging`。退役的只是领域知识那一层。
