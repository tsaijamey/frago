# browser-usage

frago browser 操作完整指南。所有浏览器操作通过 frago browser 命令执行，不直接调用 CDP 或浏览器 API。

唯一例外是把配方页面交给人看：那种页面用 `frago recipe open <url>` 开在用户的系统默认浏览器里，与本文讲的受控浏览器无关，agent 也控制不了它（见 `frago book interactive-recipe`）。除此之外，凡是 agent 自己要读、要点、要抓的页面，都走下面的命令。

## Group：你自己的那一格浏览器

**一个 group 就是浏览器标签栏上一个真的标签组**，组名写在上面，人扫一眼
就知道这几页是谁开的。你开的每一个页面都进这个组，别的 agent 开的页面
在别的组里——两边看不见彼此，也碰不到彼此。

每条 tab 操作命令 MUST 带 `--group`，否则报错 `NO_GROUP`。

  frago browser navigate <url> --group <name>
  frago browser get-content --group <name> [selector]
  frago browser click --group <name> <selector>
  frago browser exec-js --group <name> <js>
  frago browser screenshot --group <name> <output_file>

recipe/run 环境中 `FRAGO_CURRENT_RUN` 环境变量作为 fallback，此时可省略 `--group`。

四条规矩，记住这四条就够了：

1. **一个 group 最多 5 个标签。** 满了再开会失败，并把组里现有的 5 个
   页面列给你，让你自己决定关掉哪个——不会偷偷替你关掉最旧的那个。
2. **navigate 默认替换，不新开。** 替换的是这个 group「当前的那个标签」
   （最后一次 navigate 或 switch-tab 指到的），不是浏览器里正在显示的
   那个——人可能正看着自己的页面，那页永远不会被你换掉。
3. **要新开一页就加 `--new`。** 这是唯一的开页方式。
4. **用完 `group-close`。** 忘了也有兜底：整整 30 分钟没有任何动静
   （命令、切换激活、页面内滚动都算动静），整组自动关掉。

下面这些命令不需要 `--group`（管理类，或自己就是全局操作）：

  start  stop  status  check  detect  wait  reset
  groups  group-info  group-close  group-cleanup

除此之外的每一条都必须有 group，缺了会报 `--group/-g required`。
**注意 `list-tabs` / `switch-tab` / `close-tab` 现在也必须带 group**——它们
只看得见、也只动得了本 group 的标签。
`detect` 和 `wait` 两条可带可不带：`detect` 带上就从「列已装浏览器」变成「探测当前页反爬」，`wait` 带上才等在该 group 的页面上。

## Group 查询与收尾

  frago browser groups               # 所有 group：几个标签、还有多久过期
  frago browser groups --json        # JSON 格式
  frago browser group-info <name>    # group 详情：标签清单、当前标签、闲置时长
  frago browser group-close <name>   # 用完了就关——这是你的收尾动作
  frago browser group-cleanup        # 清掉标签已不存在的僵尸 group
  frago browser reset                # 关掉除落地页外的所有 tab（有 FRAGO_CURRENT_RUN 时只清本 group）

## 导航

  frago browser navigate <url> --group <name>          # 替换 group 当前标签
  frago browser navigate <url> --group <name> --new    # 在 group 里新开一个标签

不带 `--new` 时导航的是这个 group 的**当前标签**：最后一次 navigate 或
switch-tab 指到的那一个。它不是「浏览器里激活的那个标签」——agent 常年在
后台干活，人眼前的页面不归你换。

带 `--new` 就在同一个 group 里再开一页，最多 5 页。到顶了会这样告诉你：

  GROUP_TAB_LIMIT: group 'research' already holds 5 tabs (limit 5).
    * [1234] 某某页面
      [1235] 另一个页面
      ...
    → frago browser close-tab --group research <tab_id>
    → frago browser navigate <url> --group research   # 替换当前标签
    → frago browser group-close research

看到这个不要换个 group 名绕过去——那只会在标签栏上堆出第二个组。按提示
关掉一个不再需要的标签，或者改成替换。

URL 来源必须可信：用户提供、页面提取、搜索结果、recipe 输出。禁止凭记忆构造 URL。

不确定 URL 时，洋葱剥皮：先导航到已知首页 → exec-js 提取链接 → 用真实链接导航。

搜索用 Google：`frago browser navigate "https://google.com/search?q=..." --group <name>`

## 内容提取

  frago browser get-content --group <name> [selector]       # 提取文字和链接
  frago browser get-title --group <name>                    # 只要标题
  frago browser exec-js --group <name> <js> --return-value  # 提取结构化数据

选择器是位置参数，`get-content` 没有 `--selector` 这个 flag。

抓回来的内容如果是 "Just a moment…" / "verify you are human" / 403 / 内容明显缺失，那是撞上反爬了，不是页面没加载好。**不要重试 navigate 或 click**，先 `frago browser detect --group <name>` 判档，处理办法见 `frago book browser-anti-bot`。

截图不用于阅读内容，仅用于验证状态和调试。

## 页面状态

  frago browser wait --group <name> 2        # 等待秒数，支持小数
  frago browser zoom --group <name> 0.8      # 缩放，1 为原始大小
  frago browser check                        # 各浏览器是否可用、走哪个后端、是否在跑

## 交互

  frago browser click --group <name> <selector>             # JS-first，自动 fallback 坐标点击
  frago browser click --group <name> <selector> --precise   # 强制坐标级（canvas、拖拽起点）
  frago browser scroll --group <name> 800                   # 按像素，负数向上
  frago browser scroll --group <name> down|up               # 别名，等于 ±500
  frago browser scroll --group <name> page-down|page-up     # 别名，等于 ±800
  frago browser scroll-to --group <name> <selector>         # 滚动到元素

scroll 回报的是**实际位移**不是你要的距离，别拿请求值当结果：

  scrolled   真的滚了多少像素，0 就是一步没动
  at_bottom  已经到底，再滚也没有
  hidden     页面自认不可见——这是滚不动的头号原因，见下
  activated  这次有没有把 tab 置前（只有你显式要求才可能为 true）
  hint       滚不动时告诉你卡在哪、下一步该怎么办

**运行条件：目标 tab 必须是它所在窗口的当前 tab。** x.com 这类按可见性
渲染的站点，在后台 tab 里整条推文流根本不铺开（实测：后台时整页可滚余量
53px、只渲染 1 条推文；置前后立刻 4854px、28 条，且随滚动继续续载）。

**默认不动浏览器的可见状态。** 页面在后台滚不动就如实返回 `scrolled: 0`
外加 hint，不会擅自把人眼前的页面换掉。确实需要时显式加 `--activate`：

  frago browser scroll --group <name> 800 --activate

它只把该 tab 切成它自己窗口内的当前 tab，不动窗口焦点、不抢应用焦点
（这点与 switch-tab 不同，后者语义上就是要激活窗口）。`scroll-to` 同款开关。

窗口被最小化时页面同样自认不可见：已经铺开的内容还能滚，但不再续载新内容，
此时 `--activate` 也没用，只能靠人恢复窗口——hint 会这么说。

## 选择器

稳定性排序：aria-label / data-testid > 语义 ID > 语义 class > 结构选择器。避免 CSS-in-JS 生成的 class（.css-*、._*）。Twitter 用 data-testid，YouTube 用 aria-label。

验证选择器：`frago browser highlight --group <name> <selector>` 或 `exec-js "document.querySelector(...) !== null"`

## 视觉辅助

  frago browser highlight --group <name> <selector>         # 红色边框
  frago browser pointer --group <name> <selector>           # 指针标记
  frago browser spotlight --group <name> <selector>         # 聚光灯
  frago browser annotate --group <name> <selector> --text "说明"
  frago browser underline --group <name> <selector>         # 文字逐行下划线动画
  frago browser clear-effects --group <name>                # 清除所有效果

## Tab 管理（全部在 group 内）

  frago browser list-tabs --group <name>                  # 本组的标签清单
  frago browser switch-tab --group <name> <id>            # 让后续命令改落在这一页
  frago browser switch-tab --group <name> <id> --activate # 顺便把它切到人眼前
  frago browser close-tab --group <name> <id>             # 关掉本组的一页

`list-tabs` 只列本 group 的标签，带 `*` 的那个是**当前标签**——你不带 `--new`
的 navigate、你的 click / get-content / screenshot，全落在它上面。
`<id>` 可以只写前几位。

`switch-tab` 换的是「接下来的命令作用在哪一页」，默认**不动**浏览器的可见
状态：人可能正看着别的东西。真要切到人眼前，显式加 `--activate`。

`close-tab` 只能关本 group 的标签。关别人的页面——不管是别的 agent 的还是
人自己的——这条命令一概拒绝。组满了要腾位置，靠的就是它。

标签组默认是折叠的：你的页面是给你自己用的，平铺会把人的标签挤走。人手动
展开之后不会再被折回去（展开就是「我正在看」），组里含当前活动标签时也不折。

CDP 后端（`-b cdp`）的隔离规则完全一样，只有一处做不到：CDP 碰不到浏览器的
标签组界面，所以那边的 group 只是账本，标签不会在标签栏上并成一条。这也是
默认走扩展后端的又一个理由。

## 禁止

- 禁止 window.open() / raw CDP Target.createTarget 开 tab；开页只有 `--new`
- 禁止靠「换个 group 名」来绕开 5 个标签的上限——那是在标签栏上堆组
- 禁止 exec-js 手写 scrollBy / element.click() 替代专用命令
- 禁止截图当阅读工具
- 禁止凭记忆猜测 URL
- 用完不 `group-close` 不算禁止，但等 30 分钟自动清理是兜底不是流程

## 进一步阅读

`browser-usage` 只覆盖通用层。下列场景需要再拉对应 topic：

- 后端工作方式、profile 机制 → `frago book browser-backend-choice`
- 遇到 anti-bot / Cloudflare / captcha / 验证码 → `frago book browser-anti-bot`
- 启动浏览器、start 撞锁、以及为什么不要碰 `--browser` / `--port` / `--headless` → `frago book browser-startup`
- 需要真无头 / 独立实例（默认后端做不到的场景）→ `frago browser -b cdp`，判据见 `frago book browser-backend-choice`；NEVER 自起 chrome 进程
