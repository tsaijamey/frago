# browser-usage

frago browser 操作完整指南。所有浏览器操作通过 frago browser 命令执行，不直接调用 CDP 或浏览器 API。

唯一例外是把配方页面交给人看：那种页面用 `frago recipe open <url>` 开在用户的系统默认浏览器里，与本文讲的受控浏览器无关，agent 也控制不了它（见 `frago book interactive-recipe`）。除此之外，凡是 agent 自己要读、要点、要抓的页面，都走下面的命令。

## Group（前提）

每条 tab 操作命令 MUST 带 `--group` 参数指定 group 上下文，否则报错 `NO_GROUP`。

  frago browser navigate <url> --group <name>
  frago browser get-content --group <name> [selector]
  frago browser click --group <name> <selector>
  frago browser exec-js --group <name> <js>
  frago browser screenshot --group <name> <output_file>

recipe/run 环境中 `FRAGO_CURRENT_RUN` 环境变量作为 fallback，此时可省略 `--group`。

group 保证：同 group 内所有命令自动跟随同一 tab；不同 group 互不干扰；30 分钟不活跃自动清理。

下面这些命令不需要 `--group`（管理类，或自己就是全局操作）：

  start  stop  status  check  detect  wait  reset
  list-tabs  switch-tab  close-tab
  groups  group-info  group-close  group-cleanup

除此之外的每一条都必须有 group，缺了会报 `--group/-g required`。
`detect` 和 `wait` 两条可带可不带：`detect` 带上就从「列已装浏览器」变成「探测当前页反爬」，`wait` 带上才等在该 group 的页面上。

## Group 查询

  frago browser groups               # 列出所有 group
  frago browser groups --json        # JSON 格式
  frago browser group-info <name>    # group 详情
  frago browser group-close <name>   # 关闭 group
  frago browser group-cleanup        # 清掉 tab 已不存在的僵尸 group
  frago browser reset                # 关掉除落地页外的所有 tab（有 FRAGO_CURRENT_RUN 时只清本 group）

## 导航

  frago browser navigate <url> --group <name>

导航的是这个 group 当前跟着的那个标签。**要新开一个标签，就换一个 group 名**
——group 还没有绑定标签时，导航本身就会新建一个。一个 group 只记一个标签，
所以别指望在同一个 group 下攒出第二个标签。

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

## Tab 管理

  frago browser list-tabs                    # 查看所有 tab
  frago browser switch-tab <id>              # 切换 tab（自动更新 group 的跟随目标）
  frago browser close-tab <id>               # 关闭 tab

agent 开的页面一律收进浏览器里一个叫 **auto 的标签组**，默认折叠——这些页面是
给 agent 自己用的，平铺在标签栏上会把人自己的标签挤走。`list-tabs` 里的
`tab_group` / `tab_group_collapsed` 两个字段会告诉你页面归到哪儿、是否折着。

注意这跟 `--group` 是同名的两回事：`--group` 是 frago 的逻辑隔离账本，浏览器
里看不见；auto 是标签栏上那个能折叠的分组。所有 agent 页面进同一个 auto 分组，
不影响 `--group` 的隔离——两个并行 worker 的页面照旧各跟各的 tab。

人手动展开 auto 组之后，agent 不会再把它折回去；组里正显示着页面时也不折。

## 禁止

- 禁止 window.open() / raw CDP Target.createTarget 开 tab
- 禁止 exec-js 手写 scrollBy / element.click() 替代专用命令
- 禁止截图当阅读工具
- 禁止凭记忆猜测 URL

## 进一步阅读

`browser-usage` 只覆盖通用层。下列场景需要再拉对应 topic：

- 后端工作方式、profile 机制 → `frago book browser-backend-choice`
- 遇到 anti-bot / Cloudflare / captcha / 验证码 → `frago book browser-anti-bot`
- 启动浏览器、start 撞锁、以及为什么不要碰 `--browser` / `--port` / `--headless` → `frago book browser-startup`
- 需要真无头 / 独立实例（默认后端做不到的场景）→ `frago browser -b cdp`，判据见 `frago book browser-backend-choice`；NEVER 自起 chrome 进程
