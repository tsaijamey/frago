# scene-content-creation

场景类型: 内容创作

## 问题特征
生成文档、演示文稿、视频脚本、文章等内容产出物。通常需要先调研素材，再组织创作。

## 典型触发
- 写文章、公众号内容
- 制作演示文稿
- 生成视频脚本
- 整理报告

## 推荐路径

  1. frago context data:<创作关键词>            # 找历史落盘产出
  2. frago session search "<一句话说清要找什么>"  # 按意思翻历史会话
  3. 素材调研阶段（参考 scene-web-research）
  4. 创作阶段：产出文件写入 ~/.frago/data/<主体>/<YYYYMMDD>-<slug>/
  5. frago view ~/.frago/data/<主体>/<YYYYMMDD>-<slug>/result.md   # 预览产出

## 关键约束
- must-data-dir — 所有产出文件在 ~/.frago/data/<主体>/<YYYYMMDD>-<slug>/ 内
- must-execution-principles — 产出可用结果，不停在计划

## 常见陷阱
- 不做调研直接写 → 内容空洞、数据不准
- 产出文件散落各处 → 用户找不到
- 只给计划不给成品 → 用户要的是可用结果
