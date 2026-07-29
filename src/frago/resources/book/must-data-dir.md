# must-data-dir

分类: 替代（MUST）

## 解决什么问题
agent 把产出文件散落在 /tmp、Desktop 等随机位置；或者写进 `~/.frago/projects/`——那里是 run 系统自己的记账区，不是事务数据该去的地方；以及用 cd 切目录导致 frago 命令失败。

## 唯一落点：~/.frago/data/

一切事务产出、过程文件、笔记、交付物都走 `~/.frago/data/`。

`~/.frago/projects/` 是 run 系统的内部账本——run 实例元数据、`logs/execution.jsonl`、域级 `insight.jsonl` 都由 frago 自己写入维护。**agent NEVER 直接往 projects 里创建或修改文件**，无论有没有 `FRAGO_CURRENT_RUN` 环境变量，无论主题是否命中已注册 domain。看到自己正要写 `~/.frago/projects/<任何路径>`，停下改道 data。

注: `~/.frago/data/` 是 agent 工作产出的工作区（2026-05-24 起纳入同步）。
    旧定位"recipe 缓存数据用"已作废，别混。

## 目录怎么起名

**动手前先看有没有现成的地方收**。同一件事的续做、或者归属于某个已有主体的新任务，落进已有目录，别另起一个：

  {{frago_launcher}} context data:<关键词>      # 一步拿到落在哪儿，别 ls 目录挨个猜

命中已有事务目录就在里面继续（session-id.yaml 追加自己的 id）；命中某个主体容器（如 `lenovo/`）就在它下面新建事务目录。查不到才走下面的新建流程。

一次性事务直接落一层：

  ~/.frago/data/<YYYYMMDD>-<语义-slug>/

  → slug 用 kebab-case，日期前缀必带且必须是完整 8 位日期（如 20260529-power-seller-reg-audit）
  → 日期在最前面当排序键，目录列表天然按时间排列；NEVER 把日期放末尾
  → NEVER 用月份（202605）或自创其他日期粒度；日期取任务开始当天

长期主体（客户、公司、跨月的长跑项目）才配一层容器目录：

  ~/.frago/data/<主体>/<YYYYMMDD>-<语义-slug>/

  → 主体名用不带日期的 kebab-case 短词（lenovo、nanxin），它是稳定的归属而不是一件事
  → 容器层只允许一层，NEVER 再往下嵌第二层主体
  → 同一主体下每件事仍是完整的 <YYYYMMDD>-<slug>，命名规则与上面一致
  → 已经存在的容器优先用，别在顶层另起一个同主体的目录
  → 没有现成容器又拿不准算不算长期主体，就别新建容器，直接落顶层——事后并入容器比拆散容易

顶层目录名带不带 8 位日期前缀，就是事务目录与主体容器的分界。存量里有一批更早的目录两样都不占（`articles`、`agent_os` 这类没有日期前缀但直接装文件的），它们是历史遗留，当反例不当先例；不必顺手改名，各自的事做完就不再增长。

## 内容怎么组织

每个事务目录内部（样板见 `~/.frago/data/lenovo/20260716-apexp-progress-board/`）：

  <YYYYMMDD>-<slug>/
  ├── session-id.yaml       # 必备。落第一个文件时就写，追加不覆盖
  ├── notebook.md           # 有可复用的方法或纪律时才写，名字固定
  ├── scripts/              # 这件事专用的脚本，跑完还要再跑的放这儿
  ├── <类型>/               # analysis/ cards/ research/ 之类，同类中间件分堆
  └── 成品.md / 成品.html    # 交付物直接放事务目录根，别埋进子目录

  → 要写笔记就固定叫 notebook.md（小写），NEVER 自创 session.md / log.md 之类的名字
  → notebook.md 只装能复用的方法与纪律。处理过哪张卡、改了哪一行这类流水不写，去实时源查
  → 同类中间件到四个就建子目录，三个以内平铺；交付物不受这条约束，再多也放根
  → 脚本分两种：这件事以后还要再跑的放 scripts/；跑完即弃的一次性脚本走会话 scratchpad，别留在产出目录里
  → 跨天续做沿用原目录，NEVER 因为日期变了就新建——目录名的日期是这件事的开始日，不是最后修改日

session-id.yaml 格式：

  sid:
    - 7080f7a0-612b-4627-a111-bdf57aac816f

## 产出物隔离

  # ✅ 正确：产出在 data/<YYYYMMDD>-<slug>/ 内
  {{frago_launcher}} recipe run video_produce_from_script \
    --params '{"script_file": "~/.frago/data/20260729-demo-video/script.json", "output_dir": "~/.frago/data/20260729-demo-video/video"}'

  # ❌ 错误：使用外部目录
  {{frago_launcher}} recipe run video_produce_from_script \
    --params '{"script_file": "~/Desktop/script.json"}'

禁止把**产出**留在 Desktop、/tmp、Downloads 等外部位置——那些地方没有备份、不进同步、下次找不回来。
Recipe 调用时必须显式指定 output_dir 到 `~/.frago/data/<目录>/` 内。

不算产出、因而不受这条约束的东西：会话 scratchpad 里的中间文件与一次性脚本、按个人守则写给用户看的审计 jsonl。判据是这件事做完之后还需不需要它——需要就是产出，落 data。

## Run 上下文（自动管理）

Executor 启动 sub-agent 时通过环境变量 FRAGO_CURRENT_RUN 自动注入 run_id，它决定日志记到哪个 run 名下。NEVER 用它来决定文件写哪儿——文件永远在 data。

NEVER 手动调用 {{frago_launcher}} run set-context 或 {{frago_launcher}} run release。
这些命令仅供 CLI 手动调试使用，sub-agent 不需要也不应该调用。

## 禁止使用 cd

所有命令从项目根目录执行，用绝对路径访问文件。

  # ✅ 正确
  uv run python ~/.frago/data/20260729-demo-video/scripts/filter_jobs.py
  cat ~/.frago/data/20260729-demo-video/result.json

  # ❌ 错误：cd 后 frago 命令会失败
  cd ~/.frago/data/20260729-demo-video
  {{frago_launcher}} run log ...                            # 会报错

## 找回旧产出

别列 `~/.frago/data` 目录挨个猜，用关键词直接定位：

  {{frago_launcher}} context data:<关键词>

详见 context-recall。
