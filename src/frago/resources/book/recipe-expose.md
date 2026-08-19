# recipe-expose

分类: 效率（AVAILABLE）

## 是什么

`/app/<recipe>/` 是 recipe 页面的固定地址。在个人机器上它只有本人能开；在服务器上，它是唯一值得对公网开放的东西 —— recipe 页面就是成品。

开放是逐个 recipe 显式打开的。注意 `frago recipe publish` 是另一回事——那是配方把自己这次运行的状态发布给页面读，与对外开放无关。

开放，默认全关。服务端把请求分四类：

| 区 | 范围 | 要求 |
|---|---|---|
| 本机 | 源是回环或局域网地址、且没有反代转发头 | 无条件放行（本机 CLI、桌面端、recipe 回调、手机开 workbench 照旧） |
| 公开 | public 模式已发布 recipe 的 `/app/<name>/**` 的 GET | 免 token、只读、config 经过滤 |
| 身份 | identity 模式已发布 recipe 的同一批地址（在名单上才算），外加五个 `/api/auth/**`，以及 `--runnable` 页面的 `POST /app/<name>/run` | 要登录 cookie；除那一条 POST 外只读；config 过滤强度与公开区相同 |
| 私有 | 其余全部（`/api/**`、`/ws`、viewer、SPA） | 必须 `Authorization: Bearer <token>` |

登录用户不是弱化的主人：`/api/file`、`/api/agent`、`/api/recipes/<n>/run` 三条对他一律 401。

## 怎么用

模式仍然是两种（public / identity，一次只能是其中一种），`--allow` 与 `--runnable` 是在 identity 上再收窄：

    frago recipe expose <name> [--slot <slot>]      # public：所有人看同一份，开放前列出会暴露什么
    frago recipe expose <name> --require-identity   # identity：要登录，每个人看自己那一份
    frago recipe expose <name> --allow <账号id|邮箱> # 只开给点名的人，可重复；蕴含 identity
    frago recipe expose <name> --runnable           # 那些人还能点运行；蕴含 identity
    frago recipe expose <name> --yes --format json
    frago recipe unexpose <name>
    frago recipe exposed                            # 当前对外可见的清单，带模式、名单人数、能否运行

**public 模式**发布的是数据：`--slot` 指定的那一份，谁来都是这一份。
只暴露三样：recipe 的 `assets/`、该 slot 的 `public` 块、该 slot `dataDir` 下的文件。

**identity 模式**发布的是地址：匿名打开得 401，登录后读的是以自己账号 id 命名的 slot，
落在 `~/.frago/users/<账号id>/state/<recipe>.json`，与配方自己的 `app-state/` 物理分开。
读哪一份由服务端从会话算出来，URL 里写什么都不作数。适合按人分数据的页面（练习器、各填各的表单）。
访客还没被写过数据时读到空 state，页面要能渲染空数据而不是 500。

**`--allow` 只收账号 id。** 写邮箱只是查表便利，且**必须是已经登录过的邮箱**，查不到直接报错。
原因是邮箱没有验证环节：预授权一个还没人认领的地址，等于挂一张先到先得的门票，
谁先拿这个地址登录谁就进来了。先让对方登一次，再 `frago user list` 取 id。
不在名单上的人拿到的响应与「这页根本没发布」**一模一样**（同状态码同响应体），
不构成「这页存在吗」的探针。想让页面对谁都不开放用 `unexpose`，别写空名单。

**`--runnable` 让名单上的人能触发这个配方跑一趟**，产出落进各自的
`~/.frago/users/<账号id>/data/<recipe>/`。三件事必须先想清楚：

- **配方要读 `FRAGO_RECIPE_DATA_DIR`**，一行 `os.environ.get("FRAGO_RECIPE_DATA_DIR") or 自己的老默认值`。
  不读的配方 `expose --runnable` 直接拒绝——它会把每个访客的产出都写进主人那一个目录。
  NEVER 改成 import frago：带 PEP 723 块的配方跑在隔离环境里，import 不到。
- **跑的是主人的机器、主人的凭证。** `FRAGO_SECRETS` 按配方名取，没有「谁的凭证」这一维。
  所以判据不是「这配方有没有 bug」，是「这配方的源码我信到愿意让陌生人按」。
  **NEVER 把会花钱、会以主人身份对外做事的配方开成可运行**（下单、发帖、发信、调计费 API）。
- **参数按 `inputs` 严格校验**：没声明的参数一律拒，`enum` / `max_length` / `pattern` / `min` / `max`
  逐条查。主人自己跑不受这条约束，只在日志里提示。

页面这边：`POST /app/<name>/run`，请求体 `{"params": {...}}`，立刻回 202 `{"accepted": true}`，
**不回配方的返回值**。结果自己去 `data/` 里读，运行状态读平台维护的 `data/run.json`
（`running` / `done` / `failed`，这个文件名保留，配方 NEVER 自己写）。
同一个人同一个页面同时只能跑一个，第二个得 409。

登录后想知道自己能进哪些页面：`GET /api/auth/pages`，只回自己进得去的那些，
带标题和能不能运行，**不回名单本身**。门口页面靠它按人渲染目录。

身份是「邮箱 + 自设密码，首次登录即建号」，**邮箱不做验证**——它只是把手，
谁先用这个地址登录谁就占着它，所以不要在身份上挂有价值的东西。没有找回流程，主人重置：

    frago user list                    # 谁来过：id ↔ 邮箱，每行标 unverified
    frago user passwd <id|邮箱>        # 隐藏输入，顺带吊销这个人全部会话
    frago user disable <id|邮箱>       # 下一次请求即失效，不等会话过期
    frago user session list / revoke <id>

注意 `frago user session` 是登录会话，与顶层 `frago session`（agent 会话记录）是两回事。

页面要给访客看的值，写进 slot state 的 `public` 子字典：

    publish("my_recipe", {
        "dataDir": "/Users/me/.frago/data/...",   # 私有，访客拿不到这个路径
        "public": {"title": "Q3 numbers"},        # 访客只能拿到这个
    })

访客侧 `config.json` 会带 `apiBase: null` 和 `readOnly: true`。

反代只放一个前缀：

    location /app/ { proxy_pass http://127.0.0.1:8093; }
    location /     { return 404; }

用 identity 模式时反代还要多放一个前缀（登录接口），并给它配限速：

    location /api/auth/ { limit_req zone=frago_login burst=5 nodelay; proxy_pass http://127.0.0.1:8093; }

用了 `--runnable` 的话，`/app/` 这个前缀上也要配限速——那底下的 `POST .../run` 会在服务器上起进程，
比读一个文件贵得多。平台自己有两层兜底（同一人同一页串行、访客并发上限独立于主人），
但那两层挡的是并发，不是频率。

服务器上还要改三个默认值（个人机器上不要动）：

    FRAGO_SERVER_HOST=127.0.0.1    # 只有反代碰得到
    FRAGO_TRUST_LAN=0              # 同网段的邻居不算「本机」
    FRAGO_BEHIND_PROXY=1           # 干脆不从对端地址推断信任

第三条是兜底：靠「有没有反代转发头」判断请求是不是本机来的，本质是在猜别人家反代的行为，
猜错就是敞开。置位后公开区照常，其余一律要 token，转发头设不设都不影响。

identity 模式再多两个（防灌账号）：`FRAGO_TRUSTED_PROXIES=127.0.0.1` 让按 IP 限速这层成立，
`FRAGO_SIGNUP_GATE=<共享口令>` 建号要口令。前者不配时后者自动变成不可关——缺的那层要被顶上。
口令只走请求体，NEVER 拼进 URL（会进 access log、浏览器历史和 Referer）。

## 什么时候用

- 服务端跑出来的结果要给别人看（客户、同事、公开看板）→ public
- 同一个页面要按人分数据，或者不想让路过的人看见 → identity

## 不要做

- 不要指望公开页面还能调 `${apiBase}/recipes/<name>/run` 或 `${apiBase}/file?path=`。那两个接口能在服务器上执行脚本、读任意文件，公开页面一律拿不到。要公开的 recipe，把结果预先算进 `dataDir`，前端只渲染。登录用户同样拿不到。
- 不要拿 identity 模式当权限系统。`--allow` 决定的是「谁看得见」，不是「谁能干什么」——名单上的人能力完全相同，差别只在读谁的数据；也不要拿这里的邮箱当真身份，它没验过。
- 不要用 `--allow` 写一个还没人登录过的邮箱。那不是预授权同事，是先到先得。
- 不要把「跑起来会花钱、会以主人身份对外做事」的配方开成 `--runnable`。凭证是配方的，不是人的，访客用的是你的那份。
- 不要指望 `--runnable` 是沙箱。它不是——配方以主人的身份、主人的权限跑，隔离只保证产出落点不串人。判据是「这份源码我信不信得过」。
- 不要以为发布一个 slot 等于发布全部 slot。`--slot` 之外的 slot 仍然是私有的。
- 不要把敏感数据放进已发布 slot 的 `dataDir`。那个目录整体可读。

## 相关

`frago book remote-frago` — 本机怎么给服务端下发任务
