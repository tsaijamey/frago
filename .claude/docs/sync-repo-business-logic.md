---
document: business-logic
title: "frago_data_repo_smart_sync — 业务逻辑规约 (recipe 实施者底座)"
audience: "未来 recipe 实施者 (设计 in-a / 编排 recipe / 决定状态持久化方式)"
purpose: |
  在 frago 项目内置 sync_repo 能力被移除前 (见 tasks/spec.md 第二步),
  完整保留同步业务逻辑作为 recipe 实施的不可遗失约束底座.
  本文不规定实现方式 (那是 recipe 实施者的设计自由度),
  但每条业务规则不能少, 不能换皮成更弱的语义.
source:
  research: tasks/RESEARCH.md (commit d39426f, 调研者: Yan)
  expectation: tasks/EXPECTATION.md (HUMAN 口述, 2026-05-16)
  removal_spec: tasks/spec.md (recipe land 后的移除规范, 撰写者: Pian)
created: 2026-05-17
updated: 2026-05-17
---

# frago_data_repo_smart_sync — 业务逻辑规约

> **本文档的读者**: 你是 recipe 实施者 — 要造的 recipe 必须满足本文 §1–§8 列出的所有业务规则. 你**不需要**读 tasks/spec.md (那是第二步移除 sync_repo 的规范, 与你无关).
>
> **本文档的边界**: 业务规则**必须满足**, 实现方式**完全自由**. 当前 sync_repo 的实现细节 (具体 git 命令序列 / pywebview API / Python 文件结构) 是参考, 不是约束 — 你可以重新选型.
>
> **三个原则**:
> 1. 业务能力不可降级 — 14 步主流程的每条业务规则都要在 recipe 中找到对应落点
> 2. 已知缺陷不可继承 (§7) — Tier 1 空桩 / 影子账本被 gitignore / 残骸函数, 这些是 reject 的旧设计, recipe 必须改进
> 3. 复用资产可直接调用 — `tools/workspace.py` 与 `tools/deployment_agent.py` 在 recipe land 后仍存在, 不必重写

---

## §0 调用契约

### §0.1 调用方
配方被这两类调用者使用:
- 被用户操控的 Claude Code
- 被自动调用的 agent

agent 通过 `frago recipe list` 发现此配方, 通过 `frago recipe info <name>` 查阅, 通过 dry run 理解其动作.

### §0.2 调用方契约
**调用 agent 无须管任何结果**. 调用配方等于"代替人类执行" — 因为人类可能不熟悉 cli 方式运行.

业务后果:
- recipe 不向调用方暴露任何中间结果 / 状态机 / 错误码契约
- recipe 内部 agent (称 in-a) 自行完成全部决策, 失败时把人类可读的错误总结写到自己的 run log
- 调用方拿到的是 "调用已结束" 这件事, 而不是具体细节

### §0.3 in-a 必须具备的能力
EXPECTATION §4 原文 (in-a 通过 prompt 必须**非常清楚**):
- 如何收集 workspaces 里需要的内容
- 如何判断内容是新增、修改还是被删除了
- `~/.frago` 哪些目录、文件是非常重要的
- 要去读 gitignore
- 能通过运行命令清晰判断远程和本地的差异
- 何种情况以本地为准、何种情况以远程为准、发生冲突以什么标准解决
- workspaces 下的内容在同步后, 要重新部署到本机的已知 git 仓库里, 并且它知道如何部署 (例如本地实际已经删掉的内容, 不会重复再部署进去)

本文 §1–§7 是对这 7 条能力的具体业务定义.

---

## §1 同步全流程 — 14 个业务规则

> 取自 RESEARCH §3 左栏 (business rule), 完整保留. 右栏的"实现细节"不在本文 — 你可以重新选型.

### 步骤 0a: 用户认证
**业务规则**: 写 git 时必须使用已登录的 GitHub 账户身份.
**失败语义**: 凭证配置失败应**静默继续** (后续步骤自然失败暴露), 不阻断 sync 启动.

### 步骤 1: 仓库存在性
**业务规则**: 同步目标必须是 git 仓库; 不存在时**绝不删除现有 `~/.frago/` 内容**, 用 git init 嫁接而非 git clone.
**配置一致性**: 配置的 repo URL 与实际 git remote 不一致时, 以配置为准更新 remote.

### 步骤 2: .gitignore 完整性
**业务规则**: `.gitignore` 必须始终保持完整, 含以下三类:
- 设备本地数据 (账本 / device_id / settings.local.json)
- 敏感文件 (`.env`, `.env.*`)
- 二进制大文件 (5MB 以上 + 黑名单后缀, 详见 §9)

**已 tracked 的违规清理**: 凡是已被追踪但不该入库的文件 (`.tmp/`, `.env`, `.DS_Store`, `*.mp4` 等), 必须 `git rm --cached` (保留本地文件).

### 步骤 3: 敏感文件兜底
**业务规则**: `.env` 类敏感文件已 tracked 时, **必须**执行 `git rm --cached` (保留本地), 同时给 warning.
顺序: 先 `git ls-files .env .env.*` 找出, 再逐个 untrack.

### 步骤 4: 仓库可见性 + URL 协议
**业务规则**:
- 仓库 public 时**必须 warning** (敏感信息可能泄露), 但**不阻止执行**
- SSH URL → **自动转 HTTPS** (与 gh credential helper 配合更顺)

### 步骤 5: 旧路径迁移
**业务规则**: 旧路径 `~/.frago/.claude/` **一次性**迁移到 `workspaces/__system__/`, 用 `.workspace_migrated` 标记防重.
**幂等保证**: 标记存在则跳过, 不重复迁.

### 步骤 6: 删除检测
**业务规则**: 检测"本地真的删了"的资源需同时满足两个条件:
1. content-hash 账本 (`sync_metadata.json`) 记录过 entry
2. 当前 workspace 内容缺失 AND 本机 `~/.claude/` 也不再存在

**两条都成立才删 workspace 副本**, 单条成立不删 (避免误删跨设备改动).

**关键设计取舍**: 当前实现用 `sync_metadata.json` 影子账本做删除检测, 但账本被 .gitignore (见 §3.2). 这是已知缺陷 §7.2, recipe 必须改进.

### 步骤 7: workspaces 收集
**业务规则**: 从本机收集资源到 `workspaces/`:
- `~/.claude/CLAUDE.md` (全局 CLAUDE)
- `~/.claude/commands/` (slash commands)
- `~/.claude/skills/` (skills)
- `~/.claude/projects/<encoded>/memory/` (project memory)
- 各项目 `.claude/` (项目级配置)

**项目锁定规则**:
- 用 git remote URL 作 canonical-ID 锁定项目
- 没有 git remote 的项目 → **warn 并跳过** (不进 workspaces, 也不报错)

### 步骤 8: 账本写入 (baseline)
**业务规则**: 遍历 `workspaces/` 所有文件, 与现有 entry 比较, 不同就更新 entry. 跳过 `__pycache__` / `.pyc` / `.pyo`.

**entry 结构**:
```python
@dataclass
class SyncEntry:
    rel_path: str                  # workspaces/ 内相对路径
    content_hash: str              # git blob SHA1 算法: sha1("blob {size}\0{content}")
    synced_at: datetime
    synced_by: str                 # device_id (uuid4 前 8 位)
```

**版本号**: `SYNC_METADATA_VERSION = 2` (当前). recipe 若改账本结构, 升 version.

### 步骤 9: 本地提交
**业务规则**: 本地有未提交变更时, `git add . && git commit`:
- commit message 用调用方提供的 (若有) 或默认 `sync: Save local changes (N files)`
- **提交前必须确保 git user.name / user.email 已配置** (用 `gh api user` 拉取)

### 步骤 10: 快进推送 (Fast-Forward)
**业务规则**: 本地领先 + 远程无新提交时, 直接 push, **不走 rebase** (避开 rebase-abort 循环).
检测方式: `git rev-list --count` 检测 ahead/behind.

### 步骤 11: 远程拉取 + 冲突解决

**业务规则**: fetch + rebase, 处理 3 种情况:
- (a) **远程不存在 / 无 main 分支**: 跳过 (新仓库首次 push)
- (b) **历史无共同祖先** (unrelated histories): 用 `merge --allow-unrelated-histories` 合并, 冲突走两段式解决
- (c) **正常**: rebase, 失败则 fallback 到 merge + 自动解冲突

**冲突解决决策树**: 详见 §2 (本文核心).

**rebase 前预检冲突**: 比较 `merge-base..HEAD` vs `merge-base..origin/main` 的 name-status 交集, 提前 warn + 保存 `.LOCAL` / `.REMOTE` 备份.

### 步骤 12: 二次 untrack
**业务规则**: rebase 完成后**再扫一遍** ignored 路径; 仍 tracked 就 untrack + 一次额外 commit.
**原因**: rebase 可能从远程拉回已 tracked 的违规文件.

### 步骤 13: 部署 (业务核心)

**业务规则**: 把 workspace 投影回本机:
- (a) `workspaces/__system__/` → `~/.claude/` (全局)
- (b) `workspaces/<canonical-id>/.claude/` → 本地匹配项目

详细规则见 §4 (canonical-ID 匹配 / pending 队列 / 删除传播).

### 步骤 14: 最终推送
**业务规则**: 最后 `git push -u origin main`, 除非调用方指定 `--no-push`.

---

## §2 冲突解决决策树 (recipe 核心价值点)

> 当前 sync_repo 在此处有 **§7.1 Tier 1 空桩缺陷**, recipe 必须真正实现 Tier 1.

### §2.1 整体决策树

```python
def resolve_conflict(file_path: str,
                     local_content: str,
                     remote_content: str,
                     local_commit_time: datetime,
                     remote_commit_time: datetime) -> ResolvedFile:
    """
    返回融合后的内容. 决策顺序:
    Tier 1 (必须实现, 不能再当空桩): agent 语义合并
    Tier 2 (兜底, 不作为主路径): commit 时间硬币
    """
    # Tier 1 — 理解结构化文本的语义, 生成融合两边意图的版本
    if file_path 适合语义合并(file_path):
        merged = in_a.semantic_merge(file_path, local_content, remote_content)
        if merged is not None:
            return ResolvedFile(content=merged, strategy="agent_merge",
                                backup_local=f"{file_path}.sync-backup.local",
                                backup_remote=f"{file_path}.sync-backup.remote")

    # Tier 2 — 整文件 newer-commit-wins, 输者降级 .sync-backup
    if local_commit_time >= remote_commit_time:
        return ResolvedFile(content=local_content, strategy="newer_wins_local",
                            backup_remote=f"{file_path}.sync-backup")
    else:
        return ResolvedFile(content=remote_content, strategy="newer_wins_remote",
                            backup_local=f"{file_path}.sync-backup")
```

### §2.2 Tier 1 — agent 语义合并 (recipe 必须真正实现)

**业务定义**: in-a 在冲突文件上做"理解+融合", 而不是"挑一个赢家".

**适合语义合并的文件类型**:
| 文件类型 | 合并策略 |
|---|---|
| Markdown (`.md`) | 章节级合并: 同章节标题下两边都有新增内容 → 并存; 段落级冲突 → in-a 用语言模型理解意图 |
| YAML (`.yaml`, `.yml`) | key-level 合并: 不同 key → 并存; 同 key 不同 value → in-a 判断 (recipe yaml / skill frontmatter 等结构化数据有显然的字段优先级) |
| JSON (`.json`) | 同 YAML 的 key-level 合并 |
| skill / command 配置 | 按字段语义合并 (model / temperature / system_prompt 等) |
| `.claude/CLAUDE.md` | 章节级合并 (项目说明文档通常各 section 独立) |
| 代码文件 (`.py`, `.ts` 等) | **不适合 Tier 1**, 直接退 Tier 2 (语义合并代码风险太高) |
| 二进制文件 | **不进 Tier 1**, Tier 2 newer-wins |

**Tier 1 失败返回 None**: in-a 不确定合并质量时, 返回 None 退 Tier 2; **不允许返回错误的合并版本**.

**禁止行为**:
- ❌ 永远返回 None (当前空桩, 见 §7.1)
- ❌ 不读文件内容就返回 (in-a 必须真正分析两个版本)
- ❌ 把整文件交给 LLM 让它"猜一个版本" (要做结构化合并, 不是猜)

### §2.3 Tier 2 — newer-commit-wins (兜底)

**业务规则**:
- 比较两侧**最近一次 commit 的 author timestamp** (不是 mtime, 不是 commit time)
- 取较新者赢
- 输者保存为 `<file>.sync-backup` (Tier 2 单边) 或 `.sync-backup.local` + `.sync-backup.remote` (Tier 1 成功时同时备份两边)

**业务后果 (recipe 实施者要清醒认识)**: Tier 2 会**丢一半改动** (输者降级为 .sync-backup 静默保存). 这就是为什么 Tier 1 必须真正实现 — 否则任何两设备并发改同一文件都丢一半.

### §2.4 取舍标准 (EXPECTATION §4 "何种情况以本地为准 / 远程为准")

| 场景 | 取舍 | 理由 |
|---|---|---|
| 文件在本地新建, 远程无 | 本地为准 (push) | 单边新增, 无冲突 |
| 文件在远程新建, 本地无, 且账本无此 entry | 远程为准 (pull) | 单边新增, 本地从未见过 |
| 文件在远程新建, 本地无, **账本有此 entry** | 视为 §1 步骤 6 的删除检测 — 删除条件成立则 push (清远程), 不成立则远程为准 (本地误删, 拉回) | 账本是"曾经同步过"的证据, 用它区分"新建" vs "曾有现已删" |
| 同一文件两边都改 (Tier 1 适合的类型) | agent 语义合并, 融合两边意图 | recipe 的核心价值 |
| 同一文件两边都改 (Tier 1 不适合 / Tier 1 返回 None) | newer-commit-wins, 输者 .sync-backup | 兜底, 保证不阻塞 sync 流程 |
| 仓库 public + 文件含 secret | 不阻塞但 warning | 用户已被 §1 步骤 4 警告过 |
| 仓库不存在 (Step 11a) | 跳过 rebase 直接走 Step 13–14 | 新仓库首次 push 场景 |

---

## §3 配置与状态持久化

### §3.1 目标仓库 URL — recipe 自己管理

**业务规则**: recipe 必须知道**同步到哪个 git 仓库**.

**当前实现** (将被移除): `Config.sync_repo_url: Optional[str]` (src/frago/init/models.py:117).

**移除后 recipe 自决持久化位置**, 候选方案:
| 方案 | 优点 | 缺点 |
|---|---|---|
| 写 recipe 自身的 state 文件 (`~/.frago/recipes/frago_data_repo_smart_sync/state.json`) | 与 recipe 生命周期绑定, 卸载 recipe 一并清 | 跨设备时此 state 是否 sync? 需 recipe 实施者明确 |
| 写到 git remote 本身 (`git config --get remote.origin.url`) | 仓库 URL 本来就在 .git/config 里, 单一真相 | 首次 setup 仍需用户提供 URL 写入 remote |
| 复用 `Config` 但加新字段 `sync_recipe_target_repo` | 与现状最接近 | 字段失主问题 (谁定义谁读) 没解决 |

**推荐 (非强制)**: 第二个方案 — 让 git remote 自己作为真相来源, recipe 启动时若 `~/.frago/.git/config` 无 remote, 则进入 setup 流程引导用户配置.

### §3.2 影子账本设计取舍 (recipe 必须决策)

**当前实现** (将被移除): 两个账本文件被 `.gitignore`, 每台机器各持一份 — 跨设备删除检测失真 (§7.2).

| 文件 | 路径 | 用途 |
|---|---|---|
| `SKILLS_METADATA_FILE` | `~/.frago/.claude/skills_metadata.json` | 上一代 skill 同步 mtime 账本 (已废弃, 见 §7.3) |
| `SYNC_METADATA_FILE` | `~/.frago/.claude/sync_metadata.json` | 当代 workspaces content-hash 账本 + 删除检测基准 |
| `~/.frago/.device_id` | uuid4 前 8 位 | `synced_by` 字段写入 |

**recipe 实施者必须二选一**:

#### 选项 A — 保留账本但放进 workspace, 让跨设备可见

- 路径迁移: `~/.frago/.claude/sync_metadata.json` → `~/.frago/workspaces/__system__/.sync_ledger.json`
- 调整 gitignore 模板: 删旧路径的 ignore 规则, 新路径**不加 ignore** (让账本进入 git)
- `synced_by` device_id 也得跟着 sync (放 `workspaces/__system__/.devices.json` 或类似)
- 优点: 跨设备 in-a 能读到完整账本, 真正区分"新增 / 修改 / 删除"
- 缺点: 多设备并发改账本会触发 §2 冲突 (账本 .json 进 Tier 1 — 结构化合并 entries)

#### 选项 B — 完全放弃账本, 全靠 git 自身追溯

- 删除两个 metadata 文件 + 删除 device_id 概念
- 删除检测改用 `git log --diff-filter=D` (找 git 历史中删除事件)
- 优点: 单一真相 (git), 无账本一致性问题
- 缺点: 第一次同步 (无 git 历史) 时, in-a 无法区分"本地新建" vs "远程曾有现已删" → 默认按"新建"处理, 风险是误恢复已删资源

**推荐 (非强制)**: **选项 A**, 因为账本是 §1 步骤 6 删除检测的关键输入, 完全放弃会让 in-a 在第一次同步时丧失"曾经同步过"的事实判定能力.

---

## §4 workspaces 投影规则 (步骤 13 的细节)

### §4.1 canonical-ID 匹配机制

**业务规则**: workspace 内每个项目对应**唯一 canonical-ID**, 用 git remote URL 规范化得出.

**规范化算法**:
```python
def canonical_id(remote_url: str) -> str:
    """
    git@github.com:user/repo.git    → github.com__user__repo
    https://github.com/user/repo    → github.com__user__repo
    https://github.com/user/repo.git → github.com__user__repo
    """
    # 1. 去掉 protocol (https:// / git@)
    # 2. ':' / '/' 替换为 '__'
    # 3. 去 .git 后缀
    # 4. 去 trailing slash
```

**匹配 confidence**:
| confidence | 含义 | 行为 |
|---|---|---|
| 1.0 (精确) | canonical-ID 完全匹配本机某项目 | 直接 deploy |
| 0.5 (模糊) | 名字相同但 org/owner 不同 (例如 `github.com__user-a__foo` vs `github.com__user-b__foo`) | 进 pending 队列, 等用户手动确认 |
| 0.0 (无匹配) | 本机找不到对应项目 | 进 pending 队列 |

### §4.2 `.pending_deployments.json` 队列

**路径**: `~/.frago/workspaces/.pending_deployments.json`

**业务用途**: 模糊匹配 / 未匹配的部署进队列, 等用户**手动确认**.

**queue entry 结构**:
```python
@dataclass
class PendingDeployment:
    workspace_canonical_id: str
    local_candidate_path: Optional[str]  # 模糊匹配时填候选, 无匹配时 None
    confidence: float                    # 0.0 / 0.5
    detected_at: datetime
    files_count: int
```

**用户确认入口**: CLI `frago workspace pending` (用户列出 + 选择应用 / 跳过).

**recipe 不得自动应用 pending**: pending 是"需人类决策"的标志, recipe 必须让用户介入.

### §4.3 git-tracked 项目 .claude/ 的特殊处理

**业务规则**: 本地项目 `.claude/` 若被项目自己的 git 跟踪 (而不是被 frago 同步仓库跟踪), deploy 后**必须 hint 用户**:
- "本地项目 X 的 .claude/ 已更新, 因为该目录被项目 git 跟踪, 请手动 `git add .claude && git commit` 把改动提交到项目仓库"

**原因**: frago 同步的是用户跨设备配置, 但项目本身的 git 仓库会把这些配置视为项目源码; 自动 commit 项目仓库越权, 必须由用户决定.

### §4.4 删除传播规则

**业务规则**: change_type=deleted 的 workspace 变更, 投影时**精确删除** `deleted_paths` 列出的文件, **不 rmtree**.

**为什么不 rmtree**: 部分文件可能被本地新增但未进 workspace, rmtree 会误伤本地未跟踪文件.

**实现参考**: 当前 `_delete_files` (sync_repo.py) 用 `action.deleted_paths` 精确删.

### §4.5 fallback (首次 setup 兼容)

**业务规则**: 当**没有 workspace 变更**时 (例如首次 setup, workspace 全是新拉的), 仍要**至少跑一次** "frago → claude" 投影, 把 workspaces 内容投影到本机各 `.claude/` 目录.

**原因**: 首次 clone 仓库时, workspace 文件全在但本机 `~/.claude/` 是空的, 不投影用户拿不到任何内容.

---

## §5 同步方向判定 (业务模型, 当前实现未用)

> 当前 sync_repo 的 `_determine_sync_direction` 函数 (sync_repo.py:1309) 定义了清晰的三方对比决策树, 但**在 sync() 主流程从未被调用**. recipe 实施者**可以复用这套业务模型**作为冲突预检的明确决策依据.

### §5.1 SyncDirection 四态

```python
class SyncDirection(Enum):
    NONE          = "none"           # 三方一致, 无需同步
    LOCAL_TO_REPO = "local_to_repo"  # 本地新, push
    REPO_TO_LOCAL = "repo_to_local"  # 远程新, pull
    CONFLICT      = "conflict"       # 三方矛盾, 走 §2 冲突解决
```

### §5.2 三方对比决策树

输入: `local_hash` (本机文件), `repo_hash` (workspace 内副本), `recorded_hash` (账本)

| local | repo | recorded | 决策 | 业务含义 |
|---|---|---|---|---|
| H | H | H | NONE | 三方一致 |
| H | H | None | NONE | 没账本但两边一致, 可补账本不必同步 |
| H' | H | H | LOCAL_TO_REPO | 本地修改 |
| H | H' | H | REPO_TO_LOCAL | 远程修改 (其他设备 push 的) |
| None | H | H | LOCAL_TO_REPO (删除事件) | 本地删, 账本可证, 推删到远程 |
| H | None | H | REPO_TO_LOCAL (其他设备删) | 远程删, 拉删到本地 |
| H' | H'' | H | CONFLICT | 两边都改, 走 §2 |
| H' | H'' | None | CONFLICT (退化) | 无账本无法精确判定, 保守按冲突 |

**recipe 实施者建议**: 用此模型在 fetch 后 / rebase 前做"差异预报", 提前向用户展示 "X 个本地→远程 / Y 个远程→本地 / Z 个冲突", 而不是等 rebase 失败再处理.

---

## §6 SyncResult 数据契约

> UI / 上游消费者契约. 当前 sync_repo 返回, recipe 若有同等需求, 至少要能从 recipe run log 重构出等价信息 (不强求字段名一致).

```python
@dataclass
class SyncResult:
    success: bool
    local_changes: list[FileChange]       # 本设备已上传的资源变更
    remote_updates: list[FileChange]      # 远端拉下的资源变更
    pushed_to_remote: bool                # 是否实际 push 成功
    conflicts: list[str]                  # 未解决的冲突文件名
    errors: list[str]
    warnings: list[str]
    is_public_repo: bool                  # 触发 UI 安全提示
    skipped_large_files: list[str]        # 5MB 以上 / 黑名单后缀
    _raw_workspace_diffs: list[tuple[str, str]]  # (status, file_path), 给 DeploymentAgent 用

@dataclass
class FileChange:
    type: str       # "Command" | "Skill" | "Recipe" | "Project" | "System" | "Other"
    name: str
    operation: str  # "Modified" | "Added" | "Deleted"
    timestamp: datetime | None
```

**recipe 实施建议**: 把上述结构写入 recipe run log (jsonl), 调用方若关心 (虽然 §0.2 说"无须管"), 可以从 log 反查.

---

## §7 已知缺陷 (recipe 必须解决, 不可继承)

### §7.1 Tier 1 agent 合并是空桩

**事实**: `src/frago/tools/sync_conflict_agent.py:51-70` 的 `merge_conflict()` 永远 `return None`.

```python
def merge_conflict(self, file_path, local_content, remote_content) -> Optional[str]:
    """Attempt to semantically merge two versions of a file. ..."""
    # TODO: Implement agent-based semantic merge
    # For now, return None to fall back to newer-commit-wins
    logger.debug("Agent merge not yet implemented for %s", file_path)
    return None
```

**业务后果**: 任何两设备并发改同一文件, sync 都用整文件覆盖丢一半改动 (输者降级为 .sync-backup 静默保存, 用户不一定看得到).

**recipe 必须做**: 见 §2.2 的 Tier 1 实现要求 — 按文件类型走结构化合并, in-a 真正读懂结构, 生成融合版本.

### §7.2 影子账本被 .gitignore

**事实**: `resources/frago-home-gitignore.template:46-49` 显式 ignore:
```
.claude/skills_metadata.json
.claude/sync_metadata.json
.claude/settings.local.json
.device_id
```

**业务后果链**:
- 设备 A 删某资源 → 账本只在 A 本机
- 推到远端 → 设备 B 的账本不同步
- 设备 B sync 时 → 账本里没那个 entry → 走不到"曾经存在过"分支 → 没法识别"这是被 A 删除的"
- 只能靠 git diff 看到 workspaces 副本消失推断, 删除检测在跨设备并发新增 + 一方删除时可能误判

**recipe 必须做**: 见 §3.2 选项 A — 账本放 `workspaces/__system__/.sync_ledger.json`, device_id 也跟着 sync.

### §7.3 残骸函数 (recipe 设计时不要重蹈)

**事实**: sync_repo.py 含 13 个上一代设计未清理的函数, 全部零调用或仅链尾自我调用:

| 类别 | 函数 | 位置 |
|---|---|---|
| mtime 决策链 | `_determine_sync_direction` *, `_is_repo_newer_than_local`, `_get_git_commit_time`, `_is_source_newer`, `_get_dir_latest_mtime`, `_get_file_mtime`, `_files_are_identical`, `_dir_files_identical` | sync_repo.py:755-1354 |
| 旧 SKILLS metadata 账本 | `_load_skills_metadata`, `_save_skills_metadata`, `_update_skill_metadata`, `_remove_skill_metadata`, `_get_skill_metadata_mtime`, `_is_metadata_newer_than_local` | sync_repo.py:855-997 |
| 上一代主同步函数 | `_sync_claude_to_frago` (主流程已不调用, 注释明示 removed), `_sync_frago_to_claude` (仅 fallback 路径) | sync_repo.py:1402-1561 |
| Legacy 数据类 | `FileConflict` (注释 "(legacy)", 零调用) | sync_repo.py:123-129 |

*: `_determine_sync_direction` 虽零调用, 但其业务模型 (§5) 有价值, recipe 可参考决策树, 但**不要直接复制函数**.

**教训给 recipe 实施者**: 不要在 recipe 内留"上一代设计的尸体" — 每个迭代有重大设计变化时, **物理删除**旧代码, 不要保留"以防万一". 残骸代码会增加阅读负担、误导后人、积累技术债.

---

## §8 复用资产 (recipe 可直接调用, 第二步移除后仍存在)

### §8.1 `tools/workspace.py`

**关键 API**:
```python
from frago.tools.workspace import collect_workspaces, migrate_legacy_claude_dir

# 收集 workspaces (内部用 scan_roots / exclude_patterns 配置)
collect_workspaces(scan_roots: list[Path], exclude_patterns: list[str]) -> WorkspaceSnapshot

# §1 步骤 5 的旧路径迁移
migrate_legacy_claude_dir() -> None  # 自带 .workspace_migrated 标记防重
```

### §8.2 `tools/deployment_agent.py`

**关键 API**:
```python
from frago.tools.deployment_agent import DeploymentAgent, execute_deployment, format_deployment_table

agent = DeploymentAgent(workspace_diffs=...)
plan = agent.analyze()                  # 算出每个 workspace 该 deploy 到哪个本地路径
execute_deployment(plan, dry_run=False) # 实际投影 (含 §4.4 精确删除)
format_deployment_table(plan)           # 给用户看的人类可读表格
```

### §8.3 `tools/git_utils.py` (本 spec 第二步 Phase 3 新建)

**关键 API**:
```python
from frago.tools.git_utils import ensure_git_user_config

# 用 gh api user 拉取用户信息, 写入 git user.name / user.email
ensure_git_user_config(repo_path: Path) -> None
```

---

## §9 关键常量 (业务定义, 实现可自由)

> recipe 可重新选型实现, 但常量的**业务含义**不可变.

### §9.1 路径布局

```
~/.frago/                              # FRAGO_HOME, 同步仓库根
├── .git/                              # git 元数据
├── .gitignore                         # 模板 frago-home-gitignore.template
├── .device_id                         # uuid4 前 8 位 (跨设备识别)
├── .claude/                           # 旧路径, §1 步骤 5 迁出
│   ├── sync_metadata.json             # 当代账本 (gitignored, 见 §7.2)
│   └── skills_metadata.json           # 旧账本 (上一代设计, recipe 可弃)
├── workspaces/                        # 当代同步主体
│   ├── __system__/                    # 全局资源
│   │   ├── CLAUDE.md                  # ~/.claude/CLAUDE.md 镜像
│   │   ├── commands/                  # slash commands
│   │   ├── skills/                    # skills
│   │   └── memories/                  # 全局 memory (只读, 不反向部署)
│   ├── <canonical-id>/                # 每个本机已知 git 项目一份
│   │   ├── .claude/                   # 项目级 .claude 镜像
│   │   └── .project-memory/           # 项目级 memory
│   └── .pending_deployments.json      # §4.2 队列
└── recipes/                           # FRAGO_RECIPES_DIR
```

### §9.2 大小与类型限制

```python
DEFAULT_SYNC_MAX_FILE_SIZE_MB = 5       # 单文件硬上限

SYNC_EXCLUDED_EXTENSIONS = {
    # 视频音频
    ".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv", ".webm",
    ".wav", ".mp3", ".aac", ".flac", ".ogg", ".m4a",
    # 压缩包
    ".zip", ".tar", ".gz", ".rar", ".7z",
    # 文档与图像源文件
    ".pdf", ".psd", ".ai",
    # 编译产物
    ".pyc", ".pyo", ".so", ".dll", ".exe",
}

PROJECTS_EXCLUDED_SUBDIRS = {"screenshots", "logs", ".tmp"}

PROJECT_CLAUDE_EXCLUDE = {"settings.local.json", ".mcp.local.json"}  # 项目级 .claude/ 内不同步的文件
```

**recipe 实施者注意**: 这些是用户体验保护规则, **不能放松** — 否则 5MB+ 视频会误同步, .env 类敏感文件会泄露. 可以严格化 (例如加更多后缀), 不能放宽.

---

## §10 调研者的延伸提示 (RESEARCH §9 自评)

来自 RESEARCH.md §9, 给 recipe 实施者:

1. **前端构建产物**: `src/frago/server/assets/assets/index-*.js` 是 pnpm build 产物, recipe 不应触碰构建链, 由 frago 本身的 build 流程处理
2. **_ensure_git_user_config 迁出**: 第二步 spec 已规划迁到 `tools/git_utils.py`, recipe 直接 `from frago.tools.git_utils import ensure_git_user_config` 即可
3. **Config 字段去除**: 第二步会删 `Config.sync_repo_url` + `Config.sync_max_file_size_mb`. recipe 若要这两个值, 在 §3.1 选择持久化方案; max_file_size 可直接硬编码或读 recipe 自己的 config
4. **测试盲区**: 当前 sync_repo 主流程零测试覆盖, recipe 必须**自带验证机制** (recipe 的 verification step / dry-run 输出 / 端到端冒烟测试都可)

---

## §11 给 recipe 实施者的最终检查清单

实施 recipe 前对照本文档:

- [ ] §0.3 列的 7 项能力, in-a 的 prompt 是否都覆盖
- [ ] §1 的 14 步业务规则, 每条在 recipe 中有对应落点
- [ ] §2.2 Tier 1 真正实现了语义合并 (不是返回 None)
- [ ] §3.1 目标仓库 URL 持久化方案已选定
- [ ] §3.2 影子账本去留已选定 (A or B)
- [ ] §4.1–§4.5 投影规则全部覆盖 (canonical-ID 精确 vs 模糊, pending 队列, git-tracked 项目 hint, 精确删除, 首次 setup fallback)
- [ ] §7 三个已知缺陷在 recipe 中被改进, 不是被继承
- [ ] §8 复用资产的 import 路径正确, recipe 不重写
- [ ] §9 大小与类型限制保持或严格化, 不放宽
- [ ] recipe 自带验证机制 (§10.4)

**全部 ✅ 后, recipe land**. 之后才解锁 `tasks/spec.md` 的第二步移除流程.

---

**BUSINESS_LOGIC.md 结束**
