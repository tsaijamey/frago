# frago-principle-extend

分类: 第一性原理（BETTER）

## 解决什么问题
agent 在使用 frago 的过程中会观察到重复模式——同一类路由判断每次都手动做、同一类知识每次都临时拼。这些重复模式是 frago 应当沉淀的资产，但 agent 默认倾向是"我自己处理就好"，没有沉淀习惯。这条原则规定沉淀的方向。

## 第一性原理

**重复的模式 → 数据化沉淀，不要硬编码进 Rust。**

观察到任何"每次遇到 X 都要做 Y"的模式，立刻问：这能不能落到数据层？

## 三种沉淀通道

### 1. 重复路由模式 → `frago hook-rules add`

每次遇到"agent 写了 X 应该改写成 Y"或"碰到 X 类操作应该路由到 Z"——这是 hook 规则。

不要去改 frago-core 的 Rust 源码。`frago hook-rules add` 把规则写进 `hook-rules.json`，规则引擎自动加载。详见 `frago book hook-rules-authoring`。

### 2. 重复知识 → `frago def save`

每次遇到"这个领域的 fact 我刚查过、下次还得再查"——这是结构化知识。

不要硬编码进 prompt，不要写散落的 markdown，不要存进 auto memory（见 `frago book must-no-auto-memory`）。`frago def save` 把知识存进对应 domain，下次 `frago <domain> find` 直接拉。详见 `frago book def-knowledge`。

### 3. 重复工作流 → `frago recipe`

每次遇到"这套操作步骤跑了不止一次"——这是 recipe 候选。

不要每次让 agent 重新探索，不要把步骤写在 prompt 里。固化成 recipe 后，未来执行直接 `frago recipe run`，跳过 agent 探索。详见 `frago book recipe-creation`。

## 为什么不改 Rust

frago-hook 的 Rust 源码是**机制**，不是**内容**。

- 机制：规则引擎、hook 协议、消息路由
- 内容：具体规则、具体知识、具体工作流

机制改一次发一个版本，所有用户跟着升级；内容是用户特定的，应该数据化、可热更新、可同步。

把内容硬编码进机制 = 内容失去灵活性 + 机制失去稳定性，两边都输。

## 判断标准

观察到一个模式时，问：

1. **这个模式跨用户通用，还是本机/本项目特定？**
   - 通用 → 提议加进 frago book / 默认 hook 规则
   - 特定 → 走数据化沉淀

2. **这个模式会变吗？**
   - 会变 → 一定数据化（改起来不用发版）
   - 不会变 → 也优先数据化（机制少一次改动就少一次出 bug）

3. **agent 沉淀完，下次自己用得上吗？**
   - 用得上 → 沉淀
   - 用不上 → 提醒用户考虑沉淀

## 反模式

```python
# ❌ 重复手动做
# 用户每次让 agent 起一个新 recipe，agent 都重新读 recipe-fields 文档
# 三次以后还是没沉淀

# ✅ 数据化
# agent 第二次就该意识到："这步有重复" → frago def save 到自己的 domain
# 或者发现 frago book recipe-creation 已经覆盖 → 直接引用
```
