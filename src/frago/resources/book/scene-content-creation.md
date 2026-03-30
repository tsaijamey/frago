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

  1. frago run init "内容创作主题"
  2. 素材调研阶段（参考 scene-web-research）
  3. frago run log --step "素材整理" --data '{"_insights": [...]}'
  4. 创作阶段：产出文件写入 workspace/outputs/
  5. frago view outputs/result.md              # 预览产出
  6. frago run release

## 关键约束
- must-workspace — 所有产出文件在 workspace 内
- must-execution-principles — 产出可用结果，不停在计划
- run-logging — 记录创作过程中的关键发现和决策

## 常见陷阱
- 不做调研直接写 → 内容空洞、数据不准
- 产出文件散落各处 → 用户找不到
- 只给计划不给成品 → 用户要的是可用结果
