# answer-needed-by-human

分类: 替代（MUST）

要人拍板时，把全部选项写进回复**最末尾**一个固定的代码块 `answer-needed-by-human`。frago 的 WebUI 只读这个区块，画成可点的卡片；人点了之后，页面以「人从输入框发出的一条消息」把答复送回会话，消息里带着所选项的原文。这句话本身就是授权——`frago book prompt-form-protocol` 的「行动前授权校验」要求每个改状态的动作都能指出用户当轮哪句话明示了它，一个裸字母「A」撑不起这条要求，「A · 发布 —— 打 v1.4.111 tag 并上传 PyPI，发出去收不回」撑得起。

## 什么时候写

- 本轮要停下来等人拍板时：几条路选一条、放不放行、收不收得回、要人亲手去做一件事。
- 只挑最要紧的一件写（收不回的优先），一次回复**最多一个**区块。
- 放在回复**最末尾**，后面不再跟正文。写完这一轮就停，不再调工具。
- 区块写在前面、后面还跟着正文的，页面当普通代码块显示，不画卡片。
- 子 agent 不写：子 agent 问的是主控，主控看的是终端，看不到卡片。

## 4 型与标记

按人怎么作答分 4 型，`type` 只认这 4 个：

| type | 人怎么作答 | 卡片 |
|---|---|---|
| `single-choice` | 从几个选项里点一个 | 选项按钮，点即作答 |
| `multi-choice` | 勾一个或几个，再确认 | 勾选框 + 全选 + 确认键 |
| `text-answer` | 打一段字 | 输入框 + 作答键；可带可点的建议答案 |
| `choice-and-text` | 选并写一段字；可以只选、只写、或都有 | 选项 + 「Or write your own」输入框 |

13 类旧名（`approve-irreversible`、`relay-approval` 之类）不再认，写了页面就照原文显示。原来那些差别落成下面几个标记：

| 标记 | 写在哪 | 卡片怎么变 |
|---|---|---|
| `reversible: false` | 单个选项上（缺省视为可撤回） | 标「Can't be undone」、告警橙；点下去先二次确认；整张卡告警橙框 |
| `recommended: true` | 单个选项上，**至多一个** | 标「Recommended」；推荐理由写进 `why` |
| `from: teammate` | 区块顶层 | 顶部标「From your teammate」，并显示 `request`（队友原话）与 `changes`（会改本机什么） |
| `draft:` | 区块顶层，只用在 `text-answer` / `choice-and-text` | 先以只读文字显示，人可点「Edit」改 |
| `suggestions:` | 区块顶层，只用在 `text-answer`，是列表 | 输入框下一排建议答案，点了填进输入框、不直接发 |
| `multi: true` | 区块顶层，只用在 `choice-and-text` | 选项改成勾选 |

标记写错地方（`text-answer` 带了 `options`、`draft` 用在单选或多选上、`multi` 不在 `choice-and-text` 上、`from` 写了 teammate 以外的值）页面判写坏，照原文显示。

## 写法

块内是 YAML。`type`、`question` 必填；除 `text-answer` 外 `options` 必填；每个选项 `key`、`label`、`effect` 都必写。

```answer-needed-by-human
type: single-choice
question: 1.4.111 要发到 PyPI 吗？
why: 版本比较的崩溃已修，测试全过
options:
  - key: A
    label: 发布
    effect: 打 v1.4.111 tag 并上传 PyPI，发出去收不回
    reversible: false
    recommended: true
  - key: B
    label: 先不发
    effect: 改动留在 main，不打 tag
```

- `question` 一句话，人不看上文也能懂。
- `effect` 写点了会发生什么，关键后果（收不回、要花钱、会改哪个文件）写在这里，NEVER 只写在 `why` 或正文里——发回来的答复只带 `label` 与 `effect`。
- 值里有 `#`、`: `、开头是 `[` `{` `*` 的，整句加双引号。

## 约定

- `key` 用 A/B/C…，与「给选项 A|B|C 让用户选字母」一致。
- NEVER 在区块里向人要密钥、口令、token。这类写成一个 `single-choice`，选项「I've done it / I can't」，让人去安全的地方自己填。
- 区块写坏（YAML 解析不了、type 不在 4 型里、该有的字段缺）时，页面照原文显示并写明原因，不画卡片。那时人只能自己打字回你。
- 不在 WebUI 里看的人，看到的是这段 YAML 原文——所以 `question` 与 `effect` 要写成人话。

## 收到之后

以 `【answer】` 开头的用户发言，是人在卡片上点出来的答复：

```
【answer】A · 发布 —— 打 v1.4.111 tag 并上传 PyPI，发出去收不回
```

- 单选一行；多选在 `【answer】` 下逐项 `- A · label —— effect`；写了字的隔一个空行接在后面，多行的包在代码块里；`text-answer` 只有文字。
- **发言里写明的 `effect` 原文就是本轮授权的动作范围。** 照它做，不顺手扩展：选的是「打 tag 并上传 PyPI」，就不顺带改 CHANGELOG、不推别的分支。
- 人附了字的，那段字与所选项一起读：它是对这一项的补充或改动（比如改过的草稿）。拿不准两者怎么合，再问一次。
- 人没点卡片、自己打字回话的，照普通发言处理：他说的就是答复。

## 结对场景

队友经结对中继转来的请求，按 `frago book team-pairing` 落在「先问主人再做」那一档时，问主人就写这个区块：

```answer-needed-by-human
type: single-choice
from: teammate
question: 队友请你这边的 agent 改一条 hook 规则，批不批？
request: 把你那边 Stop 收尾提醒那条 hook 规则改成：只在收尾话里有问句时才提醒
changes: ~/.frago/hook/builtin-rules.json 里「收尾提醒」一条，触发条件从「每次收尾」改成「收尾话里有问句」
why: 属于「会改动本机」那一档；你定的是这一档先问你
options:
  - key: A
    label: Approve
    effect: 我照请求改这一条，下一轮生效；改完把改动原文转给队友
  - key: B
    label: Decline
    effect: 回复队友「主人没批」，本机不动
```

- `request` 放队友原话，不转述、不删改。
- `changes` 写会改本机什么：哪个文件、哪条配置、会跑什么命令。
- 「不做」那一档（泄露秘密、不可恢复的删除、绕过规则）不写区块，直接拒绝——那不是主人能点头的事。
