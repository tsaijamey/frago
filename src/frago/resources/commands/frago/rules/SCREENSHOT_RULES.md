# 截图使用规范（强制执行）

适用于：`/frago.run`、`/frago.do`、`/frago.recipe`、`/frago.test`

## ⛔ 核心禁令（违反即任务失败）

> **禁止使用截图获取网页文字内容。必须使用 `get-content` 或配方提取。**

截图转文字效率低、易出错、丢失结构化信息。这是**硬性禁止**，不是建议。

## 导航后必须执行的流程

```
1. frago chrome navigate <url>    ← 导航
2. frago recipe list | grep xxx   ← 检查是否有现成配方
3. frago chrome get-content       ← 无配方时用此命令获取内容
4. （可选）frago chrome screenshot ← 仅用于验证状态，禁止用于阅读
```

## 场景强制对照表

| 场景 | ✅ 必须这样做 | ⛔ 禁止这样做 |
|-----|-------------|-------------|
| 获取推文/帖子内容 | `frago chrome get-content` 或配方 | 截图后让 AI "阅读" |
| 获取评论列表 | `frago chrome get-content` 或配方 | 截图整个评论区 |
| 获取页面任何文字 | `frago chrome get-content` 或 `exec-js` | 截图后让 AI "阅读" |
| 获取 DOM 结构 | `frago chrome exec-js` 提取 | 截图整个页面 |

## 截图的唯一合法用途

- ✅ **验证状态**：确认导航成功、元素已加载
- ✅ **调试定位**：排查元素定位失败
- ✅ **视觉备份**：记录元素位置（防重排）

## 自检问题

在使用 `frago chrome screenshot` 前必须回答：

> "我是否打算用这张截图来阅读页面内容？"
> - 如果是 → **禁止截图**，改用 `frago chrome get-content`
> - 如果否 → 可以截图

## 截图命令

```bash
# 基本截图
frago chrome screenshot output.png

# 全屏截图
frago chrome screenshot output.png --full-page

# 在 run 上下文中截图（自动保存到 screenshots/）
frago run screenshot "步骤描述"
```
