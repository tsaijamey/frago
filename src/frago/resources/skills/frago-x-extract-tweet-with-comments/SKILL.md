---
name: frago-x-extract-tweet-with-comments
description: Twitter/X 推文及评论提取与内容生产指南。当用户提到 "Twitter 视频"、"推特观点"、"X 评论视频"、"网友观点视频" 或明确指定此 skill 时使用。涵盖素材收集、观点整理、朗读稿生成的内容生产流程。
---

# X Extract Tweet with Comments - 内容生产指南

围绕特定主题收集 Twitter/X 上的 posts 和 comments，整理网友观点并加入主持人评论，生成朗读稿。

## ⚠️ 核心原则：文档输出导向

**此 skill 的产出为后续环节服务，所有过程必须以文件形式留痕。**

1. **禁止仅在 response 中展示** - 每个阶段的结果必须写入对应的 `outputs/` 文件
2. **增量保存** - 每收集/整理一批内容，立即写入文件，不要等到最后
3. **可追溯** - 所有内容必须标注真实来源（URL），确保后续可验证
4. **模板仅供格式参考** - 占位符必须替换为真实内容，禁止复制示例文本

---

## 生产流程

| 阶段 | 任务 | 产出物 | 人工介入 |
|-----|------|-------|---------|
| 1. 素材收集 | 在 X 上搜索/浏览，增量记录素材 | `01_draft.jsonl` | - |
| 2. 提取整理 | 分类观点，与用户探讨"我"的观点 | `02_content_draft.md` | - |
| 3. 朗读稿生成 | 生成正式的朗读稿文本 | `03_narration.md` | 调整朗读稿内容 |

---

## 阶段 1: 素材收集

**产出物**：`outputs/01_draft.jsonl`，增量记录所有素材。

**原则**：宁多勿缺，漏记的素材后续无法追溯。

**01_draft.jsonl 字段**：`type`(tweet/comment), `url`, `author`, `content`, `scroll_to_text`, `parent_url`(comment必填)

格式示例见 [templates/01_draft.jsonl](templates/01_draft.jsonl)

### ⚠️ 关键约束（必须遵守）

1. **禁止复制模板示例内容** - 模板仅供格式参考，每条记录必须是实际收集的素材
2. **URL 必须真实** - 从浏览器地址栏或 DOM 中获取，**严禁编造或使用占位符**
3. **开始收集前清空产出文件** - 确保 `outputs/01_draft.jsonl` 不包含旧数据或模板内容

### 截图使用规范

**原则**：少用截图，多用配方提取内容。

| 用途 | 正确 | 错误 |
|-----|------|------|
| 获取内容 | `x_extract_*` 配方 | 截图让 AI "阅读" |
| 验证状态 | 截图检查 | - |
| 备份位置 | 截图（评论可能重排） | - |

---

## 阶段 2: 提取整理

从 `01_draft.jsonl` 提取素材，分类整理，与用户探讨"我"的观点。

**产出物**：`outputs/02_content_draft.md`，包含分类观点和"我的评论"。

模板见 [templates/02_content_draft.md](templates/02_content_draft.md)

查询命令：`cat outputs/01_draft.jsonl | jq 'select(.type=="tweet")'`

---

## 阶段 3: 朗读稿生成

根据 `02_content_draft.md` 生成正式的朗读稿。

**产出物**：`outputs/03_narration.md`

模板见 [templates/03_narration.md](templates/03_narration.md)

**风格要求**：
- 口语化、语言节奏明快
- 直接进入主题，不要自我介绍
- 开场用一句有冲击力的 Hook 抓住注意力

**人工操作**：调整朗读稿内容，确保表达自然流畅。

---

## 常见问题

| 问题 | 解决方案 |
|-----|---------|
| 找不到目标元素 | 使用更长的文本片段 |
| 评论位置变化 | 收集时截图备份 |

---

## 参考文档

- Twitter 元素特征和选择器：[REFERENCE.md](REFERENCE.md)
- Frago CDP 命令：`uv run frago --help`
