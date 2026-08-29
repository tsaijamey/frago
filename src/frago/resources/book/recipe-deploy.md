# recipe-deploy

分类: 效率（AVAILABLE）

## 是什么

人会用一堆词说同一件事：**部署、同步、更新、上传、传上去、发上去、发布、推上去、上线**。
它们指的都是这条链路，但**落在链路的不同段**，而且没有任何一个 frago 命令叫「deploy」——
这条链路是四段拼起来的，中间三段是手工的：

    ① 决定谁能看          ← 只有人能回答，不许猜
    ② 把配方目录送过去     ← rsync，没有 frago 命令
    ③ 在服务器上验一遍     ← 以跑 frago 的那个用户身份
    ④ frago recipe expose  ← 开放，参数由 ① 决定

**用户说「传上去」，可能只想要 ②；说「发布」，多半是 ②③④ 一整条。这两者的差别不能靠猜。**
分不清就问一句，别默认。

## ① 先问清楚谁能看 —— 这一步 NEVER 跳过

**第一次开放没有默认值**：不说清楚谁能看，`frago recipe expose` 直接拒绝执行。
这是有意的——「还没想清楚」的人恰恰就是敲光杆命令的那个人。
猜错的代价是一张页面对全体注册用户敞开，而**没有任何一层会提醒你猜错了**。
所以敲 expose 之前，这三问必须有答案：

1. **谁能打开这张页面？** 三选一：
   - 任何人，不用登录 → `--public`（但页面若调 `api/<mode>` 就开不成 public，见 recipe-expose）
   - 任何登录用户 → `--signed-in`
   - 只有点名的这几个 → `--allow <id>`（可重复）
2. **从哪个根读？** 各人读各人那份 → 不写（默认，读 `users/<账号id>/state/`）；
   **点名的这几个看配方自己那一份** → `--shared`（读 `app-state/<配方>/`，
   路径里没有任何账号；只读，构造上不接受任何运行）。这一问以前无解，见 ⑤。
3. **页面上要不要有按钮？** 这一问 expose 回答不了：能按什么写在**配方**的 `recipe.md` 的
   `page_actions` 里，由写配方的人逐个点名。`--runnable` 已经取消。

改动已开放的页面是**增量**的：只改你点到的字段，没写 `--allow` 不会把名单清掉。
放宽必须说出口——`--deny` / `--only` / `--signed-in` / `--public`。`--force` 因此也取消了。

**先跑 `frago recipe exposed` 看现状**，再拿现状去跟用户对答案。不要凭上一次会话的记忆报名单。

细节全在 `frago book recipe-expose`——特别是「未登录的人 / 登录用户 / 主人」这三个词的严格区分，
以及为什么**主人不是一个账号**。在讨论权限时使用「访客」这个词一律视为错误，它同时盖住了登录和未登录两种人。

## ② 查清那台机器，再动它

**这一段的事实在历史里，不在代码里，推理推不出来。** 本会话第一次碰这台机器，先召回：

    frago session search "<机器名> 配方 部署"
    frago frago-recipe-ops find

必须问出答案的三件事：

- **跑 frago 的是哪个 unix 用户？** `ssh <别名>` 登进去的那个用户**通常不是**它。
  两者不一致时你在 SSH 里敲的 `frago` 读的是**另一份** `~/.frago`——版本、账号、已开放页面全对不上，
  你看到的是一份过期快照。判据：`pgrep -af frago.server.runner`。
- **frago 装在哪、怎么重启？** 部署机往往是 git + `uv build` + systemd，不是 `frago server restart`。
- **配方目录在哪？** 用命令问，NEVER 猜路径：

      frago recipe info <name> --format json | jq -r .base_dir

  配方分 `atomic/chrome/`、`atomic/system/`、`workflows/` 三处，**直接写死 `workflows/` 会漏**——
  例如 `frago_login_portal` 就在 `atomic/system/` 下。

一个反复踩的坑：`ssh box 'sudo -u ubuntu bash -lc "…"'` 的 cwd 是 `/root`，那个用户读不了，
报出来是 `Permission denied: '/root/.frago/.env'`，看起来像权限配错了，其实只是工作目录不对。
解法：脚本第一行 `cd ~`，或者用 `sudo -iu <user>`（login shell，cwd 归位）。
命令里引号超过两层时，**写成 `.sh` scp 上去再跑**，比在三层转义里拼可靠得多。

## ③ 送代码

先 dry-run，看清楚要删什么再真跑：

    SRC=$(frago recipe info <name> --format json | jq -r .base_dir)
    rsync -rin --delete --exclude='__pycache__' --exclude='*.pyc' \
          "$SRC/" <box>:<远端 frago 家目录>/recipes/<同样的相对路径>/<name>/

    # 看过 dry-run 之后去掉 n
    rsync -ri  --delete --exclude='__pycache__' --exclude='*.pyc' "$SRC/" …

两件必做的收尾：

- **`--delete` 是必要的**：本机删掉的文件不删远端，页面会继续加载一份早就该消失的旧 JS，
  而且它「能跑」，只是行为对不上——比缺文件更难查。
- **属主归位**：如果你是以 root 或另一个用户 rsync 过去的，跑一次
  `chown -R <跑frago的用户>:<组> <目标目录>`。否则配方跑起来写不了自己的数据目录。

送完核对一次，别信 rsync 的退出码：

    # 对几个关键文件比 hash，本机 shasum -a 256 / 远端 sha256sum
    for f in assets/app.js recipe.py; do … done

## ④ 在服务器上验，以那个用户的身份

    frago recipe validate <name>
    frago recipe run <name> --params-file /tmp/p.json      # 冒烟

`frago recipe validate` **不执行模块，因此查不出「引用了一个不存在的函数」**。
2026-08-26 实测：某个 lib 里有个函数被 import 两次却没有定义，validate 报 OK，
直到别的配方通过总线调它才炸 ImportError。

**冒烟的正确办法**：用一个**不存在的 mode** 跑一遍。模块能加载就会正常报「未知 mode」，
加载不了会报 ImportError / NameError——一次调用同时验了「文件到位」和「模块能 import」。

还要知道：**服务器算得比本机慢**（2026-08-26 同一份代码同一个池子实测约 8 倍：本机 18.6 秒/天，服务器约 2.5 分钟/天）。
排调度间隔、估回补耗时，按服务器的数字算，不能拿本机的推。

## ⑤ 数据从哪来 —— 开放之前必须想清楚的那一问

页面能打开 ≠ 页面上有东西。默认下（各人读各人那份）登录用户的每一次读都被路由到
**他自己名下的目录**，而且这个身份**沿着配方之间的调用继续往下传**。
配方跑出来的公共结果落在**算它的那个人**名下（通常是调度或主人）。
于是名单加对了，页面打开了，读的却是一个空目录，**三层没有一处报错**。

先判性质，判据一句话：**复制之后原件还会继续更新的东西，必须只有一份。**

- **这几个人本来就该看配方自己算的那一份** → `frago recipe expose <name> --allow … --shared`。
  一条命令，不动数据，页面直接读配方自己的槽和那个槽声明的 `dataDir`。
- **数据要给别的配方读** → 写机器级共读目录 `~/.frago/recipe-data/<配方>/share/common/`，
  读的那个配方在 `recipe.md` 的 `reads_common` 里列上生产者，
  **再由主人 `frago recipe grant <读的人> --read <被读的人>` 授权**。
  声明是请求（由得利的一方写），授权才是许可。两半缺一不可，
  运行时只拿得到「既声明又授权」的那些，`frago recipe validate` 会说缺的是哪一半。

**验收只有一条可信的路**：拿名单上一个真实账号登录进去看一眼。
以主人身份（本机、或带 token 直连）跑出数据，**不构成登录用户看得到数据的证据**。

## ⑥ 开放

按 ① 的答案选参数，细节见 `frago book recipe-expose`：

    frago recipe expose <name> --public                    # 谁都能看，不用登录
    frago recipe expose <name> --signed-in                 # 任何登录用户
    frago recipe expose <name> --allow <id> --allow <id>   # 只有这几个，各看各的
    frago recipe expose <name> --allow <id> --shared       # 这几个看配方自己那一份（只读）

`--format json` **不豁免确认**：不带 `--yes` 时它回 `{"code":"confirm_required","notes":[…]}` 并以 1 退出。
那份 `notes` 就是「这次会暴露什么」的清单，**读完再带 `--yes` 回来**，不要看到非零退出就直接补 `--yes` 重跑。

## ⑥b 页面上的按钮：从旧机器搬过来时必然要处理的一件事

**2026-08-29 之前开放的页面，`published.json` 里可能带着 `runnable: true`。升级之后那个键不授予任何东西了**，
于是那些页面的按钮一律失效，而页面本身照常打开——**没有任何一层报错**，只有人点下去没反应。
`frago recipe exposed` 会把还带这个键的记录单独列出来提醒。

先分清哪些是真损失。带 `runnable` 不等于页面真在用它：

    # 这张页面到底走不走访客那条运行门？
    grep -rn "fetch(.\?run\|'./run'\|appBase}run" <配方目录>/assets

- 只有 `${cfg.apiBase}/recipes/<名>/run` 这一种写法 → **零损失**。登录用户的 `apiBase` 是 `null`，
  那条路径拼出来是 `null/recipes/…`，从来没通过。2026-08-29 在 demo 上实测到一张这样的页面。
- 出现相对路径 `run` / `'./run'` / `${appBase}run` → **访客真在用**，不补声明按钮就是死的。

要恢复，改的是**配方**不是 expose：

    # recipe.md
    page_actions: [save, refresh]     # 页面能触发哪几个 mode，逐个点名

三条硬约束，写之前逐条对：

1. **与 `exports` 不许有交集。** 导出的 mode 按契约只读，页面直接 `POST /app/<名>/api/<mode>` 就能读，
   不需要按钮；两边都写 `frago recipe validate` 直接报错。
2. **配方 MUST 读 `FRAGO_RECIPE_DATA_DIR`**（或建在 `frago_recipe` 基类上），否则 validate 报错——
   不然每个人按下去写的都是配方写死的那同一个目录。
3. **页面 MUST 在 body 里点名 mode**：`{"params": {"mode": "save", …}}`。不写 mode 一律 403。
   平台不替你解析配方的默认 mode——那个默认在类里、这条路由看不见，「解析」实际上是「猜」，
   而猜错就是授权了一个 mode、跑了另一个。**这一条在作者自己机器上测不出来**：主人那条路根本不查声明，
   所以缺 mode 的页面在你机器上一切正常、只在服务器上以登录用户身份打开才坏。

**这是权限决定，不是格式转换。** 往 `page_actions` 里写一个 mode，等于让**每一个能打开这张页面的人**
在这台服务器上、用这台机器配好的凭证跑那段代码。所以逐条问：

    这张页面开给谁？        --allow 点名的几个 / --signed-in 全体注册用户
    这个 mode 会做什么？    改本地数据 / 花钱 / 以你的名义对外发东西
    最坏情况谁来承担？

`--signed-in` 的页面尤其要停一下：它对**全体注册用户**开放，而注册在这台机器上是「首次登录即建号」。
旧模型下它可能带着 `runnable: true`，但那是「看得见就全能按」的连带结果，未必是当时真想给的——
**升级正好是重新问一遍这个问题的时机，不要照着旧值恢复。**

**`--shared` 的页面无论声明了什么都不接受运行**（没有人有自己的目录），所以这一节对它不适用。

## ⑥c 配方不跟着仓库走，两台机器各改一遍

`page_actions` 写在 `recipe.md` 里，而配方住在 `~/.frago/recipes/`，**不在 frago 仓库里**。
本机改完要 rsync 过去（见 ③），或者两边各改一遍再比 hash。
**NEVER 只改服务器那份**：下一次从本机同步会把它覆盖回去，而且是静默的。

## ⑦ 服务器这一侧：门口、反代、环境变量

**这三个默认值在服务器上必须改（个人机器上不要动）：**

    FRAGO_SERVER_HOST=127.0.0.1    # 只有反代碰得到
    FRAGO_TRUST_LAN=0              # 同网段的邻居不算「本机」
    FRAGO_BEHIND_PROXY=1           # 干脆不从对端地址推断信任

第三条是兜底。靠「有没有反代转发头」判断请求是不是本机来的，本质是在猜别人家反代的行为，猜错就是敞开。
置位后公开区照常，其余一律要 token。
（容器里 `FRAGO_TRUST_LAN` 默认就关着；CGNAT 段 100.64/10（Tailscale）在 Python 3.13+ 上**不算**私网，tailnet 邻居要 token。）

**反代只放一个前缀**，identity 模式再多放登录接口并限速：

    location /app/      { proxy_pass http://127.0.0.1:8093; }
    location /api/auth/ { limit_req zone=frago_login burst=5 nodelay; proxy_pass http://127.0.0.1:8093; }
    location /          { return 404; }

配方声明了 `page_actions` 的话 `/app/` 也要限速——那底下的 `POST .../run` 会在服务器上起进程。
平台自己那两层兜底挡的是并发，不是频率。

**identity 模式再多三个环境变量：**

    FRAGO_LOGIN_PORTAL=<门口配方名>   # 优先级最高；空字符串=关掉跳转。
                                     # 不设时读登记表（expose --portal），再兜底 frago_login_portal
    FRAGO_TRUSTED_PROXIES=127.0.0.1  # 让按 IP 限速这层成立
    FRAGO_SIGNUP_GATE=<共享口令>      # 建号要口令，只走请求体，NEVER 拼进 URL

**`FRAGO_BEHIND_PROXY=1` 而不配 `FRAGO_TRUSTED_PROXIES` 时**，没有任何地址可信，按 IP 的登录限速自动关闭，
于是 `FRAGO_SIGNUP_GATE` 变成强制且关不掉。`frago server` 启动时会把这句警告打出来。

**登录门口**：未登录的人打开 identity 页面，本来会收到一句写给机器看的 401（它提的 token 那人既没有也不该有）。
现在服务器把他 `302 → /app/<门口>/?next=<配方名>`。门口是**具名**的不靠猜，否则第二张公开页面一开就会悄悄换一扇门。
门口现在登记在 `published.json` 里（`frago recipe expose <门口> --public --portal`），
`frago recipe exposed` 看得见，一台机器只能有一个，第二次登记会指名现任并拒绝。

跳转的五个条件缺一不可：GET/HEAD 且 `Accept` 含 `text/html`（页面自己的 `fetch` 要 JSON，跳过去会变成莫名其妙的解析错误）；
目标是 identity 模式的已发布页面；门口不跳自己；**门口自己必须是 public 模式的已发布页面**（否则只是多绕一步的 401）；
响应带 `no-store`。

门口页面**不随 frago 发布**，是一张自己写的 User 配方（本机与服务器上都叫 `frago_login_portal`），
认 `?next=<配方>`。要用这套跳转，门口配方得先自己
`frago recipe expose <门口> --public --portal`。
那张页面按访客浏览器语言中英自动切换；未登录时只有登录表单和一条「返回首页」，不列任何页面清单
（登录之后才列，且是服务端按人算的那份）。

**账号管理**（身份是「邮箱 + 自设密码，首次登录即建号」，**邮箱不做验证**，没有找回流程）：

    frago user list                          # id ↔ 邮箱，每行标 unverified
    frago user passwd <id|邮箱>              # 隐藏输入，顺带吊销这个人全部会话
    frago user passwd <id|邮箱> --temporary  # 发一段临时口令，那个人必须自己换掉
    frago user disable <id|邮箱>             # 下一次请求即失效
    frago user session list / revoke <id>

`frago user session` 是登录会话，与顶层 `frago session`（agent 会话记录）是两回事。

**`--temporary` 是「替别人重置」那条路**（访问控制台上的「重置密码」按钮走的也是它）。
没有找回流程，所以「我忘了密码」最后一定落到主人手上，而主人给出去的那段口令自己也知道。
于是重置一次做三件事：旧密码作废、那个人所有登录一起断掉、账号被标成**欠一次改密**——
在他设一个自己的密码之前，服务端只放行「看自己是谁 / 改密码 / 退出登录」，
**连 `/api/auth/pages` 都拒**，一张页面也打不开。他一改完，锁当场解开。
`frago user list` 里这种账号标着 `must-change-password`。

口令由机器生成，不收外面传进来的值（没有 `--password`，网页上也没有填的地方）：
网页上填的东西会变成配方参数，而配方参数是 argv 的一个元素，同机任何账号 `ps -ww` 都看得见。
门口页面靠登录回执与 `/api/auth/me` 里的 `mustChangePassword` 换成「先设一个你自己的密码」那一屏——
那只是渲染依据，拦人的是网关。

## 不会跟着配方一起过去的东西

rsync 搬的只有代码。这些是每台机器自己的登记，**必须在服务器上重来一遍**：

- **调度**：`frago schedule` 是本机登记。2026-08-26 实测本机 21 条一条都没跟过去。
- **channel / 通知**：服务器上通常没有 channel，`--notify-to desktop` 在那种机器上没有意义。
- **凭证**：`FRAGO_SECRETS` 是那台机器自己的。
- **数据**：`recipe-data/` 不该 rsync——服务器上的那份是它自己跑出来的。
- **已开放清单**：`~/.frago/published.json` 也是每台机器一份。

## frago 本身要不要一起升

配方引用了新版 frago 才有的能力时才需要。顺序（2026-08-26 实测走通）：

    ① 本机 git push（推 main——服务器拉的就是它）
    ② 服务器上以那个用户身份 cd <仓库> && git pull --ff-only
    ③ uv build --wheel
    ④ uv tool install --force "$(ls -t dist/frago_cli-*-py3-none-any.whl | head -1)"
    ⑤ systemctl --user restart frago-server

**第四步 NEVER 写成 `dist/*.whl`。** dist/ 里躺着历次构建的所有 wheel，通配一次展开出好几个，
`uv tool install` 只收一个包名，当场报 Usage 退出——而前面 build 是成功的，
于是**版本号纹丝不动，看起来像升级完了**。2026-08-29 实测踩到：build 报
`Successfully built frago_cli-1.2.192`，紧接着 `frago --version` 还是 1.2.190。

**仓库在哪不要猜。** 它未必在跑 frago 那个用户的家目录下（demo 这台在 `/www/wwwroot/frago`）。
反查装的是哪个 wheel、从哪个仓库来：

    cat ~/.local/share/uv/tools/frago-cli/uv-receipt.toml

**第五步必须走 systemd，不是 `frago server restart`**：环境变量来自 unit 里的
`EnvironmentFile=…/server.env`，绕过 systemd 重启会丢掉那几个安全变量（`FRAGO_BEHIND_PROXY` 就在里面），
而丢了之后**服务照常起来**，只是把整个 API 对反代后面的所有人敞开了。
以 root 执行 `systemctl --user` 要补 `XDG_RUNTIME_DIR=/run/user/$(id -u <user>)` 与 `DBUS_SESSION_BUS_ADDRESS`。

## 什么时候用

- 用户说「把这个配方部署 / 同步 / 传 / 发 / 发布到服务器」——不管用哪个词，走这一篇
- 服务端要产出一个给别人看的页面
- 本机改完配方，服务器上那份要跟上

## 不要做

- **不要在没问清「谁能看」之前就 expose。** 第一次开放没有默认值，会被拒；
  但改一张已开放的页面不会拦你，想清楚再敲。
- **不要把「部署」和「开放」当成一件事。** 送代码上去不等于别人看得见；expose 了不等于别人看得到数据。
- 不要猜配方目录在哪。`frago recipe info --format json` 里的 `base_dir` 是唯一可信的答案。
- 不要假设 `ssh <别名>` 的那个用户就是跑 frago 的用户。先 `pgrep -af frago.server.runner`。
- 不要跳过 rsync 的 dry-run。`--delete` 删错目录这件事没有撤销。
- 不要拿本机跑通当作服务器跑得通的证据。本机每个请求都落在主人区，测不出任何权限问题；本机也没有登录这回事。
- 不要 rsync `recipe-data/`。数据是那台机器自己的。
- 不要用 `frago server restart` 重启部署机上的服务。那会丢掉 systemd unit 里的安全环境变量。
- 不要把运维类任务（改 nginx、看日志、查进程）走 `frago remote`。直连 SSH 更稳，控制面也不用上公网。

## 相关

`frago book recipe-expose` — 开放之后谁能看到什么，四个区、三种人、每个参数的效果
`frago book remote-frago` — 本机怎么给服务端那个 agent 下发任务书
`frago frago-recipe-ops find` — 这台机器上历次部署踩过的具体坑
