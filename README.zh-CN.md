# frago

**AI agent 的操作系统** — 让 AI agent 在你的电脑上运行，替你完成重复性工作。

> frago 与 OpenClaw（龙虾）无关。frago 的启动时间早于 OpenClaw 约一个月。

[English](README.md)

## 为什么选择 frago

**安装简单，轻松配置。** 客户端只有约 2MB，下载后自动完成环境检查和安装。配好一个 AI 大模型，立刻就能开始用。不需要终端，不需要配环境，不需要手动装依赖。

每天花几个小时在电脑上做那些机器本来就能做的事——填表格、从网站拉数据、搬运文件。AI agent 已经有能力做这些了，但它们被锁在终端和命令行后面，大多数人用不了。

frago 给 AI agent 一个运行的地方，给你一个观看和控制它们的窗口。描述你的需求，frago 搞定剩下的。

AI 摸索出一套做法后，frago 会保存这些步骤，下次同样的事一键就行——不再需要 AI 重新来过。

## 开始使用

下载安装：

| 平台 | 下载 |
|------|------|
| **macOS (Apple Silicon)** | [.dmg](https://github.com/tsaijamey/frago/releases/latest) |
| **macOS (Intel)** | [.dmg](https://github.com/tsaijamey/frago/releases/latest) |
| **Windows** | [.msi](https://github.com/tsaijamey/frago/releases/latest) |
| **Linux (deb)** | [.deb](https://github.com/tsaijamey/frago/releases/latest) |
| **Linux (rpm)** | [.rpm](https://github.com/tsaijamey/frago/releases/latest) |
| **Linux (AppImage)** | [.AppImage](https://github.com/tsaijamey/frago/releases/latest) |

> 所有下载见 [Releases 页面](https://github.com/tsaijamey/frago/releases/latest)。

## 工作原理

```
你描述任务
    ↓
AI 替你完成
    ↓
下次同样的事 → 一键搞定
```

为什么"一键"能行？AI 完成任务后，会把走通的步骤保存为可执行的代码。这段代码每次运行结果都一样——不需要 AI 重新思考，没有随机性，也不消耗 token。这些保存下来的流程，我们称之为 **Recipe**（配方）。

Recipe 是 frago 为自己打造的"软件"。和提示词、指令不同，Recipe 是真正的代码，确定性执行。Recipe 还能跨任务复用——AI 学会了登录某个网站，这个 Recipe 就能成为任何需要登录操作的任务的构建模块。

## 文档

- [使用指南](docs/user-guide.zh-CN.md) — 安装后的入门指引
- [关键概念](docs/concepts.zh-CN.md) — Recipe、Run、Skill 如何协作
- [开发者文档](docs/developer.zh-CN.md) — CLI、架构和技术细节

## 许可证

AGPL-3.0 — 详见 [LICENSE](LICENSE)

## 贡献

- [提交 Issue](https://github.com/tsaijamey/Frago/issues)
- [技术讨论](https://github.com/tsaijamey/Frago/discussions)

---

Created with Claude Code
