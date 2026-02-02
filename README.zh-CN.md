# frago

**AI Agent 的骨架框架** — 让 AI 记住如何完成任务，而不是每次从头探索。

[English](README.md)

## 为什么选择 frago

AI Agent 很聪明，但不可预测。同样的任务问 10 次，可能得到 10 种不同的结果——有的成功，有的失败。

frago 用 **Recipe 系统** 解决这个问题：经过验证的自动化脚本，确定性执行。一旦 Recipe 能用，它就一直能用。

**确定性执行。这才是关键。**

> 与 Anthropic 的 ["Code execution with MCP"](https://www.anthropic.com/engineering/code-execution-with-mcp) 理念相同：确定性代码优于反复 LLM 探索。frago 用 Recipe 而非 MCP。

## 产品对比

| | **Cowork** | **OpenClaw** | **frago** |
|--|------------|--------------|-----------|
| **最适合** | 非技术用户的文件管理 | 多渠道消息自动化 | 可复用自动化 + Claude Code |
| **记忆** | 无（每次会话都是新的） | 跨对话上下文 | **Recipe 系统**（经验证的脚本） |
| **可靠性** | AI 每次都在探索 | 因任务而异 | **确定性**（Recipe = 有保障） |
| **平台** | macOS（计划支持 Windows） | 任意操作系统 | Windows / macOS / Linux |
| **价格** | $20-200/月订阅 | 免费 + API 成本 | **免费 & 自托管** |
| **技术底盘** | Claude Agent SDK | Pi agent + 多渠道 | **Claude Code**（Anthropic 旗舰） |
| **数据** | Anthropic 云端 | 本地优先 | **100% 本地** |

**根据你的需求选择：**
- **Cowork** — 优秀的用户体验，适合整理文件，非开发者友好
- **OpenClaw** — 强大的多渠道收件箱（WhatsApp、Telegram、Slack...）
- **frago** — 确定性的浏览器自动化，深度集成 Claude Code

## 快速开始

```bash
uv tool install frago-cli   # 安装
frago init                   # 初始化
frago server start           # 启动 Web UI → http://127.0.0.1:8093
```

> 不熟悉 `uv`？查看[安装指南](docs/installation.zh-CN.md)。

## 环境要求

| 依赖 | 版本 |
|------|------|
| Python | 3.13+ |
| Node.js | 20+ |
| Chrome | 最新版 |

## 工作原理

frago 通过 Claude Code slash commands 集成：

```
/frago.run     探索研究，积累经验
     ↓
/frago.recipe  将经验固化为可复用配方
     ↓
/frago.test    验证配方（趁上下文还在）
```

### Recipe 的优势

```
AI 探索：     不可预测——可能成功，可能失败，可能走错路
                      ↓
              一旦成功 → 保存为 Recipe
                      ↓
Recipe 执行：  确定性——经验证的脚本，结果有保障
```

**Recipe = 肌肉记忆。不用思考，直接执行。**

## 核心系统

| 系统 | 用途 |
|------|------|
| **Recipe** | 可复用自动化脚本（chrome-js/python/shell） |
| **Run** | 持久化任务上下文，JSONL 日志 |
| **CDP** | 原生 Chrome 控制（~2MB，无 Node.js 中继） |
| **Web UI** | 浏览器端 GUI（端口 8093） |

## CLI 命令

```bash
# Recipe 管理
frago recipe list              # 列出所有配方
frago recipe run <name>        # 执行配方

# 浏览器控制
frago chrome navigate <url>
frago chrome click <selector>
frago chrome screenshot <file>

# 服务
frago server start/stop/status
```

## 文档

- [安装指南](docs/installation.zh-CN.md) — 安装和前置条件
- [使用指南](docs/user-guide.zh-CN.md) — 命令和用法
- [关键概念](docs/concepts.zh-CN.md) — Run、Recipe、Skill 关系
- [技术架构](docs/architecture.zh-CN.md) — 技术设计
- [Recipe 系统](docs/recipes.zh-CN.md) — Recipe 系统深入

## 资源同步

跨设备同步你的配方：

```bash
frago sync --set-repo git@github.com:you/my-resources.git
frago sync  # 双向同步
```

## 许可证

AGPL-3.0 — 详见 [LICENSE](LICENSE)

## 贡献

- [提交 Issue](https://github.com/tsaijamey/Frago/issues)
- [技术讨论](https://github.com/tsaijamey/Frago/discussions)

---

Created with Claude Code
