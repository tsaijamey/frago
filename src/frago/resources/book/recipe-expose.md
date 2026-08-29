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

## `/app/<name>/api/<mode>`：页面能不能是 public 由它决定

identity 区的第二条 POST，是「页面向自己的后端要数据」的唯一入口。路径写死成一段、不许带点。

**网关根本不看 `runnable`**：`/run` 和 `/api/<mode>` 共用同一句判断（发布了、是 identity、在名单上），
`runnable` 是 `/run` 那条路由自己再查，不满足回 404。**所以页面调只读 mode 不需要 `--runnable`。**

**推论**：匿名区只收 GET/HEAD，所以 **public 页面调不了 `api/<mode>`**。
一张「页面发请求问后端要数据」的页面**只能是 identity 模式**。
要做成 public，必须把结果预先算成文件放进 `dataDir`，前端只渲染。

## 怎么用

模式不是参数，是推导出来的：`--require-identity` / `--allow` / `--runnable` 任一出现即 identity，否则 public。
所以写了 `--allow` 忘了 `--require-identity`，页面依然是登录可见，不会掉回 public。

    frago recipe expose <name> [--slot <slot>]      # public：所有人看同一份
    frago recipe expose <name> --require-identity   # 要登录，每个人看自己那一份
    frago recipe expose <name> --allow <账号id|邮箱> # 只开给点名的人，可重复
    frago recipe expose <name> --runnable           # 那些人还能点运行
    frago recipe expose <name> --force              # 唯一用途：明说要撤掉已有白名单
    frago recipe unexpose <name>
    frago recipe exposed                            # 现状：模式、名单人数、能否运行

**`--slot <名>`（默认 `default`）**

- public 下：唯一被发布的那一份。`?key=` 必须等于它；给两个值直接拒；空值算默认槽。
- identity 下几乎不起作用：读的槽位是**他自己的账号 id**，由服务端从会话算出。
  而且他只要带**任何** `?key=`，网关当场拒——不是忽略，是拒。这时 `--slot` 只决定审计报告描述哪一份。

**`--require-identity`**

未登录一律拒（浏览器导航会被 302 送去门口）。登录用户读 `~/.frago/users/<账号id>/state/<recipe>.json`，
与配方自己的 `app-state/` 物理分开。**页面要能渲染空 state 而不是 500**——第一次打开时那份还没被写过。

**`--allow <账号id|邮箱>`（可重复）**

- **只收账号 id**。邮箱只是查表便利，且**必须是已经登录过的邮箱**，查不到直接报错——
  邮箱没有验证环节，预授权一个没人认领的地址等于挂一张先到先得的门票。
  先让对方登一次，再 `frago user list` 取 id。
- 不在名单上的人拿到的响应与「这页根本没发布」**一模一样**（401 而非 403——403 等于确认这页存在且有人在名单上）。
- 存进 `published.json` 后是四态（`_allow_of`）：无 `allow` 键 = 老记录、所有登录用户；`null` = 同上；
  `["id",…]` = 只这些人；**别的任何东西 = 谁都不行**（NEVER 抢救能认出来的那几项，缺的那半可能正是关键限制）。
- 空名单写不进去，`publish()` 直接抛错。关页面用 `unexpose`。

**`--runnable`**

让名单上的人触发这个配方在服务器上跑一趟，产出落各自的 `~/.frago/users/<账号id>/data/<recipe>/`。四件事：

- **配方要读 `FRAGO_RECIPE_DATA_DIR`**（或建在 `frago_recipe` 基类上），否则直接拒——
  它会把每个人的产出都写进主人那一个目录。检查是字符串搜索，弱是故意的，抓的是「从没考虑过这问题」的配方。
  NEVER 改成 `import frago`：带 PEP 723 块的配方跑在隔离环境里 import 不到。
- **跑的是主人的机器、主人的凭证。** `FRAGO_SECRETS` 按配方名取，没有「谁的凭证」这一维。
  判据不是「这配方有没有 bug」，是「这份源码我信到愿意让陌生人按」。
  **NEVER 把会花钱、会以主人身份对外做事的配方开成可运行。**
- **整份名单一起开**，做不到「这三个能看、那两个能跑」。
- 参数按 `inputs` 严格校验（`enum` / `max_length` / `pattern` / `min` / `max` 逐条查）。主人自己跑不受此约束。

页面这边：`POST /app/<name>/run`，体 `{"params":{…}}`，立刻回 202，**不回配方的返回值**。
结果去 `data/` 读，状态读平台维护的 `data/run.json`（配方 NEVER 自己写这个文件）。同一人同一页串行，第二个 409。

**`--force`**

只有一个用途：**本来有名单、这次没写 `--allow`**——那等于放宽到所有登录用户，默认直接拒绝执行并列出会被撤掉的账号。
首次发布、再次点名、缩小名单、public 页面都不触发。
**NEVER 折进 `--yes`**：`--yes` 是脚本习惯带着的自动化开关，折进去这道锁就白设了。

**`--yes` / `--format json`**

`--format json` **不豁免确认**：不带 `--yes` 时回 `{"code":"confirm_required","notes":[…]}` 并以 1 退出。
那份 `notes` 就是「这次会暴露什么」——**读完再带 `--yes` 回来，NEVER 见非零退出就直接补 `--yes` 重跑**。

**跑之前就会被拒的**：配方不存在；没有 `assets/` 目录；`--allow` 的账号查不到；
该带 `--force` 没带；`--runnable` 但配方不读 `FRAGO_RECIPE_DATA_DIR`；`recipe_checks.audit` 报出致命项。

**贯穿全部的一条**：每跑一次 expose 都是整条写回，**少写一个开关等于关掉它**。
改 `--runnable` 也得把 `--allow` 原样再敲一遍。

读回来时两处刻意的不对称，都往关的方向倒：`mode` 缺键读成 public（老记录当年就是发给匿名读者的）、
认不出来读成 identity；`runnable` 必须严格 `True`（`"true"`、`1` 全读成 False——都是手改文件时想反了的产物）。

## 名单加对了人，页面照样可能是空的

**expose 只回答「谁能打开」。「他看得到什么」是另一个问题，由数据落在谁名下决定。**

登录用户的每一次读都被路由到**他自己名下的目录**，而且这个身份**沿着配方之间的调用继续往下传**：
A 的页面问 plan 要数据，plan 转身问引擎，引擎也是以 A 的身份跑的。
而配方跑出的公共结果落在**算它的那个人**名下（通常是调度或主人）。
于是名单加对了、页面打开了，读的却是空目录，**三层没有一处报错**。
2026-08-26 实测：引擎刚算完 7245 只标的，看板上写着「引擎还没算过任何一天」。

判据：**复制之后原件还会继续更新的东西，必须只有一份。**
解法是把公共结果写进 `~/.frago/recipe-data/<配方>/share/common/`，
并在 `recipe.md` 的 `reads_common` 里列上生产者——声明了才拿得到共读根。**不是改 expose 参数。**

**验收只有一条可信的路**：拿名单上一个真实账号登录进去看。
以主人身份跑出数据**不构成**登录用户看得到数据的证据。

## 页面能拿到什么

反过来的契约——配方声明什么是公开的，别的一概不出去：

    publish("my_recipe", {
        "dataDir": "/Users/me/.frago/data/...",   # 私有，路径永不到客户端
        "public": {"title": "Q3 numbers"},        # 只有这个出去
    })

`dataDir` 底下的文件仍从 `/app/<name>/data/…` 可读。非主人侧 `config.json` 带 `apiBase: null`、`readOnly: true`。
路径两道锁（每个匿名和 identity 入口共用）：不许 `..` / `.` 段，不许任何以点开头的段——后者是被读走过 `.env` 之后加的。

登录后能进哪些页面由 `GET /api/auth/pages` 回答，只回自己进得去的那些，**不回名单本身**。
两个后果：**public 页面永远不出现在门口目录里**（那份列表走 `allows()`，它对 public 记录一律答 False）；
卡片标题取配方的 `description`，整句显示。

**被重置过的账号连这份清单都读不到。** 主人 `frago user passwd <id> --temporary` 之后，
那个账号在换掉临时口令之前只剩三条路（`/api/auth/me`、`/api/auth/password`、`/api/auth/logout`），
页面和页面清单一律拒。详见 `frago book recipe-deploy` 的账号管理一节。

## 什么时候用

- 结果给不特定的人看，且页面不需要向后端要数据 → public
- 页面要调 `api/<mode>` → **只能 identity**
- 按人分数据，或不想让路过的人看见 → identity
- 只给点名的几个人 → `--allow`；他们还要能跑 → 再加 `--runnable`

## 不要做

- **不要在没问清「谁能看、谁能运行」之前就敲 expose。** 默认值是「所有登录用户」，且整条重写，
  猜错的代价是页面对全体注册用户敞开，**没有任何一层会提醒你猜错了**。
- 不要拿主人视角的运行结果当成登录用户看得到数据的证据。那是两个目录，中间没有通道。
- 不要以为「本机能开、图能画出来」说明服务器上也行。本机每个请求都落 `local` 区，测不出任何权限问题。
- 不要拿 identity 当权限系统。`--allow` 决定「谁看得见」，不是「谁能干什么」——名单上的人能力完全相同。
- 不要拿这里的邮箱当真身份，它没验过；更不要用 `--allow` 写一个还没人登录过的邮箱。
- 不要指望公开页面能调 `${apiBase}/recipes/<name>/run` 或 `${apiBase}/file?path=`。登录用户同样拿不到。
- 不要指望 `--runnable` 是沙箱。配方以主人的身份、主人的权限跑，隔离只保证产出落点不串人。
- 不要以为发布一个 slot 等于发布全部；不要把敏感数据放进已发布 slot 的 `dataDir`，那目录整体可读。
- 不要拿 `--force` 当消警告的开关。

## 相关

`frago book recipe-deploy` — 配方怎么送上服务器、反代怎么配、门口页面、服务器上那几个环境变量
`frago book remote-frago` — 本机怎么给服务端下发任务
