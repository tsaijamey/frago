# frago-principle-os

分类: 第一性原理（AVAILABLE）

## 解决什么问题
agent 不知道 frago 是什么品类的东西，会按"普通 CLI 工具"对待——缺少 frago 应当被赋予的特殊地位（agent 的运行环境，而非 agent 的对手或助手）。这条原则把 frago 的定位说清楚。

## 第一性原理

frago = **agent OS**，AI agent 的操作系统。

frago 不造 agent。agent 指 Claude Code / Codex 等外部 agent，frago 为它们提供"可运行的环境"——agent 知道怎么做、用什么操作、如何扩展自己的操作能力、如何沉淀复用经验。

## 四个支柱

| 能力维度 | frago 提供 |
|---------|-----------|
| agent 知道怎么做（行为约束、路由、规则）        | frago-hook |
| agent 用什么操作（标准化命令入口）              | frago 系列命令（chrome / recipe / server / sync / run / view ...） |
| agent 如何扩展操作能力（结构化知识 + 自定义命令） | frago def / frago def 定义的命令 |
| agent 如何沉淀和复用工作流                      | frago recipe |

## 不在 agent 视野里的部分

frago 也有 Web UI、桌面客户端、跨设备同步——但**那些是给人用的**，不是给 agent 用的。agent 通过四个支柱看见 frago，UI 这层不归 agent 管。

## agent OS 是个什么品类

业界没有标准定义。frago 是这个定义的一次具体落地。所以：
- 不要按"自动化工具"理解 frago（它不只是 RPA）
- 不要按"Claude Code 的封装"理解 frago（它不依赖某个具体 agent）
- 按"操作系统支持多种应用程序"那个比喻理解——agent 是跑在 frago 上的"应用"
