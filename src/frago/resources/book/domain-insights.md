# domain-insights

分类: 效率（AVAILABLE）

## 一句话：这套形态已退役，别再用

`run insights` 这一整套已经退役——写入口于 2026-07-26 关闭，读入口随后一并撤掉。
知识沉淀与查询的唯一形态是 def 领域文档。本章只保留退役说明和迁移指引。

## 现在往哪沉淀、往哪查

    frago def list                          # 有哪些知识域
    frago <域名> find                        # 该域已沉淀了什么
    frago <域名> find -- --name=<文档名>      # 看单篇详情
    frago <域名> save --name=<文档名> --data='{...}' --content='[...]'   # 沉淀新知识

跨域找落盘产出走 `frago context data:<关键词>`，翻历史会话原文走
`frago session search "<一句话>"`。详见 `frago book def-knowledge`。

## 为什么退役

同一件事的知识过去被劈成两半：一半是 `<域> save` 写的 books 结构化文档，一半是
`run insights` 写的 projects 流水。两套域名几乎不相交（30 个 def 域 vs 60 个 insight
域，只有 8 个同名），谁也召不回谁。写入端有 hook 天天催记，读取端却没有任何自动通道，
攒了几个月的知识没人读得到。

留着两个写入口，就是持续制造第二套散落知识。所以收敛到一套，写入口封死，
读入口也没有再留的理由。

## 历史数据在哪

1355 条历史 insight 里，797 条是 2026-04-26 一次性迁移脚本自动回填的
`Legacy run: <run名>` 占位行（只是"某次跑过某任务"的存在标记，不是知识），
真知识 558 条。

这 558 条已按主题聚类改写成 276 篇 def 文档，分布在 20 个域里，逐域经独立盲测验收。
用 `frago <域名> find` 就能查到。

原始 jsonl 仍躺在 `~/.frago/projects/{domain}/insight.jsonl`，
另有三层留底一个字节没删：

    ~/.frago/_archive/insight-migration-20260726-003044/

这两处都只是留底位置，不是查询入口——真要查知识，走 `frago <域名> find`。
