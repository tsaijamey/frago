# must-data-dir

分类: 替代（MUST）

## 解决什么问题
agent 把产出文件散落在 /tmp、Desktop 等随机位置；目录起名各凭想象，下次谁也找不回来；或者写进 `~/.frago/projects/`——那是 frago 自动维护的会话账本，不是事务数据该去的地方。

## 唯一落点：~/.frago/data/

一切事务产出、过程文件、笔记、交付物都走 `~/.frago/data/`。

`~/.frago/projects/` 是 frago 自己的会话账本：一个知识域一个目录，域下按会话 id 存放同步下来的会话记录（`metadata.json`、`steps.jsonl`、`summary.json`、`summary.md`），连域目录带 `_domain.json` 一起都由 frago 在同步时写入。**agent NEVER 直接往 projects 里创建或修改文件**，无论有没有 `FRAGO_CURRENT_RUN` 环境变量，无论主题是否命中已注册域。看到自己正要写 `~/.frago/projects/<任何路径>`，停下改道 data。读它不受限。

## 目录怎么起名

唯一合法形态，两层，缺一不可：

  ~/.frago/data/<主体>/<YYYYMMDD>-<语义-slug>/

  → 第一层是主体：这件事归属于谁、归属于哪个长期对象。不带日期的 kebab 短词（lenovo、nanxin）
  → 第二层是事务：完整 8 位日期前缀 + kebab-case 语义 slug（20260716-apexp-progress-board）
  → 日期在最前面当排序键；NEVER 放末尾，NEVER 用月份（202605）或自创粒度；取任务开始当天
  → 主体容器只允许一层，NEVER 再往下嵌第二层主体
  → 事务目录 NEVER 直接建在 data 根下。`~/.frago/data/20260729-xxx/` 是非法的，无论这件事看起来多一次性
  → 主体容器下 NEVER 直接放文件，它只装事务目录

**动手前先查现成落点**，别自己拍脑袋造主体：

  frago context data:<关键词>      # 一步拿到落在哪儿，别 ls 目录挨个猜

命中已有事务目录就在里面继续（session-id.yaml 追加自己的 id）；命中某个主体容器就在它下面新建事务目录。两样都没命中，才需要新建主体容器——取这件事归属的那个稳定对象（客户、公司、产品、长期项目、生活领域），拿不准就问用户，NEVER 用一件事的名字当主体名。

日期是分层的标记：第一层是主体，永远不带日期；第二层是事务，永远带日期。

  ✅ ~/.frago/data/lenovo/20260716-apexp-progress-board/
  ❌ ~/.frago/data/20260716-apexp-progress-board/     # 事务落在主体那一层
  ❌ ~/.frago/data/lenovo/apexp-progress-board/       # 事务那一层没有日期
  ❌ ~/.frago/data/lenovo/apexp/20260716-board/       # 主体嵌了两层
  ❌ ~/.frago/data/lenovo/report.md                   # 主体层直接放文件

## 内容怎么组织

每个事务目录内部（样板见 `~/.frago/data/lenovo/20260716-apexp-progress-board/`）：

  <主体>/<YYYYMMDD>-<slug>/
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

  # ✅ 正确：产出在 data/<主体>/<YYYYMMDD>-<slug>/ 内
  frago recipe run video_produce_from_script \
    --params '{"script_file": "~/.frago/data/lenovo/20260729-demo-video/script.json", "output_dir": "~/.frago/data/lenovo/20260729-demo-video/video"}'

  # ❌ 错误：使用外部目录
  frago recipe run video_produce_from_script \
    --params '{"script_file": "~/Desktop/script.json"}'

禁止把**产出**留在 Desktop、/tmp、Downloads 等外部位置——那些地方没有备份、不进同步、下次找不回来。
Recipe 调用时必须显式指定 output_dir 到 `~/.frago/data/<主体>/<YYYYMMDD>-<slug>/` 内。

不算产出、因而不受这条约束的东西：会话 scratchpad 里的中间文件与一次性脚本、按个人守则写给用户看的审计 jsonl。判据是这件事做完之后还需不需要它——需要就是产出，落 data。

## Run 上下文（自动管理）

Executor 启动 sub-agent 时通过环境变量 FRAGO_CURRENT_RUN 自动注入 run_id，它决定日志记到哪个 run 名下。NEVER 用它来决定文件写哪儿——文件永远在 data。

NEVER 手动调用 frago run set-context 或 frago run release。
这些命令仅供 CLI 手动调试使用，sub-agent 不需要也不应该调用。

## 路径一律写绝对路径

每次 Bash 调用结束后工作目录都会重置回项目根，cd 只在当次调用内有效，靠它建立的相对路径下一条命令就失效。

  frago recipe run job_filter \
    --params '{"input": "~/.frago/data/lenovo/20260729-demo-video/jobs.json"}'

## 找回旧产出

别列 `~/.frago/data` 目录挨个猜，用关键词直接定位：

  frago context data:<关键词>

详见 context-recall。
