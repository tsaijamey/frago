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
| 身份 | identity 模式已发布 recipe 的同一批地址，外加四个 `/api/auth/**` | 要登录 cookie、只读、config 过滤强度与公开区相同 |
| 私有 | 其余全部（`/api/**`、`/ws`、viewer、SPA） | 必须 `Authorization: Bearer <token>` |

登录用户不是弱化的主人：`/api/file`、`/api/agent`、`/api/recipes/<n>/run` 三条对他一律 401。

## 怎么用

开放模式两种，一次只能是其中一种：

    frago recipe expose <name> [--slot <slot>]    # public：所有人看同一份，开放前列出会暴露什么
    frago recipe expose <name> --require-identity # identity：要登录，每个人看自己那一份
    frago recipe expose <name> --yes --format json
    frago recipe unexpose <name>
    frago recipe exposed                          # 当前对外可见的清单，带模式

**public 模式**发布的是数据：`--slot` 指定的那一份，谁来都是这一份。
只暴露三样：recipe 的 `assets/`、该 slot 的 `public` 块、该 slot `dataDir` 下的文件。

**identity 模式**发布的是地址：匿名打开得 401，登录后读的是以自己账号 id 命名的 slot，
落在 `~/.frago/app-state-users/<recipe>/<id>.json`，与配方自己的 `app-state/` 物理分开。
读哪一份由服务端从会话算出来，URL 里写什么都不作数。适合按人分数据的页面（练习器、各填各的表单）。
访客还没被写过数据时读到空 state，页面要能渲染空数据而不是 500。

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
- 不要拿 identity 模式当权限系统。所有登录用户能力完全相同，差别只在读谁的数据；也不要拿这里的邮箱当真身份，它没验过。
- 不要以为发布一个 slot 等于发布全部 slot。`--slot` 之外的 slot 仍然是私有的。
- 不要把敏感数据放进已发布 slot 的 `dataDir`。那个目录整体可读。

## 相关

`frago book remote-frago` — 本机怎么给服务端下发任务
