# 开发者文档

[English](developer.md)

frago 是一个 agent OS。本页面是面向开发者的入口——适用于想使用 CLI 或参与项目开发的人。

## CLI

frago 的命令行界面——相当于操作系统的 shell。桌面客户端能做的，CLI 都能做，还支持浏览器自动化、Recipe 开发和直接控制 agent。

### 快速安装

```bash
# macOS/Linux
curl -fsSL https://frago.ai/install.sh | sh

# Windows
powershell -c "irm https://frago.ai/install.ps1 | iex"
```

详细的环境要求、手动安装和各平台前置条件见 [安装指南](installation.zh-CN.md)。

## 开发环境

```bash
git clone https://github.com/tsaijamey/frago.git
cd frago
uv sync --all-extras --dev
```

## 文档索引

- [安装指南](installation.zh-CN.md) — CLI 安装和各平台前置条件
- [关键概念](concepts.zh-CN.md) — Recipe、Run、Skill 如何协作
- [Recipe 系统](recipes.zh-CN.md) — Recipe 系统详解
- [示例参考](examples.zh-CN.md) — 实际自动化示例
- [浏览器支持](browser-support.zh-CN.md) — 支持的浏览器和 CDP 命令
