# 架构北极星图

> **本文件描述的是 _目标态_，不是当前态。**
> 当前 `src/frago/` 与下述结构存在偏差，偏差量由 `.importlinter` 契约违规数量化，作为 report-only 债务基线持续跟踪。
> 目标：通过渐进式架构重构清偿既有依赖债务，让契约违规数单调降到 0。

## 设计目标

让任何贡献者或 AI 代理在 5 分钟内能回答：

1. 这段代码该放在哪一层？
2. 这一层允许 import 什么、禁止 import 什么？
3. 哪些是"业务核心"（`domains/`）、哪些是"外部接缝"（`adapters/`）、哪些是"运行时编排"（`runtime/`）？

当前 `src/frago/` 把这三类全混在一个扁平目录里，贡献者或 AI 代理只能靠经验与记忆判断模块归属。北极星图把它们显式分层。

## 分层模型

```
┌────────────────────────────────────────────────────────────┐
│  cli/         — 用户/agent 入口（click 命令、参数解析）       │
├────────────────────────────────────────────────────────────┤
│  server/      — 长进程编排（FastAPI + WebSocket + daemon）   │
│  client/      — 桌面/Web 前端（独立进程，HTTP/WS 通信）       │
├────────────────────────────────────────────────────────────┤
│  domains/     — 业务核心（无外部依赖、无 IO、纯逻辑）          │
│    sync/      — 同步策略与冲突裁决                            │
│    recipes/   — Recipe 解析、合法性、调度                     │
│    sessions/  — 会话语义、消息流转                            │
│    runs/      — Run 生命周期、insights 聚合                  │
│    workspace/ — 部署计划生成（DeploymentPlanner 归属地）      │
├────────────────────────────────────────────────────────────┤
│  adapters/    — 外部世界接缝（一切 IO 在此）                   │
│    llm/       — Claude Code 进程、Codex 进程（外部代理进程）   │
│    chrome/    — 浏览器自动化（cdp + extension 双后端）         │
│    fs/        — 文件系统、git、~/.frago 仓库                  │
│    net/       — HTTP、WebSocket 客户端                        │
├────────────────────────────────────────────────────────────┤
│  core/        — 跨层基础（错误类、类型别名、compat、logging）  │
└────────────────────────────────────────────────────────────┘
```

> 补充说明：`src/frago/ontology/` 为独立操作型本体核心层，承载领域本体定义、自省与运行时治理契约，与 `cli / server / domains / adapters / core` 共同受架构分层依赖契约约束。

## 依赖矩阵（目标态）

行=源，列=目标；✅ 允许 import，❌ 禁止。

|              | cli | server | client | domains | adapters | core |
|--------------|-----|--------|--------|---------|----------|------|
| **cli**      | —   | ✅      | ❌      | ✅       | ✅        | ✅    |
| **server**   | ❌   | —      | ❌      | ✅       | ✅        | ✅    |
| **client**   | ❌   | ❌      | —      | ❌       | ❌        | ❌    |
| **domains**  | ❌   | ❌      | ❌      | ✅       | ❌        | ✅    |
| **adapters** | ❌   | ❌      | ❌      | ❌       | ✅        | ✅    |
| **core**     | ❌   | ❌      | ❌      | ❌       | ❌        | —    |

关键不变量：

- `domains/` 必须可在没有 chrome、没有网络、没有 server 的情况下被纯函数测试。
- `adapters/` 是唯一允许 IO 的层；任何 `subprocess.run` / `requests.get` / 文件系统改写必须在此发生。
- `client/` 与 Python 后端零代码共享，仅通过 HTTP/WS 接口耦合。
- `core/` 不依赖任何上层；其它层都可以依赖 `core/`。

## 演进映射与债务基线说明

下表为现有模块及历史迁移路径向目标态分层的演进对照，配合 `.importlinter` 的 report-only 债务基线使用（部分旧路径为历史迁移映射示例）：

| 现行 / 历史位置 | 目标位置 | 演进目标与基线说明 |
|---|---|---|
| `tools/sync_repo.py`（历史路径；现家目录同步能力归属 `cloud/`） | 拆为 `domains/sync/` + `adapters/fs/git.py` | 历史迁移映射示例：分离冲突裁决逻辑与 Git/文件 IO |
| `tools/deployment_planner.py` | `domains/workspace/planner.py` | 归入工作区纯规划领域逻辑 |
| `tools/workspace.py` | 拆为 `domains/workspace/` + `adapters/fs/` | 分离工作区规则与文件系统操作 |
| `browser/cdp/`, `browser/extension/`, `browser/backends/`（历史路径 `chrome/cdp/`, `chrome/extension/`, `chrome/backends/` 及顶层 `cdp/`） | `adapters/chrome/`（浏览器自动化外部接缝） | 历史迁移映射示例：现行代码已统一收拢至 `browser/`，目标态归入 `adapters/` |
| `recipes/` | 拆为 `domains/recipes/`（解析、合法性）+ `runtime/recipes/`（执行编排） | 分离配方契约校验与运行期编排，清偿对 `server/` 的反向依赖 |
| `session/` | 拆为 `domains/sessions/` + `adapters/fs/sessions_store.py` | 分离会话语义模型与本地持久化存储 |
| `run/` | 拆为 `domains/runs/` + `adapters/fs/runs_store.py` | 分离 Run 生命周期逻辑与落盘存储 |
| `server/services/agent_service.py` | `adapters/llm/claude_code_process.py` | 将外部代理进程封装下沉至 LLM 适配层 |
| `server/services/primary_agent_service.py` | 拆为 `domains/sessions/pa.py` + `adapters/llm/` | 分离主控会话领域语义与外部代理调用 |
| `server/services/*` 其余 | 大多保留在 `server/services/`，重写为薄编排层 | 收敛为薄编排层，下沉领域逻辑与外部 IO |
| `init/`, `compat.py`, `client_manager.py` | `core/` | 归入零上层依赖的跨层基础层 |
| `cli/*_commands.py` | 拆分巨石（`commands.py`），保留在 `cli/` | 按子命令域拆解入口层 |
| `src/frago/ontology/` | 独立操作型本体核心层 | 承载领域本体模型、自省与运行时治理契约，受分层边界契约约束 |

## 命名规范（与北极星图绑定）

- "Agent" 一词专指 _AI agent_（Claude Code、Codex 等外部进程），不可用作纯逻辑类名。
  - 正例：`DeploymentPlanner`、`ClaudeCodeProcess`
  - 反例：`DeploymentAgent`（纯逻辑规划类不应带 Agent 后缀）、`AgentService`（外部进程封装应直接具名为具体进程类）
- "Service" 一词限定为 `server/services/` 下的薄编排层；纯业务逻辑不带 Service 后缀。
- "Manager" 一词谨慎使用，优先具名职责（如 `TabGroupManager` 可接受，`SessionManager` 应拆分为更具体的职责类）。

## 守护机制

- `.importlinter` 配置以本文件为契约源，违规数量化架构技术债务基线。
- 当前以 report-only 模式持续观测债务收敛趋势，待存量循环依赖清偿完毕后切换为 CI 阻断门禁。
- 贡献者或 AI 代理在新增模块前 MUST 对照本文件确认归属层；不确定时，先在 PR 描述写明候选位置 + 一个反例（"为什么不放在 X"）。

## 修订记录

- 2026-05-06：v0 初版，确立目标态分层契约与架构守护基线。
- 2026-11-28：完成公开化修订并迁入 `docs/` 目录，供开源贡献者与架构契约测试共用。
