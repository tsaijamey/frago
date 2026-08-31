# recipe-expose

分类: 效率（AVAILABLE）

## 三种人，禁止混称

| 说法 | 是什么 | 代码里怎么认 |
|---|---|---|
| **未登录的人** | 没有登录会话 | 没有能解析成活会话的 `frago_sid` cookie |
| **登录用户** | 登录了，但不是主人 | cookie 解析出一个账号 id |
| **主人** | **不是账号**，是请求来源 | `is_owner_request` = 请求落在 `local` 或 `token` 区 |

**NEVER 用「访客」讨论权限**：中文里它同时盖住登录和未登录两种人，而这两者差着一整个区。
源码里的 `visitor` 特指「登录了但不是主人」，直译成访客正好翻反。

**主人不是账号。** `is_owner_request` 只认 `zone in ("local", "token")`，
而 `identity_of()` 明说账号在**每个区**都可能存在（主人的浏览器也带 cookie）。
所以系统里没有任何一个账号是主人——你自己那个账号从公网登录进去，待遇和名单上其他人完全一样。
主人只有两条来路：请求从本机发出（`local`），或带着 `~/.frago/server-token`（`token`）。
那个文件 0600、首次需要时自生成，`frago server token` 是读它不是设它。**谁读得到那串谁就是主人。**

## 两个独立的问题

一张已开放的页面由两个**互不相干**的答案描述，混成一个是这套东西以前最大的毛病：

| 问题 | 存在哪 | 谁决定 |
|---|---|---|
| **谁能打开** | `published.json` 的 `mode` + `allow` | 开放它的人 |
| **从哪个根读** | `published.json` 的 `reads` | 开放它的人 |
| **页面能触发什么** | 配方那个 mode 方法上的 `@action` | 写配方的人 |

第三行以前也在 `published.json` 里，叫 `--runnable`：**看得见就等于全部能按**，
而按下去是在这台机器上、用这台机器配好的凭证跑。同一个配方在这张页面上能跑、在那张不能，
配方自己一个字都没说。现在能力来自契约、可见性来自名单，两件事只能各自收窄，谁都放宽不了谁。

第二行以前根本不存在。`identity` 一个词同时表示「要登录」和「各人读各人那份」，
于是最常见的需求——**点名这几个人，看这个配方算出来的同一份东西**——没有任何写法，
逼着人去借机器级共读（那是给数据层设计的）或者干脆开成 public。

`reads` 说的是**从两个根里的哪一个读**，这两个根 `app_state` 里一直都有、物理分开：

| `reads` | 落点 | 谁有一份 |
|---|---|---|
| `own` | `~/.frago/users/<账号id>/state/<配方>.json` | 每个登录用户一份 |
| `recipe` | `~/.frago/app-state/<配方>/<槽>.json` | **配方自己一份，路径里没有任何账号** |

**这里不要说「主人的那一份」。** 「主人」在本篇的定义是**请求来源**（`local` 或带 token），
拿它去描述一份数据存在哪，等于让同一个词盖住两件毫不相干的事——正是开头那张表要禁的。
而且 `recipe` 那一份确实不在任何人名下：它就是配方自己的槽。

## 四个区

`/app/<recipe>/` 是页面的固定地址，默认全关，逐个显式打开。
（注意 `frago recipe publish` 是配方写自己的运行状态给页面读，与对外开放无关。）

每个请求按这个顺序落进**一个**区：

| 顺序 | 区 | 条件 | 待遇 |
|---|---|---|---|
| 1 | local | 对端可信 **且** 无反代转发头 | 主人 |
| 2 | public | public 模式已发布页面的 `/app/<name>/**`，GET/HEAD，槽位对得上 | 免登录只读 |
| 3 | identity | 带活会话 cookie，且请求在下面那张封闭清单里 | 登录用户 |
| 4 | public | `POST /api/auth/login` 这一条 | 未登录唯一能发的 POST |
| 5 | token | 带正确的服务器 token | 主人 |
| 6 | — | 都不是 | 浏览器导航够条件 → 302 去门口；否则 401 |

**登录用户够得着的全部**（`_IDENTITY_ENDPOINTS` + `classify_identity`，封闭清单，新接口默认落 token 区）：

    POST   /api/auth/login  /logout  /password
    GET    /api/auth/me     /api/auth/pages          （HEAD 同）
    GET    /app/<name>/**          ┐ identity 模式
    POST   /app/<name>/run         ├ 且他在名单上
    POST   /app/<name>/api/<mode>  ┘

`/api/file`、`/api/agent`、`/api/recipes/<n>/run` 对登录用户一律 401——那三条等于在这台机器上执行代码。

两个从顺序里掉出来的坑：

- **同时带 cookie 和 token 去开一张你在名单上的 identity 页面，进的是 identity 区**——
  以主人的钥匙进门却拿到登录用户的待遇。要以主人身份验证，用没有 cookie 的客户端（`curl`）。
  （反过来不会：identity 判不过会继续往下走到 token 检查，cookie 不会让你损失什么。）
- 这道闸在 CORS 外面，**OPTIONS 一律 401**，跨域预检到不了 CORS。

## 匿名区只收 GET/HEAD，所以前后端分离的页面开不成 public

`/app/<name>/api/<mode>` 是「页面向自己的后端要数据」的唯一入口，走 POST。
匿名区只收 GET/HEAD，**于是一张会调 `api/<mode>` 的页面，开成 public 之后每一次都被拒，
页面白着，三层没有一处报错**。

以前这只能在开放之后被人撞见。现在 `expose --public` 会先读一遍 `assets/`，
发现页面在调后端就当场拒绝并给出两条路：

- 把结果预先算成文件放进 `dataDir`，页面只渲染 → 可以 public；
- 或者 `--signed-in` / `--allow …`，要一份共同的数据就再加 `--shared`。

**推论**：`public` 与 `identity` 这个二选一，实际上常常是「老架构 / 前后端分离」的二选一，
名字却让人以为在选给谁看。真正在选给谁看的是 `--public / --signed-in / --allow` 这三个开关。

## 怎么用

    frago recipe expose <name> --public              # 谁都能看，不用登录
    frago recipe expose <name> --signed-in           # 任何登录用户
    frago recipe expose <name> --allow <id|邮箱>     # 只开给点名的人，可重复
    frago recipe expose <name> --deny  <id|邮箱>     # 把某个人移出名单
    frago recipe expose <name> --only  <id|邮箱>     # 整份名单换成这几个
    frago recipe expose <name> --shared              # 名单上的人读你的同一份（只读）
    frago recipe expose <name> --each-their-own      # 各人读各人那份（identity 的默认）
    frago recipe expose <name> --portal              # 这张页面是登录门口
    frago recipe unexpose <name>
    frago recipe exposed                             # 现状：谁能看、读谁的、能按什么

**第一次开放 MUST 明说谁能看。没有默认值。**
以前不带开关等于 public，而「还没想清楚」的人恰恰就是敲光杆命令的那个人，
拿到的是最宽的那个答案。现在不带三选一直接拒绝，并把三个选项列出来。

**再次 expose 只改你点到的字段。** 没写 `--allow` 不会把名单清掉，改 `--slot` 不会顺手放开页面。
放宽必须说出口：`--deny` / `--only` / `--signed-in` / `--public`。
`--force` 因此不再存在——它唯一的用途就是抵消「每次整条重写」的副作用。

**`--slot <名>`（默认 `default`）**

- `--public`：唯一被发布的那一份。`?key=` 必须等于它；给两个值直接拒；空值算默认槽。
- `--shared`：名单上所有人读的**就是配方自己这个槽**。`--slot` 在这里第一次真正起作用。
- `--each-their-own`：**带了直接报错**。读的槽位是他自己的账号 id，由服务端从会话算出，
  他只要带**任何** `?key=` 网关就当场拒（不是忽略，是拒）——这里写一个槽名会被记下来却什么也不管，
  只改审计报告里的一行字。以前它是默默收下的，于是有人花一下午想不通自己的 `--slot` 为什么没生效。

**`--allow <账号id|邮箱>`（可重复）**

- **只收账号 id**。邮箱只是查表便利，且**必须是已经登录过的邮箱**，查不到直接报错——
  邮箱没有验证环节，预授权一个没人认领的地址等于挂一张先到先得的门票。
  先让对方登一次，再 `frago user list` 取 id。
- 不在名单上的人拿到的响应与「这页根本没发布」**一模一样**（401 而非 403——403 等于确认这页存在且有人在名单上）。
- 存进 `published.json` 后是四态（`_allow_of`）：无 `allow` 键 = 老记录、所有登录用户；`null` = 同上；
  `["id",…]` = 只这些人；**别的任何东西 = 谁都不行**（NEVER 抢救能认出来的那几项，缺的那半可能正是关键限制）。
- 空名单写不进去。把最后一个人 `--deny` 掉会被拒绝，关页面用 `unexpose`。

**`--shared`：一群指定的人看配方自己那一份**

名单上的每个人读的都是配方自己的 `--slot` 那一份（`app-state/<配方>/<槽>.json`），
`/app/<name>/data/…` 给的是那个槽声明的 `dataDir`，页面调 `api/<mode>` 也以同一个落点作答。
**只读，且是构造上的只读**：这种页面下没有任何人有自己的目录，
所以 `/run` 一律 404，`config.json` 里 `actions` 恒为空——配方标了多少 `@action` 都不算数。

这和「机器级共读」（`share/common` + `reads_common`）不是一回事：
那一套解决的是**多个配方之间**怎么读同一份数据，这一条解决的是**多个人**怎么看同一张页面上的同一份数据。

**`--each-their-own`（identity 的默认）**

登录用户读 `~/.frago/users/<账号id>/state/<recipe>.json`，与配方自己的 `app-state/` 物理分开。
**页面要能渲染空 state 而不是 500**——第一次打开时那份还没被写过。

**`--portal`**

把这张页面登记成登录门口，写进 `published.json`，`frago recipe exposed` 里看得见。
门口 MUST 是 `--public`（否则 302 过去只是换个地方 401），且**一台机器只能有一个**，
第二次登记会指名现任并拒绝。`FRAGO_LOGIN_PORTAL` 仍然优先于登记表（空字符串=关掉跳转），
两者都没有时兜底用历史默认名 `frago_login_portal`。

**`--yes` / `--format json`**

`--format json` **不豁免确认**：不带 `--yes` 时回 `{"code":"confirm_required","notes":[…]}` 并以 1 退出。
那份 `notes` 就是「这次会暴露什么」——**读完再带 `--yes` 回来，NEVER 见非零退出就直接补 `--yes` 重跑**。

**跑之前就会被拒的**：配方不存在；没有 `assets/` 目录；第一次开放却没说谁能看；
`--allow` 的账号查不到；名单会被清空；`--public` 但页面在调 `api/<mode>`；
门口不是 public 或者已经有一个；`recipe_checks.audit` 报出致命项。

读回来时几处刻意的不对称，都往关的方向倒：`mode` 缺键读成 public（老记录当年就是发给匿名读者的）、
认不出来读成 identity；`reads` 缺键或认不出来读成 `own`（各看各的，认错方向只会让人看到自己的空目录，
认错成 `recipe` 才会把不该给的那份给出去）；
`portal` 必须严格 `True`（`"true"`、`1` 全读成 False——都是手改文件时想反了的产物）。

## 页面能按什么：配方说了算

    # recipe.py
    @export                      # 别的模块能调的，MUST 只读；页面也读得到
    def mode_status(self): ...

    @action                      # 页面能触发的，可以干活
    def mode_save(self): ...

    def mode_backfill(self): ...  # 不标：只有主人能跑

**一个 mode 一个级别。** 「既导出又给页面按」不是一种状态：导出的 mode 按契约只读，
页面直接 `POST /app/<name>/api/<mode>` 就能读，不需要按钮。这以前是一条人写的
互斥校验规则，现在是形状上写不出来。

这三档**不是全序**，NEVER 照 C++ 的 public / protected / private 去理解。
一个 mode 可以允许页面触发却不允许别的模块调用——总线那条路额外承诺只读，
页面这条明确不承诺。要类比就类比 Rust 的 `pub(crate)`：可见性带着「对谁」。

页面发 `POST /app/<name>/run`，体 `{"params":{"mode":"save", …}}`：

- 配方一个 `@action` 都没标 → 404（与「这页没发布」同一个答案）
- 开了，但要的这个 mode 不在里面 → 403，并把开了哪几个列出来（这是页面作者能改的错）
- `--shared` 的页面 → 404，无论配方开了什么
- 参数按 `inputs` 严格校验（`enum` / `max_length` / `pattern` / `min` / `max` 逐条查）

回 202，**不回配方的返回值**。结果去 `data/` 读，状态读平台维护的 `data/run.json`
（配方 NEVER 自己写这个文件）。同一人同一页串行，第二个 409。

**标了 `@action` 的 mode MUST 写在平台交代的落点里。** 建在基类上就自动满足：
`self.data_dir` 就是那个变量的读取，平台没交代它直接抛，而且运行器是**在这次运行自己的目录里**
起的进程，所以连 `open("x.json", "w")` 这种裸相对路径也落在对的地方。

真正要防的是**跟「谁在跑」无关的固定位置**——绝对路径、`Path.home()/…`、`~/…`。
这两条平时是警告（只有主人跑的配方本来就可以在主人树下存长期数据），
**一旦有 mode 标了 `@action` 就升级成拦截**：同一行代码，从「你自己的落点」变成
「每个人按下去写的都是同一份」。`frago recipe validate` 和 `expose` 用的是同一个判据。

跑的是**这台机器、这台机器配好的凭证**。`FRAGO_SECRETS` 按配方名取，没有「谁的凭证」这一维——
按按钮的是谁，对外部系统来说看不出任何区别。
判据不是「这配方有没有 bug」，是「这份源码我信到愿意让别人按」。
**NEVER 给会花钱、会以你的名义对外做事的 mode 标 `@action`。**

## 名单加对了人，页面照样可能是空的

**expose 只回答「谁能打开」和「读谁的」。「那份数据里有没有东西」是第三个问题。**

`--each-their-own` 下，登录用户的每一次读都被路由到**他自己名下的目录**，
而且这个身份**沿着配方之间的调用继续往下传**：
A 的页面问 plan 要数据，plan 转身问引擎，引擎也是以 A 的身份跑的。
而配方跑出的公共结果落在**算它的那次运行**名下（通常是调度，或你在本机跑的那次，两者都记在本机身份下）。
于是名单加对了、页面打开了，读的却是空目录，**三层没有一处报错**。
2026-08-26 实测：引擎刚算完 7245 只标的，看板上写着「引擎还没算过任何一天」。

两条路，先判性质——**复制之后原件还会继续更新的东西，必须只有一份**：

- 这些人本来就该看配方自己算的那一份 → `--shared`。一条命令，不动数据。
- 数据要给**别的配方**读 → 写进 `~/.frago/recipe-data/<配方>/share/common/`，
  读的那个配方在 `recipe.md` 的 `reads_common` 里列上生产者，
  **再由主人 `frago recipe grant <读的人> --read <被读的人>` 授权**。
  声明是请求，授权才是许可：声明由得利的一方写，光有它等于配方给自己授权。
  两半缺一不可，`frago recipe validate` 会说缺的是哪一半。

**验收只有一条可信的路**：拿名单上一个真实账号登录进去看。
以主人身份跑出数据**不构成**登录用户看得到数据的证据。

## 页面能拿到什么

反过来的契约——配方声明什么是公开的，别的一概不出去：

    publish("my_recipe", {
        "dataDir": "/Users/me/.frago/data/...",   # 私有，路径永不到客户端
        "public": {"title": "Q3 numbers"},        # 只有这个出去
    })

`dataDir` 底下的文件仍从 `/app/<name>/data/…` 可读。非主人侧 `config.json` 带 `apiBase: null`、`readOnly: true`，
外加 `actions`（这张页面能按哪几个 mode，匿名侧连这个键都没有）。
`--shared` 不改变**过滤多少**，只改变**从哪个根读**：那份也只出 `public` 块。
路径两道锁（每个匿名和 identity 入口共用）：不许 `..` / `.` 段，不许任何以点开头的段——后者是被读走过 `.env` 之后加的。

登录后能进哪些页面由 `GET /api/auth/pages` 回答，只回自己进得去的那些，**不回名单本身**。
两个后果：**public 页面永远不出现在门口目录里**（那份列表走 `allows()`，它对 public 记录一律答 False）；
卡片标题取配方的 `description`，整句显示。

**被重置过的账号连这份清单都读不到。** 主人 `frago user passwd <id> --temporary` 之后，
那个账号在换掉临时口令之前只剩三条路（`/api/auth/me`、`/api/auth/password`、`/api/auth/logout`），
页面和页面清单一律拒。详见 `frago book recipe-deploy` 的账号管理一节。

## 什么时候用哪个

- 结果给不特定的人看，且页面不向后端要数据 → `--public`
- 页面要调 `api/<mode>` → 只能 identity（`--signed-in` 或 `--allow`）
- 点名几个人看**配方算的同一份** → `--allow … --shared`
- 每人一份自己的数据 → `--allow … `（默认就是 `--each-their-own`）
- 他们还要能按按钮 → 在**配方**那个 mode 方法上标 `@action`，不在 expose 里

## 不要做

- **不要在没问清「谁能看」之前就敲 expose。** 第一次会被拒，但改动已有页面不会——
  想清楚再敲，现状先看 `frago recipe exposed`，不要凭上一次会话的记忆报名单。
- 不要拿主人视角的运行结果当成登录用户看得到数据的证据。那是两个目录，中间没有通道。
- 不要以为「本机能开、图能画出来」说明服务器上也行。本机每个请求都落 `local` 区，测不出任何权限问题。
- 不要拿 identity 当权限系统。名单决定「谁看得见」，`@action` 决定「能按什么」——
  名单上的人之间能力完全相同，做不到「这三个能看、那两个能跑」。
- 不要拿这里的邮箱当真身份，它没验过；更不要用 `--allow` 写一个还没人登录过的邮箱。
- 不要指望页面能调 `${apiBase}/recipes/<name>/run` 或 `${apiBase}/file?path=`。登录用户同样拿不到。
- 不要指望 `@action` 是沙箱。配方以跑 frago 的那个系统用户的身份和权限跑，隔离只保证产出落点不串人。
- 不要在 `recipe.md` 里找 `exports` / `page_actions`。那两个字段已作废，还写着 `validate` 直接报错——
  对外性质只在方法上，没有第二处可以跟它对不上。
- 不要以为发布一个 slot 等于发布全部；不要把敏感数据放进已发布 slot 的 `dataDir`，那目录整体可读。

## 相关

`frago book recipe-deploy` — 配方怎么送上服务器、反代怎么配、门口页面、服务器上那几个环境变量
`frago book remote-frago` — 本机怎么给服务端下发任务
