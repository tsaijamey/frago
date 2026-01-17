---
id: getting-started
title: 开始使用
category: getting-started
order: 1
version: 0.38.1
last_updated: 2026-01-17
tags:
  - beginner
  - first-time
  - quick-start
---

# 开始使用

## Q: 我刚装完frago，进入了Web UI，现在该从哪开始？

**A**: 建议按以下步骤开始：

1. **先看看有什么现成的配方** → 点击左侧"Recipes"
   - 切换到"Community"标签，浏览社区配方
   - 配方是标准化的自动化任务定义，比如"提取YouTube字幕"
   - 找到感兴趣的配方，点进去查看它能做什么

2. **如果你想让AI帮你做事** → 点击左侧"Console"
   - 在输入框里直接说你想做什么
   - 比如："帮我提取这个网页的内容"
   - AI会自动完成并告诉你结果

3. **执行确定性任务** → 点击左侧"Tasks"
   - 运行已有的Recipe配方
   - 执行不需要调整路线的自动化任务

**💡 提示**: 新手建议先从社区配方开始，找一个感兴趣的配方体验一下frago的能力。

---

## Q: 左侧菜单这么多，每个是干什么的？

**A**: 以下是各个菜单项的功能说明：

- **Dashboard（仪表盘）**: 系统总览
  - 服务器运行状态、运行时长
  - 最近6小时活动统计图表
  - Tasks/Recipes/Skills数量总览

- **Console（控制台）**: Recipe开发专用
  - 自动批准所有操作（文件读写、命令执行等）
  - 无需等待确认，AI直接执行
  - ⚠️ 警告：所有操作自动执行，小心使用

- **Tasks（任务）**: 确定性任务执行
  - 运行已有Recipe或标准化任务
  - 适合不需要中途调整的任务
  - 输入提示或选择配方即可执行

- **Recipes（配方）**: 配方管理中心
  - 浏览本地配方和社区配方
  - 查看配方参数、使用场景、示例
  - 一键运行，填参数即可

- **Skills（技能）**: 方法论文档（进阶）
  - 告诉AI"如何做某类任务"
  - 与Recipe配合使用
  - 新手可以先忽略

- **Workspace（工作空间）**: 项目文件浏览器
  - 查看Run项目目录
  - 浏览日志、截图、输出文件
  - 文件预览功能

- **Sync（同步）**: 跨设备同步
  - 设置Git仓库
  - 同步Recipes和Skills到其他机器
  - 单机使用不需要配置

- **Secrets（密钥）**: 敏感信息管理
  - 存储API keys
  - Recipe可以安全引用
  - 环境变量配置

- **Settings（设置）**: 配置中心
  - API Key配置
  - Model Override（切换Claude模型）
  - 外观设置：主题、语言

---

## Q: 我想试试frago，推荐一个最简单的任务？

**A**: 推荐运行 `test_inspect_tab` Recipe，这是最简单的测试。

**步骤**:
1. 点击左侧"Recipes"
2. 在搜索框输入"test"或直接找到 `test_inspect_tab`
3. 点击进入详情页面
4. 点击"Run"按钮
5. 等几秒，查看输出结果

**这个Recipe做什么**:
- 检查当前浏览器标签页的信息（标题、URL、DOM统计）
- 不会修改任何内容，完全安全
- 帮助你了解Recipe的执行流程

**看到结果后**:
- 你会看到当前页面的标题、URL等信息
- 这说明frago的Chrome自动化功能正常工作
- 可以尝试其他更复杂的Recipes

---

## Q: 教程里提到的"Claude Code"是什么？

**A**: Claude Code是Anthropic官方的CLI工具，frago配合它使用效果最佳。

**Claude Code CLI vs frago Web UI**:

| 特性 | Claude Code CLI | frago Web UI |
|------|----------------|--------------|
| 交互方式 | 命令行 | 浏览器界面 |
| 工具批准 | 手动确认每个操作 | 自动批准（Console） |
| 适用场景 | 敏感项目、需要控制 | 快速开发、可视化 |
| 学习曲线 | 需要熟悉命令行 | 直观易用 |

**frago的独特价值**:
- 即使不用Claude Code CLI，frago Web UI也可以独立使用
- Web UI提供可视化界面和Recipe管理
- Console模式适合快速开发和测试Recipes
- Tasks模式用于执行确定性自动化任务

**如何配合使用**（可选）:
```bash
# 在CLI中使用frago命令
/frago.run 研究如何提取YouTube字幕
/frago.recipe 创建一个提取字幕的recipe
/frago.test youtube_extract_video_transcript
```

**新手建议**: 先熟悉frago Web UI，CLI可以以后再研究。
