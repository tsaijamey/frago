# domain-insights

分类: 效率（AVAILABLE）

## 解决什么问题
agent 完成任务时产生有价值的领域级知识——已验证的事实、关键决策、伏笔、状态快照、踩过的坑——但缺少标准沉淀路径。Phase 2 起，这些知识通过 `{{frago_launcher}} run insights` 写入 domain 级 `insight.jsonl`，跨 session 持久化、跨任务复用。

## 是什么

Domain insight = 一段绑定到 domain（= run instance）的结构化知识，存于 `~/.frago/projects/{domain}/insight.jsonl`。

不绑特定操作日志，跨 session 持久化、可独立追加和更新。一个 domain 下能积累任意多条 insight，构成这个领域的知识库。

## 5 种 type 的语义边界

按"这条 insight **本质是什么**"判断，不是按内容主题：

| type | 语义 | 典型场景 | 反例 |
|------|------|---------|------|
| `fact` | 已验证的客观事实 | "Twitter API v2 限流为 100 req / 15min" | 主观判断、推测 |
| `decision` | 关键设计/方案决策 | "选 CDP 而非 Playwright，因为 zero-deps" | 无背景的事实 |
| `foreshadow` | 伏笔——未来可能用到 | "这站说 2026Q3 切 SSO，要预留改造窗口" | 立即可验证的事实 |
| `state` | 当前状态快照 | "账号当前权限层级为 viewer" | 不会变的常量 |
| `lesson` | 教训 / 踩过的坑 | "动态 class 不可靠，要用 data-testid" | 中性事实 |

选不准时，**confidence 设低（0.3-0.5）+ 偏向 fact**，后续可 update 改 type。

## 写入

  {{frago_launcher}} run insights --save \
    --type fact \
    --payload "Twitter API v2 限流 100/15min（2026 起）" \
    --confidence 0.9 \
    --related-sessions <session_id1>,<session_id2>

- `--domain <name>` 指定 domain；省略时用当前 run context（`FRAGO_CURRENT_RUN`）
- `--confidence` ∈ [0.0, 1.0]，默认 0.5
- `--related-sessions` 关联到产生这条 insight 的 sub-agent session

## 更新（追加式版本化）

  {{frago_launcher}} run insights --update <id> --confidence 0.95 --payload "..."

不修改原 jsonl 行，追加一条 `version+1` 新条目，旧版自动 `superseded=true`。读取时只暴露最新非 superseded 版本。

## 查询

  {{frago_launcher}} run insights                                 # 当前 domain 全部
  {{frago_launcher}} run insights --query "API 限流"               # payload 全文搜
  {{frago_launcher}} run insights --type fact                      # 按 type 过滤
  {{frago_launcher}} run insights --domain twitter --format json   # 跨 domain + JSON 输出

跨 domain 全文搜 + run 名搜：`{{frago_launcher}} run find <keyword>`。

## 何时记 insight

frago hook 在 Edit/Write 后会催 agent 记 insight。agent 自觉记录的场景：

| 出现什么 | 选哪种 type |
|---------|-----------|
| 验证了一个非显然的事实 | `fact` |
| 做了"为什么 A 不 B"的取舍 | `decision` |
| 发现 6 个月内可能影响后续工作的预兆 | `foreshadow` |
| 当前状态/权限/配置可能变化、值得快照 | `state` |
| 调试中栽过的坑、找到的 workaround | `lesson` |

**不记 insight 的场景**：
- 操作流水（那是 `{{frago_launcher}} run log` 的事）
- 一次性临时调试输出
- 跟领域无关的项目内部细节

