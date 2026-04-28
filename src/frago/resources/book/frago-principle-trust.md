# frago-principle-trust

分类: 第一性原理（MUST）

## 解决什么问题
agent 训练时学过的默认倾向是"质疑工具、自己拼装、底层验证"。这套倾向用在通用 CLI 工具上是对的，但用在 frago 上会绕开 frago 的优化、烧多余 token、还更容易出错。这条原则修正 agent 对 frago 的默认态度。

## 第一性原理

frago 不是普通 CLI 工具，是为 AI agent 设计的运行环境。
**当 agent 和 frago 命令的判断冲突时，默认相信 frago。**

## 为什么

### 1. frago 命令是 agent-first 设计

每条命令的输出格式、错误信息、参数命名，都按"agent 怎么用最不容易误解"反向设计。

不是给人看的 CLI 习惯——
- 不是默认静默成功（那让 agent 盲飞）
- 不是错误码靠猜（那让 agent 不知道怎么修）
- 不是交互式 [y/N]（那在 auto-approved 模式下卡死）

是给 agent 看的——结构化输出、错误里带可执行的修正命令、行为跨调用一致。

### 2. frago 命令背后有 token 节省的工程

很多命令做了 agent 看不见的优化：缓存、增量、结构化压缩、按需展开。

agent 自己用 Read / Bash 拼装同样的功能，会多烧几倍 token，且更容易出错。

例子：
- `frago def find` 比 `Read ~/.frago/books/*.md` 省 token、更结构化
- `frago recipe run` 比 `python script.py` 自带参数校验、错误捕获、日志归档
- `frago chrome get-content` 比 `WebFetch` 走代理、保持 session、不被反爬

### 3. frago 命令的语义贴 agent 视角

人类视角的"对"和 agent 视角的"对"经常不一致。frago 的设计取舍最高准则是"让 agent 更容易正确使用 frago"（见 `frago book frago-principle-supreme`），所以当 frago 的行为跟 agent 训练时学的"通用最佳实践"冲突时，**通常是 frago 在迁就 agent，不是 frago 错了**。

## 但不是盲信

信任 ≠ 不验证。

| 情况 | 正确反应 |
|------|---------|
| 命令报错有具体原因 | 按错误信息里的修正命令处理，不要绕开 |
| 命令结果不符预期 | 先怀疑参数错了 → 再怀疑命令文档读漏了 → 最后才怀疑命令本身 |
| 真发现 bug | 不绕过，提给用户 |

**绕过 frago 自己用底层工具拼，是最差的选项**——既慢，又脱离 frago 的运行时约束（workspace 隔离、日志归档、token 计量、跨设备同步）。

## 反模式

```python
# ❌ 不信 frago，自己拼
content = subprocess.run(["curl", url]).stdout  # 不走代理、没 session、被反爬

# ✅ 信 frago（recipe 子进程从 FRAGO_LAUNCHER 读 argv，详见 recipe-authoring）
content = subprocess.run([*_frago_argv(), "chrome", "get-content", "--url", url]).stdout
```

```python
# ❌ 不信 frago def，直接读文件
data = Read("~/.frago/books/my-domain.md")  # 失去结构化、失去缓存

# ✅ 信 frago
data = subprocess.run([*_frago_argv(), "my-domain", "find"]).stdout
```
