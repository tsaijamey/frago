# must-content-extraction

分类: 替代（MUST）

## 解决什么问题
agent 习惯截图然后让 AI "读"页面文字，低效、易错、丢失结构信息。必须用 get-content 或 recipe 提取文字内容。

## 导航后的标准操作序列

  1. frago chrome navigate <url>
  2. frago recipe list | grep xxx          # 检查是否有现成 recipe
  3. frago chrome get-content              # 无 recipe 时用这个
  4. frago chrome screenshot               # 仅用于验证状态，不用于阅读

## 场景对照

| 场景 | 正确做法 | 禁止做法 |
|------|----------|----------|
| 获取推文/帖子内容 | get-content 或 recipe | 截图让 AI "读" |
| 获取评论列表 | get-content 或 recipe | 截图整个评论区 |
| 获取任何页面文字 | get-content 或 exec-js | 截图让 AI "读" |
| 获取 DOM 结构 | exec-js 提取 | 截图整个页面 |

## 截图的合法用途

- 验证状态：确认导航成功、元素已加载
- 调试定位：排查元素定位失败
- 视觉备份：记录元素位置（防回流）

## 自检问题

使用 frago chrome screenshot 前必须回答：

> "我是否打算用这张截图来读取页面内容？"
> - 是 → 不要截图，用 frago chrome get-content
> - 否 → 可以截图

## 截图命令

  frago chrome screenshot output.png                        # 基本截图
  frago chrome screenshot output.png --full-page            # 全页截图
  frago run screenshot "step description"                   # Run 上下文中（自动存到 screenshots/）
