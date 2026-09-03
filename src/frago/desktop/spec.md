# agent_os 规格

> 这份规格由 frago recipe plan 生成，`frago recipe create agent_os` 会读它。
> **下面几个字段是给机器读的，写什么，模板里就长出什么。**
> 想清楚再写：改代码容易，改一个已经被别人依赖的接口难。

## 机器读的部分

```yaml
type: workflow          # atomic（一件事）| workflow（串起几件事）
runtime: python

# 这个模块能做哪几件事。一个 mode 一件事，第一个是默认。
# up MUST 排第一：平台的守护服务发现桌面「该在却不在」时，调的是
# RecipeRunner().run("agent_os", {})，一个参数都不传
# （src/frago/server/services/virtual_os_lifecycle.py:138）。
# 换个 mode 排到第一位，守护每 15 秒去拉的就是别的东西，而它照样报成功。
modes:
  - up
  - status

# 别的模块能调哪几个 mode。MUST 是只读的：
# 不触网、不重算、不改状态、不开浏览器——别人每 5 分钟问一次也不会出事。
# up 起进程、开浏览器、改注册表，它在干活，所以不导出。
exports:
  - status

# 用了谁的哪个口。写下来，对方才知道自己正在被谁读。
# 页面**资产版本号**从这里要。旧版是自己 stat 对方的目录、数所有文件的 mtime——
# 于是对方不知道自己正在被读，改自己的文件时看不到任何提示。
imports: {agent_os_ui: [status]}

# 要一张页面：桌面舞台那块画面就是它。
# 但页面**文件**不在本模块手里——recipe.md 里写 `ui_from: agent_os_ui`，
# 服务端直接从对方目录发（src/frago/server/routes/app_pages.py:106）。
# 所以 create 生成的空 assets/ 骨架 MUST 删掉：留着它，下一个人会以为页面在这儿改。
page: true
```

## 人读的部分

### 它解决什么问题

**谁**：要录教学与演示视频的人，以及替他干活的 agent（主要是 `video_pipeline_studio`）。
**什么时候**：要拍一段「在电脑上做某件事」的画面，而真拍屏幕会拍进私人窗口、
通知气泡、乱七八糟的标签页，而且不可重来。

本模块是一块**虚拟 macOS 桌面舞台**：把一个真实 tmux 会话和一个真实浏览器标签页
重构成一块可脚本操控的桌面画面，全屏打开后被录屏。终端里跑的是真命令，浏览器里
开的是真网页，桌面、窗口、鼠标、字幕都是画出来的，所以每一帧都可复现、可重来。

```
agent_os/                本模块
├── recipe.py            入口——这轮改造只动这一层
├── broker.py            采集与操控：tmux 抓帧、CDP 截帧、WebSocket 服务端、录制
├── health.py            启动自检：八项「会静默出错」的检查
├── registry.py          实例注册表：身份层与运行态层分开
└── aos                  命令行小工具（frago desktop 转发到它）
```

原先这儿还有一个 `video/`（shotstat 节奏测量、cases 浮层模板、playbook、
FRAMEWORK/FINDINGS）。**2026-08-27 已搬去 `video_pipeline_studio` 自己的目录**：
那是视频制作的手艺，不是舞台的机件，本模块从来一次都没引用过它，
而 `video_pipeline_studio` 一直在按绝对路径伸手进来拿。搬走之后那只手消失。
本模块**不提供视频制作的任何手艺与模板**，别再往这儿加。

`broker.py` / `health.py` / `registry.py` 是本模块自己的内部实现，
**原样保留、不动、不拆**。它们不是三个配方，是一个模块的三个文件——
跨模块只走接口那条规矩管的是**模块之间**，不是一个模块内部的文件之间。

**硬约束：平台按绝对路径要本模块的两个文件，它们 MUST 留在原位。**
这不是风格问题，是外面已经有两根硬连线钉在这个目录上：

| 谁 | 按绝对路径要什么 | 挪了会怎样 |
|---|---|---|
| `frago desktop` 命令（`src/frago/cli/desktop_commands.py:40`，`RECIPE_NAME = "agent_os"`） | 本模块目录下的 `aos` 脚本 | 命令**当场失效**——它在 `:80` 先查文件在不在，不在就报「本机没有虚拟桌面配方」并把期望路径打出来 |
| 服务端的舞台保活服务（`src/frago/server/services/virtual_os_lifecycle.py:50`） | 本模块目录下的 `registry.py`，`importlib` 按路径加载 | 守护**静默地**退回「从来没建过实例」那条路——一句日志都没有 |

`registry.py` 被按路径 import 而不是抄一份，是因为「在不在跑」的判据（pid 活着**且**
端口应答）住在配方里，抄到服务端必然漂移。

所以这轮改造**只动入口 `recipe.py` 那一层**：`aos` / `broker.py` / `health.py` /
`registry.py` **不改名、不挪窝、不拆**。（`aos` 内部有一处非改不可，见「配套改动」——
改的是它 `cmd_up` 里怎么调配方，文件本身仍在原路径、原文件名。）

### 每个 mode 做什么

| mode | 输入 | 输出 | 只读？ |
|---|---|---|---|
| `up`（默认） | 见下表，全部可选 | `url` / `control` / `content_id` / `tmux_session` / `instance` / `runtime` / `health` … | **否**——起进程、开浏览器、写注册表，所以不导出 |
| `status` | — | `instance` / `runtime` / `broker` / `health` | 是——只探一次本机 broker 的 `/status`，不起任何进程 |

#### up

把舞台拉起来。旧版整支脚本干的就是这一件事，**顺序与判据逐字保留**：

**1. 先查本机有没有 tmux。**没有就致命，一个字节都不往下走。
MUST 在任何别的事情之前：后面每一步都会留下痕迹（发布页面状态、建实例记录、
起进程、开标签页），在一台没有终端的机器上一路铺到最后再失败，留下的是一台半成品
舞台——而下一次 `up` 会把那半成品当现成的复用。

**2. 合并配置。**

| 参数 | 默认 | 说明 |
|---|---|---|
| `id` | `default` | **只认 `default`**，传别的直接拒绝 |
| `port` | `8770` | broker 的 HTTP / WebSocket 端口 |
| `stage_port` | `9222` | 演员浏览器的 CDP 端口 |
| `record_port` | `9223` | 录制机位的 CDP 端口 |
| `tmux_session` | `frago-stage` | 舞台终端那个会话的名字 |
| `desktop_width` / `desktop_height` | `1920` / `1080` | 桌面画面尺寸 |
| `browser_width` / `browser_height` | `1280` / `800` | 虚拟浏览器窗口占位 |
| `term_cols` / `term_rows` | `120` / `32` | 终端字符网格 |
| `start_url` | `about:blank` | 演员标签开机停在哪 |
| `fps` | `30` | 录制帧率 |
| `actor_mode` | `headless` | `headless` \| `head`，别的值直接拒绝 |
| `open` | 不传 | `true` 一定开新标签；`false` 一定不开；不传才走探测（见第 6 步） |

`id` 只认 `default`：这台电脑上虚拟桌面只有一个。早先可以传 id 开多个，代价是每条
指令都要先回答「打给哪一台」，**而打错了回执照样一切正常**。收成唯一之后这个问题
不存在。

`actor_mode` 只有两档。默认无头——舞台存在的理由就是不占人的屏幕。传 `head` 的只有
一种情形：**演员要演的内容需要 GPU**（无头带着 `--disable-gpu` 起，WebGL 拿不到，
三维场景在里面不是渲得慢是根本渲不出来，而且没有任何一层会报错）。代价说在前面：
有头就是一扇真窗口开在人的屏幕上，还会抢一次焦点。中间那档「把窗口挪到屏幕外」
2026-08-23 撤掉了——macOS 只认进程开的第一扇窗，之后新建的窗口照样落在屏幕上，
它从来没兑现过「看不见」，只是让人以为兑现了。

`clips_dir` **不是参数**，由平台交代的落点算出来（`self.store.path("clips")`）。

**3. 发布桌面页要显示的状态。**五项，一项不多：

```
brokerWs    ws://127.0.0.1:<port>/stream
desktop     {w, h}
uiVersion   ← 问 agent_os_ui 要（见下）
contentId   registry.content_id_for(id)
instanceId  id
```

**`uiVersion` 改由 `self.ask("agent_os_ui", "status")` 要，字段名是 `asset_version`。**
口径不变——仍是那个目录里**全部常规文件 mtime 的最大值**——只是改由对方自己算、
自己给。旧版是自己伸手进 `~/.frago/recipes/atomic/system/agent_os_ui/assets/` 数
mtime，于是对方不知道自己正在被读：改自己的文件时看不到任何提示说别处依赖着这个
目录，断裂不在改动那一刻暴露，只在有人点开桌面页那一刻暴露，而那时看到的是
「画面被拉伸变形」，跟改了哪个文件毫无关系。

这个数字本身没有意义，唯一的要求是**资产变了它就变**：桌面页每次上报 layout 都带着
它，broker 拿它做**相等**比对，对不上就整条丢弃并叫那个标签自己刷新。没有它的话，
一个开着旧 JS 的标签页照样能把自己那套几何报给 broker，和新标签轮流覆盖。

`contentId` 与 `instanceId` **两个都写，缺一不可**：前者是荧幕归属的依据，broker 拿它
比对；后者是人和日志读得懂的名字。端口不属于身份（所有实例默认都是 8770），旧实例
遗留的标签每秒重连一次，连上后来的 broker 是必然事件；它一上报 layout 就会把自己那块
荧幕的窗口几何按在新舞台上——症状是网页只占窗口左上角一小块，而日志一切正常。

`slot` 的算法保留：`content_id` 等于默认值（`bc98c2f8114b`）时用 `"default"`，
否则用 `content_id` 本身。

publish **只发渲染状态，NEVER 发路径**。上面五项都不是路径。基类会当场拦下带路径的
状态（`frago_recipe.py:627`），拦的理由不是洁癖：访客机器上没那个文件，能读任意路径
的接口对访客一律关死，而落点一挪页面还在读老地方、每次刷新都显示成功。

**4. 算出桌面页地址。**算式只有 `health.expected_desktop_url(content_id)` 一处，
**NEVER 两边各写一遍**。两边各写必然漂移，而漂移的表现要么是自检天天误报「URL 变了」，
要么是真变了却报不出来。

MUST 注意：`self.publish()` 会返回一个地址，**那个返回值不参与地址计算**。
平台的 `page_url()` 给的是 `http://localhost:8093/app/agent_os`
（`src/frago/recipes/app_state.py:336`），算式给的是 `http://127.0.0.1:8093/app/agent_os`
（`health.py:53`）——同一张页面，两个字符串。拿返回值去登记身份，自检的 `desktop_url`
那一项从此每次都报「桌面页地址变了」，而世界什么都没变。

**5. 登记实例身份，拉起 broker。**

身份走 `registry.ensure_identity`：**已存在就原样返回，不重算、不覆盖**——身份的全部
价值就在于它不变。人浏览器里那个标签页的门牌号不能因为换了个 broker 端口就换。

拉 broker 前先探端口：**端口上已经活着就复用，NEVER 再起一个。**两个 broker 抢同一个
tmux 会话会互相 kill，画面会莫名其妙清空；而且后起的那个绑不上端口、当场收尾，
它的收尾会把**活着的那个**注销成 stopped，之后每条指令都被「实例存在但没在运行」
挡掉，而画面其实好端端地在推。

真要起的时候：`uv run broker.py '<cfg-json>'`，`start_new_session=True`，
stdout / stderr 追加进 `broker.log`。两条不能省的交代——

- **cwd MUST 是配方自己的目录**：broker 要 import 同目录的 `registry`。
- **环境 MUST 原样传下去**：`registry` 自己读 `FRAGO_RECIPE_DATA_DIR` 定台账落点
  （`registry.py:44`），拿不到就在 import 那一刻抛。

等最多 **90 秒**，每秒探一次端口，中间用 `self.progress` 报进度；到点还没就绪就致命，
错误信息里带上 `broker.log` 的位置。

**6. 开不开桌面页。**显式传 `open` 的照旧优先：人说不开就不开，人说要开就一定开一个
新的。不传（默认）时才走探测——先探 **2.5 秒**，看**本实例**有没有主荧幕已经连着，
有就复用、不开新标签。

必须等那 2.5 秒：broker 刚起来时客户端必然是 0，人那个标签每秒重连一次，大约 1 秒后
才回来。不等就会每次 `up` 都判成「没人开着」，于是又开一个——标签越攒越多，
而这正是这条探测要治的病。

必须核对 `content_id`：端口不属于身份，探到的很可能是**别的实例**的 broker。
只看 `primary` 的话，别人那块荧幕会让这次 `up` 判成「已经有人开着」，于是自己的桌面页
一个也不开——回执还写着 `screen_reused: true`，看上去一切正常，人却对着空白等画面。

开页面走 `self.open_page(url)`：它走系统默认浏览器（`frago/viewer/browser.py:122`），
是「把配方页面给人看」的唯一入口。**NEVER 用 `frago browser navigate`**——那会把页面
塞进 agent 正在驱动的那个 CDP 浏览器，既占着 agent 的浏览器，又让录制依赖那个浏览器
活着。开不开得成不致命：`open_page` 开不成返回 False，记进回执、`self.warn` 一句。

**7. 最后跑一次启动自检。**`health.report(instance, status=<broker /status>)`。

**自检恒不抛异常，它是诊断不是门禁。**任何一项自己查不了（目录不可读、注册表损坏、
broker 不可达）都不得影响启动，该项如实标 `unavailable`，配方照常返回成功。
诊断工具把被诊断对象搞挂是荒谬的。

broker `/status` 只取一次，不轮询等 `ui_ready`。唯一的例外是「客户端数为 0」时多等
**1.5 秒**、一有客户端立刻走：刚重启的 broker 必然一个客户端都没有，不等就会在每次重启
时报一条「没有桌面页连着」，而它一秒后自行消失——这种狼来了的告警报几次就没人看了。

up 的回执字段与旧版逐字一致：`success` / `id` / `url` / `instance` / `runtime` /
`control` / `status` / `content_id` / `tmux_session` / `browser_opened` /
`screen_reused` / `health` / `hint`。`success` 与信封的 `ok` 重复，**故意保留**：
现有调用方读的是它。

#### status

舞台现在什么状态。**只读**：不起任何进程、不开浏览器、不改任何状态。

| 字段 | 内容 |
|---|---|
| `instance` | 身份层：`id` / `content_id` / `desktop_url` / `clips_dir` / `tmux_session` / `created_at` |
| `runtime` | 运行态：`pid` / `port` / `status` / `started_at` / `heartbeat_at` |
| `control` | 指令打到哪：`http://127.0.0.1:<port>/control` |
| `broker` | `reachable` + 采集 / 客户端 / 几何上报：`clients`（带身份的名单）/ `clients_count` / `layout_reported` / `ui_ready` / `frame_age_sec` / `actor_viewport` / `focus` / `windows_open` / `recording` / `cdp_ports` / `pid` |
| `health` | 启动自检那份报告，与 up 用的是同一份实现 |

**探不到就如实说不可达，NEVER 当成正常。**`reachable: false` 时其余字段一律 `null`，
**NEVER 拿 `0` 或 `false` 顶上去**——「没有客户端连着」和「问不到」是两件事，
补救动作也不同（一个去开标签页，一个去看 broker 死没死），混成一个数就等于拿一个
编出来的 0 去骗自检。

导出给别的模块，凭什么算只读：它只做三件事——读本模块自己的注册表文件、
向 `127.0.0.1` 上自己那个 broker 的 `/status` 发一次 GET、跑一遍自检
（自检会 `tmux capture-pane` 一次、`scandir` 两个目录）。不触网、不重算、不改状态、
不开浏览器，别人每 5 分钟问一次也不会出事。

**唯一一处可能落笔的地方，写在明面上**：`registry.read_instance` 读到一条写着
`running` 的记录时会现场探活（pid 还在**且**端口应答），不成立就把 `status` 就地纠正为
`stopped` 落盘。这不是新增状态，是把一句已经不成立的话改成真话；幂等，纠正一次之后
不再写。不走它的话得在这儿抄一份「怎么算在跑」的判据，两份判据必然漂移——
而这正是平台的守护服务宁可按路径 import 这个文件也不肯抄的那份判据。

### 它不做什么

- **不做剪辑、不合成、不管分镜与闸门、不判片子好不好。**录视频那一整套工艺、
  故障处方与开录闸门在 `video_pipeline_studio` 手里。本模块只提供舞台：
  它答得出「画面是不是活的」，答不出「这条片子能不能用」。
- **不提供视频制作的任何手艺与模板。**shotstat 节奏测量、cases 浮层模板、playbook、
  FRAMEWORK / FINDINGS——这些原先躺在本模块的 `video/` 里，**2026-08-27 已搬进
  `video_pipeline_studio` 自己的目录**。判据很干脆：只有 `video_pipeline_studio` 用它们，
  `agent_os` 自己一次都没引用过。**别再往这儿加**——手艺放在舞台里，等于让每个只想
  拉起一块画面的人都背上一整套剪辑口径，而改手艺的人还以为自己在改舞台。
- **不持有页面文件。**`index.html` / `style.css` / `app.js` / `ansi.js` 四个文件在
  `agent_os_ui` 手里，服务端靠 `ui_from: agent_os_ui` 直接从对方目录发。
  本模块的目录下**不该有 assets/**——`ui_from` 借的是整个目录，这儿留一个空骨架，
  下一个人会以为页面在这儿改。
- **不再伸手进 `agent_os_ui` 的目录。**版本号走总线问它要。`imports` 里写着
  `agent_os_ui: [status]` 不是备注，是总线放行的依据：没声明的调用会被当场拒掉，
  而且**拒掉这件事本身会被记下来**（`~/.frago/bus-edges.jsonl`）。
- **不开第二台舞台。**`id` 只认 `default`。
- **不停舞台、不发指令、不录制。**`down` / `rec` / `term` / `browser` / `camera`
  这些动词在 `aos` 那支小工具里（`frago desktop` 转发到它），指令直接 POST 到
  broker 的 `/control`。本模块两个 mode 只管「拉起来」和「现在什么样」。
- **不给页面调 `status`。**页面调导出 mode 走的是另一道门，那道门**拒收任何带本机
  路径的返回值**（`app_pages.py:329`，整条调用作废，不是过滤掉那个字段）。而
  `instance.clips_dir` 和自检报告里的 `how_to_fix`（「删除 …/profiles/edge/9999」）
  正是路径。本模块的页面不需要它——它靠 `brokerWs` 拿画面、靠 `config.json` 拿那五项
  渲染状态。**下一个人 MUST 知道**：想让页面调 `status`，得先把路径从自检报告里摘
  干净，而那些路径正是自检有用的地方。
- **不自己拼数据路径、不兜底。**平台没交代落点时基类抛 `NoLandingSpot`，
  配方不接不兜底。

### 这轮改造与旧版不同的地方

只有三处，其余逐字保留。

**一、`uiVersion` 走总线问 `agent_os_ui` 要**，不再自己数对方目录里的 mtime。
理由见上。口径（全部文件 mtime 的最大值）一个字没改。
连带的：旧版那条「UI 资产缺失」的致命检查删掉——资产在不在由对方自己答。

**二、新增 `status` mode 并导出。**旧版没有 mode 这回事，整支脚本只干 `up`；
「现在什么样」得跑 `aos status`，而那是命令行，别的模块调不到，页面也调不到。

**三、自检拿到的 `clips_dir` 用本次运行的落点，不用注册表里那条。**
这一处是**判据上的改动，单独拎出来说**：

`registry.ensure_identity` 对已存在的记录一个字段都不重算（身份的价值就在于它不变），
所以这台机器上那条 2026-07-22 建的记录里，`clips_dir` 至今写着
`~/.frago/data/agent_os/clips`——一个**已经不存在**的目录；而 broker 实际把片子写在
平台交代的落点下，此刻那里躺着 110 个文件 / 29MB。自检的 `clips` 那一项读的是注册表
那条，于是它在查一个空气目录，报「尚未创建（还没录过）」并标 **ok**。
一句错话，而且是自检最不该说的那种错话。

所以 `health.report` 收到的记录里，`clips_dir` 换成本次运行算出来的那条
（`self.store.path("clips")`），其余字段原样。**注册表文件不动**——身份层永不重算是
`registry` 的设计，不在这一层推翻。

### 配套改动（不在本模块里，但不改它当场断）

`aos` 那支小工具的 `cmd_up` 是这么调配方的（`aos:600-618`）：
`uv run recipe.py '<params>'`，取 stdout **最后一行 JSON**，判 `payload["success"]`。

新工艺下这三件事全变了，**MUST 一起改，否则 `frago desktop up` 当场断**：

1. **最后一行是信封**：`{"t":"result","ok":true,"data":{…}}`，`success` 在 `data` 里。
   照旧读 `payload["success"]` 会取到空，于是抛「失败」——**而舞台其实已经起来了**。
   回执说失败而世界是成功的，是最坏的一种错。
2. **`frago desktop` 只交代了落点，没交代总线**（`desktop_commands.py:104-115`），
   也没有把基类放上 `PYTHONPATH`——那两件是 `frago recipe run` 干的
   （`runner.py:485-499`）。直接 `uv run recipe.py` 的话，新配方连 `import frago_recipe`
   都过不去。
3. 所以 `cmd_up` 改成走 `frago recipe run agent_os --params '<params>'`，
   拆信封读 `ok` 与 `data`。一条路：平台起配方，落点、总线、身份都由平台交代。

`aos` 的其余动词不受影响：它们直接 POST 到 broker 的 `/control`，不经过 recipe.py。

### 数据

都落平台交代的落点（`self.store` / `self.data_dir`），**NEVER 自己拼路径**。
老落点 `~/.frago/data/agent-os/` 是个主体容器，里面还住着人归档的交付物和另一个配方的
视频项目，运行状态混在那儿谁也说不清哪份归谁。

| 落什么 | 落哪 | 谁写 |
|---|---|---|
| 录屏片段 `<name>.mp4` / `<name>.jsonl` | `<落点>/clips/` | broker（路径由 `up` 经 cfg 交代给它） |
| broker 日志 | `<落点>/broker.log` | broker 的 stdout / stderr，`up` 起进程时接过去 |
| 实例台账 | `<落点>/<id>.json` | `registry`，它自己读 `FRAGO_RECIPE_DATA_DIR` |

要别的模块的数据就走 `imports` 声明 + `self.ask`，**NEVER 读对方的文件**。
本模块只问 `agent_os_ui` 要一样东西：`status` 里的 `asset_version`。

### 出错怎么办

分界线只有一条：**舞台还立不立得住。**

| 情况 | 怎么报 | 数据 |
|---|---|---|
| 平台没交代落点 | 基类抛 `NoLandingSpot`，**配方不接不兜底** | 不动 |
| 总线不可达（服务端没起、不是走 `frago recipe run` 起的） | 基类抛 `BusUnavailable`，**不兜底**——退回自己去读对方目录，等于在最坏的时刻把这轮要修的病装回去 | 不动 |
| 本机没有 tmux | **致命**，且 MUST 在第一步就报 | 不动 |
| 传了 `default` 之外的 `id` | **致命** | 不动 |
| `actor_mode` 不是 `headless` / `head` | **致命**，错误信息里列出认识的两档 | 不动 |
| 问 `agent_os_ui` 要版本号失败（它没装、答不出） | **致命**。发一个没有版本号的页面状态出去，等于把每个标签都标成旧的，broker 会把它们的几何整条丢弃——画面变形，而没有一处报错 | 不动 |
| 发布桌面页状态失败（总线返回非 200） | **致命** | 不动 |
| broker 90 秒内没就绪 | **致命**，错误信息里带上 `broker.log` 的位置 | 已起的进程留在原地，不去猜着 kill |
| 桌面页还没连上来 | **不致命** `self.warn`。自检那条 WARN 自带 `means` / `if_ignored` / `how_to_fix` 三段 | 不动 |
| 桌面页没开成（系统里没有可用浏览器） | **不致命** `self.warn`，回执里 `browser_opened: false`，人拿 `url` 自己开 | 不动 |
| 自检的某一项查不了 | **不致命**，该项标 `unavailable`，**NEVER 当 pass** | 不动 |
| `status` 时 broker 不可达 | **不致命**，`reachable: false`，退出码 0 | 不动 |

`up` 拉 broker 要等最多 90 秒，中间用 `self.progress` 报进度——不报的话，
一个要等一分半的启动和一个卡死的启动在调用方眼里长得一模一样。

### 怎么验

下面每条都写清依据的是上面哪条规则。**期望值不是拍脑袋写的**：凡是现在就问得到的
真值，我当场问过——`agent_os_ui` 报的版本号、8770 上那台旧 broker 的 `/status`、
注册表记录的内容、`content_id` 的哈希、以及总线 `page_url()` 与 `expected_desktop_url()`
给出的两个不同 URL。

**配方本身还没生成**，所以 `frago recipe run agent_os …` 这些条要等
`frago recipe create agent_os` 之后才跑得起来。**create 之后 MUST 从第 1 条跑到第 15 条。**

第 13、14、15 三条不依赖配方生成，**现在就能跑，而且现在就是绿的——我跑过**。
它们守的是改造前后都不许变的东西：两条硬约束，加上「发给页面的状态里没有本机路径」。
旧配方在这三条上本来就是对的，所以它们红了只有一个意思：这轮改造把原本好的东西弄坏了。

现在红的有两条，性质完全不同，**NEVER 混为一谈**：

- **第 6 条红是「本来就该红」**：页面上挂的 `uiVersion` 是旧配方自己数 mtime 数出来的
  `1787549479`，而 `agent_os_ui` 此刻报 `1787833318`（两个数我都当场问过）。
  **这两个数不相等，正是这轮要修的病**——改造完跑一次 `up` 之后它必须相等。
- **第 11 条红是「刚被弄坏的」**：`frago recipe create` 生成的骨架没写 `ui_from`，
  又铺了个空 `assets/`，桌面页此刻发的是那份空骨架。这条**不是改造的目标，是改造的副作用**，
  而且它此刻就在生效——细节见第 11 条本身。

先约定：

```bash
RUN() { frago recipe run agent_os --params "$1" 2>/dev/null; }
UI=~/.frago/recipes/atomic/system/agent_os_ui/assets
```

`frago recipe run` 把 `data` 打在 stdout、`[recipe] …` 打在 stderr，所以一律
`2>/dev/null | jq`。**要退出码就先把输出接住**——管道里的 `$?` 是 `jq` 的，不是配方的。

#### 1. 舞台没起的时候，status 也跑得完，且如实说不可达

```bash
frago desktop down                      # 或确认 8770 上没人监听
out=$(RUN '{"mode":"status"}'); echo "exit=$?"        # 期望 0
printf '%s\n' "$out" | jq -e '
  .broker.reachable == false and
  ([.health.checks[] | select(.item=="ui_ready" or .item=="screen_ownership"
      or .item=="screen_duplicates") | .level] | unique == ["unavailable"])'
```
依据：「`status` 探不到就如实说不可达，NEVER 当成正常」+「自检的某一项查不了就标
`unavailable`，NEVER 当 pass」。这三项的真值全在 broker 手里，broker 不可达时
`health.py` 走的正是 `_unavailable` 那条路（`health.py:270`、`311`、`396`）。
`ui_ready` 等三项 MUST 不是 `ok`——标成 ok 就是拿「问不到」冒充「没问题」。

#### 2. up 跑完，回执四项都在，而且值是算得出来的

```bash
RUN '{"mode":"up"}' | jq -e '
  .url == "http://127.0.0.1:8093/app/agent_os" and
  .control == "http://127.0.0.1:8770/control" and
  .content_id == "bc98c2f8114b" and
  .tmux_session == "frago-stage"'
```
依据：`content_id = sha256("agent_os:default")[:12]`（`registry.content_id_for`）
= `bc98c2f8114b`，**这个数我算过**，正好等于 `health.DEFAULT_CONTENT_ID`，
所以 `expected_desktop_url` 走的是「默认实例返回光秃秃的 base」那条分支，地址不带
`?key=`。`control` 由默认端口 8770 拼出。`tmux_session` 走 id=default 的默认值。

**MUST 是 `127.0.0.1` 不是 `localhost`。**总线 `publish()` 返回的是
`http://localhost:8093/app/agent_os`——同一张页面、两个字符串。这条断言就是在守
「地址只有 `health.expected_desktop_url` 一处算式」：哪天有人图省事拿 publish 的返回值
去登记，这条会立刻红，而症状本来会是自检天天报「桌面页地址变了」。

#### 3. 再跑 status，broker 可达，客户端与几何报得出来

```bash
RUN '{"mode":"status"}' | jq -e '
  .broker.reachable == true and
  (.broker.clients_count | type) == "number" and
  (.broker.layout_reported | type) == "boolean" and
  (.broker.clients | type) == "array"'
```
依据：「`status` 报 broker 报的采集 / 客户端 / 几何上报」。

**期望 MUST 是「是个数」，NEVER 写成 `> 0`。**刚起来的 broker 客户端必然是 0——
人那个标签每秒重连一次，大约 1 秒后才回来。写成 `> 0` 的验收单会在一个完全正确的
系统上红。（实测此刻 `clients_count` 就是 0。）

#### 4. 连跑两次不会起出第二个 broker

```bash
RUN '{"mode":"up"}' > /dev/null
p1=$(curl -s http://127.0.0.1:8770/status | jq -r .pid)
RUN '{"mode":"up"}' > /dev/null
p2=$(curl -s http://127.0.0.1:8770/status | jq -r .pid)
[ "$p1" = "$p2" ] && echo "同一个 broker: $p1"
[ "$(lsof -nP -iTCP:8770 -sTCP:LISTEN | tail -n +2 | wc -l | tr -d ' ')" = "1" ] && echo OK
```
依据：「端口上已经活着就复用，NEVER 再起一个——两个 broker 抢同一个 tmux 会话会互相
kill」。

**NEVER 用 `pgrep -f broker.py` 数。**`uv run broker.py` 是**两个**进程（uv 的壳
+ 它起的 python），期望值是 2 不是 1；而且 `pgrep -f` 还会匹配到你自己这条命令行。
实测过：`pgrep` 数出 2，`lsof` 数出 1，后者才是「有几个 broker 占着这个端口」。

#### 5. 已经有荧幕连着时，不会多开一个桌面页标签

**先看前置条件成不成立**——不成立这条验不了：

```bash
curl -s http://127.0.0.1:8770/status | jq '[.clients[] | select(.primary)] | length'
```
得是 `1`。是 `0` 就先在浏览器里打开一次 `http://127.0.0.1:8093/app/agent_os`，
等一两秒再看。

```bash
RUN '{"mode":"up"}' | jq -e '.screen_reused == true and .browser_opened == false'
```
依据：「不传 `open` 时先探 2.5 秒看**本实例**有没有主荧幕已经连着，有就复用不开新标签」。

**没有荧幕连着的时候，第二次跑照样开一个标签，那是对的。**判据是「本实例已经有主荧幕
连着」，不是「跑过第二次」。此刻这台机器 `clients_count` 是 0，直接跑这一条会得到
`screen_reused: false`——**配方没错，是前置条件没造出来**。

顺带验显式那两档：

```bash
RUN '{"mode":"up","open":false}' | jq -e '.browser_opened == false and .screen_reused == false'
```
依据：「显式传 `open` 的照旧优先」——人说不开就不开，连探测都不走，所以
`screen_reused` 也是 false（它只在探测那条路上才为真）。

#### 6. 页面拿到的 uiVersion 与 agent_os_ui 报的是同一个数

```bash
want=$(frago recipe run agent_os_ui --params '{"mode":"status"}' 2>/dev/null | jq -r '.asset_version')
got=$(curl -s http://127.0.0.1:8093/app/agent_os/config.json | jq -r '.uiVersion')
[ "$want" = "$got" ] && echo "OK $got"
```
依据：「版本号改由对方自己算、自己给」+「publish 发的五项里有 `uiVersion`」。
`config.json` 就是页面真正读到的那份状态（`app_pages.py:183`）。

**两边字段名不一样**：`agent_os_ui` 那头叫 `asset_version`，发到页面上叫 `uiVersion`。
照着 `.ui_version` 去 jq 会取到 `null`，看起来像配方没发版本号，实际是验收单问错了字段。
（我实测过 `agent_os_ui` 的返回，字段名确实是 `asset_version`。）

**期望值 MUST 现算，NEVER 写死。**此刻 `agent_os_ui` 报 `1787833318`，而页面上挂着的
还是 `1787549479`——旧配方最后一次 `up` 时自己数 mtime 数出来的，数的还是老目录里那份
文件。**这两个数不相等，正是这轮要修的病**；改造完跑一次 `up` 之后它们必须相等。

#### 7. 边界：只有一台舞台

```bash
RUN '{"mode":"up","id":"stage2"}' > /dev/null; echo "exit=$?"     # 期望非 0
```
依据：致命清单「传了 `default` 之外的 `id`」。

#### 8. 边界：actor_mode 只有两档

```bash
RUN '{"mode":"up","actor_mode":"offscreen"}' > /dev/null; echo "exit=$?"   # 期望非 0
```
依据：致命清单「`actor_mode` 不认识」。挑 `offscreen` 是因为它是 2026-08-23 撤掉的那一
档——撤掉的东西 MUST 报错，**NEVER 悄悄当成默认值处理**：那样人以为窗口挪到屏幕外了，
而它就开在屏幕正中间。

#### 9. 边界：status 真的只读

```bash
before_listen=$(lsof -nP -iTCP:8770 -sTCP:LISTEN | tail -n +2 | wc -l | tr -d ' ')
before=$(RUN '{"mode":"status"}' | jq -c '{s:.runtime.status, p:.runtime.pid, d:.instance.id}')
RUN '{"mode":"status"}' > /dev/null
after=$(RUN '{"mode":"status"}' | jq -c '{s:.runtime.status, p:.runtime.pid, d:.instance.id}')
[ "$before" = "$after" ] && echo "状态没动"
[ "$before_listen" = "$(lsof -nP -iTCP:8770 -sTCP:LISTEN | tail -n +2 | wc -l | tr -d ' ')" ] && echo "没起新进程"
```
依据：「`status` 只读：不起任何进程、不开浏览器、不改任何状态」+ `registry.read_instance`
唯一那处落笔（把已经不成立的 `running` 纠正成 `stopped`）——舞台正在跑的时候这条纠正
不会触发，所以三个字段 MUST 一模一样。

**NEVER 拿整个 `<id>.json` 的 mtime 或全文来比。**`heartbeat_at` 是 **broker** 每秒写的
（`registry.touch_heartbeat`），不是 `status` 写的；比全文必红，而红的原因跟 `status`
没有半点关系。实测两次 `cat` 之间它就从 `20:30:26` 走到了 `20:30:36`。

#### 10. 边界：up 没被导出

```bash
grep -n "exports" ~/.frago/recipes/workflows/agent_os/recipe.py
```
期望：`exports = ("status",)`，里面没有 `up`。
依据：「exports MUST 只读」+「`up` 起进程、开浏览器、改状态，所以不导出」。

这是**静态声明检查**，说清为什么：总线放行照的是这个元组（`bus.py:264`），
而 `frago recipe run` 是自己跑自己、不过总线，跑一条命令验不出「别人调不到」。
要动态验，得让另一个模块 `self.ask("agent_os", "up")` 去撞 403。

#### 11. 边界：页面文件不在本模块手里

```bash
ls ~/.frago/recipes/workflows/agent_os/assets 2>&1        # 期望：No such file or directory
grep -n "ui_from" ~/.frago/recipes/workflows/agent_os/recipe.md   # 期望：ui_from: agent_os_ui
cmp <(curl -s http://127.0.0.1:8093/app/agent_os/index.html) $UI/index.html && echo "逐字节相同"
```
依据：「页面**文件**仍由服务端从 `agent_os_ui` 的目录发，靠 `ui_from` 这一句」+
「本模块目录下不该有 assets/」。服务端解析 `ui_from` 的地方在 `app_pages.py:106`：
声明了就一律去对方目录取，这儿留个空 assets/ 不会报错，只会骗到下一个改页面的人。

**这条现在是红的，而且是最该先修的一条——我刚跑过。**`frago recipe create agent_os`
（20:39 跑完的那次）干了两件事：生成的 `recipe.md` 里**没有 `ui_from`**，同时在本模块
目录下铺了一个空 `assets/`（`index.html` 282 字节 / `app.css` 324 / `app.js` 2143）。
两件事凑一起的后果不是「多了个没用的目录」——我 `cmp` 过服务端此刻发的
`/app/agent_os/index.html`，它**逐字节等于本模块那份空骨架**，不是 `agent_os_ui` 那份
8986 字节的真页面。**桌面页此刻就是坏的。**

而它坏得一声不吭：页面照常返回 200，`frago desktop status` 照常报 ok，broker 照常推画面，
只有打开页面的人看见一片空白。所以实现时这两步 MUST 一起做，缺一条都补不回来：
删掉 `assets/`，在 `recipe.md` 的 frontmatter 里补上 `ui_from: agent_os_ui`。

#### 12. 默认 mode 是 up

```bash
frago recipe run agent_os 2>/dev/null | jq -e '.url and .tmux_session'
```
依据：`modes` 第一个是默认 + 平台守护调的是 `RecipeRunner().run("agent_os", {})`，
一个参数都不传（`virtual_os_lifecycle.py:138`）。`up` 不排第一，守护每 15 秒去拉的就是
别的东西——而它照样报成功，桌面照样不回来。

#### 13. 边界：改造之后 `frago desktop` 仍然找得到舞台

```bash
test -x ~/.frago/recipes/workflows/agent_os/aos      && echo "aos 在原位"
test -f ~/.frago/recipes/workflows/agent_os/registry.py && echo "registry.py 在原位"
frago desktop status; echo "exit=$?"                 # 期望 0
```
期望 `frago desktop status` 报出实例身份，**NEVER** 报「本机没有虚拟桌面配方」。
依据：硬约束一——`desktop_commands.py:40` 按绝对路径要 `aos`，`:80` 先查在不在，
不在就直接报缺配方。

**这条验的是路径，不是新配方。**`aos status` 走 `cmd_status`（`aos:545`），
读注册表 + 探 broker，**一次都不碰 `recipe.py`**（`RECIPE` 在整个 `aos` 里只被
`cmd_up` 用一处，`aos:601`）。所以它跑通**不能**推出「配套改动做完了」——
`frago desktop up` 得单独验，那条走的是 `cmd_up` 那条路。

#### 14. 边界：视频手艺不在本模块

```bash
ls ~/.frago/recipes/workflows/agent_os/video 2>&1     # 期望：No such file or directory
ls ~/.frago/recipes/workflows/video_pipeline_studio/video >/dev/null && echo "在对家手里"
grep -rn "video/" ~/.frago/recipes/workflows/agent_os/*.py | wc -l   # 期望 0
```
依据：硬约束二 +「不提供视频制作的任何手艺与模板」。第三条是防回流的：
本模块**从来没引用过** `video/`，所以搬走之后代码里也不该长出任何指回去的路径——
真有人要 shotstat，路是 `video_pipeline_studio`，不是绕回舞台。

#### 15. 边界：发给页面的状态里，一条本机路径都没有

```bash
curl -s http://127.0.0.1:8093/app/agent_os/config.json | jq -e '
  (.brokerWs and .desktop and .uiVersion and .contentId and .instanceId) and
  ([paths(scalars) as $p | getpath($p) | tostring]
     | map(select(test("/Users/|\\.frago|^~"))) | length == 0)'
```
依据：「publish 只发渲染状态，NEVER 发路径」+「页面文件不在本模块手里，页面是前端」。
拦的理由不是洁癖：访客机器上没那个文件，而落点一挪，页面还在读老地方、每次刷新都
显示成功。

**NEVER 断言「键恰好是那五个」。**`config.json` 里除了配方发的五项，还有平台自己塞进去的
`apiBase` / `readOnly` / `recipeName` / `appBase` / `slot` / `runnable`——
**我实测过这份返回**，此刻它就是十一个键。写成 `keys == [五项]` 的验收单会在一个完全
正确的系统上红。配方这一侧能断言的只有两件事：那五项都在，且整份状态里没有一条本机路径。

**`brokerWs` 里那个 `/stream` 不算。**规则说的「一条路径都没有」指的是**文件系统**路径——
页面拿到文件路径也用不上，而 `ws://127.0.0.1:8770/stream` 是它拿画面的唯一通道。
上面的正则只认 `/Users/` / `.frago` / `~`，就是为了不把 URL 路径误伤成违规。

#### 只在特定时刻才错的，怎么造那个时刻

**「桌面页还没连上来」那条 WARN**（不致命，退出码仍是 0）：

```bash
# 把所有 agent_os 的标签页关掉，等 3 秒，确认 clients_count 归零
curl -s http://127.0.0.1:8770/status | jq '.clients_count'      # 得是 0
out=$(RUN '{"mode":"up"}'); echo "exit=$?"                      # 期望 0
printf '%s\n' "$out" | jq -e '
  .success == true and
  (.health.warn_count >= 1) and
  (.health.agent_must_respond | length > 0) and
  ([.health.checks[] | select(.item=="ui_ready") | .level] == ["warn"])'
```
依据：「不致命：桌面页还没连上来（自检那条 WARN 本身带补救说法）」+
`health.check_ui_ready` 的 `clients == 0` 分支。`agent_must_respond` MUST 在——
没有它，这条 WARN 就只是一句话；有它，读到的 agent 必须逐条书面回应。

**「broker 90 秒内没就绪」那条致命**：造法是让 8770 被一个**不答 `/status`** 的进程占住
（例如 `nc -l 8770`），再跑 `up`。期望：约 90 秒后退出码非 0，错误信息里有
`broker.log` 的位置。这条**贵且有破坏性**（要占端口、等一分半），
**只在动过拉 broker 那一段时才跑**；跑完 MUST 把占端口的进程收掉。

---

# 附：元素寻址与指令层词表 —— 2026-09-02 从 8-26 迁移前的版本补回

> 这两整节在迁移中被删，而 aos 与 broker 的对应实现一行未改。
> 核对方式：`frago desktop` 裸跑列资源，`frago desktop term` 列 term 的动词。

## 5. 元素寻址（v2 核心修正）

### 为什么不需要"视觉"

这个 OS 的每一个像素都是自己渲染的：dock 图标是桌面页的 DOM 元素，窗口矩形是 UI
上报的几何，标签条是自己画的，页面元素在舞台浏览器的 DOM 里，终端是 tmux 的字符
网格。位置全部是一手数据。截图加视觉模型是把已知信息渲染成像素再猜回来，慢、不准，
还凭空制造不确定性。系统 hook 同理——hook 用于拦截自己看不见的事件，这里没有
看不见的东西。

正确做法是把已有的位置真值暴露成可寻址的命名空间。

### 命名空间

前缀即域，域决定解析路径：

| ref 形式 | 域 | 真值来源 | 解析方式 |
|---|---|---|---|
| `dock:term` `dock:browser` | 桌面级 | 桌面页 DOM | UI 全量快照 |
| `win:term` `win:browser` `win:term.titlebar` | 桌面级 | 桌面页 DOM | UI 全量快照 |
| `tab:0` `tab:reddit` | 桌面级 | 桌面页 DOM | UI 全量快照 |
| `addr` | 桌面级 | 桌面页 DOM | UI 全量快照 |
| `page:<selector>` `page:"文字"` | 页面内 | 舞台浏览器 DOM | 按需查询 + 坐标换算 |
| `term:r12c40` | 终端内 | tmux 网格 | 字符宽高换算 |
| `term:rows 5-12` `term:rows -8` `term:match "error"` | 终端内 | tmux 画面文本 + 网格 | 行号换算成桌面矩形（**只能取景**） |

**桌面级走全量快照**：元素总共几十个，UI 在每次几何变化时连同 layout 一并上报所有
可寻址元素的矩形。全量优于按需——省掉往返延迟，并让"现在能点什么"零成本可查。

**页面元素走按需查询**：数量成千上万，无法全量。broker 在舞台浏览器执行 JS 按选择器
或文字定位，取得页面坐标，用已握有的窗口内容矩形与视口比例换算成桌面坐标。

坐标换算 MUST 在 broker 内完成。v1 由 agent 手工换算，窗口一动矩形就变，实测出现过
用旧坐标点空的故障。

### 终端画的是缓冲区，不是最后一屏（2026-08-20 加）

终端窗口里那几十行，取自一整块**缓冲区**：tmux 的 history 加当前可见屏。窗口是这块
缓冲区上的一个视口，`term scroll` 决定它停在哪一段。

**在这之前画面上只有最后一屏，而且这不是配置问题，是取数取少了。** pane 有多高由虚拟
终端窗口装得下多少行决定（见"UI 量字符格 → broker resize tmux"那条），所以命令输出一长，
前面的内容必然滚进 tmux 的 history。那份内容一直都在——`history-limit` 默认 2000 行——
只是 `capture-pane -e -p` 不带 `-S` 时只给可见屏，链路从头到尾没人去取。后果是画面上
永远只剩个尾巴：教学视频里一条长输出的前半段观众根本看不到，也没有任何指令能把它调回来。

采集改成两段，各按各的性质取：

| 段 | 怎么取 | 为什么 |
|---|---|---|
| 历史 | 只在它变长时取新增那几行（`capture-pane -S -<新增数> -E -1`） | 历史是追加式的，锚点是 tmux 自己数的 `#{history_size}`。每轮全量重取等于把同样的几千行每秒重抓八遍 |
| 当前屏 | 每轮整段替换（`capture-pane -e -p`） | 它本来就会被就地改写：提示符、进度条、全屏 TUI |

推给荧幕的是增量（`base` / `from` / 变化后的那一段），不是整段：缓冲区上限 4000 行，
整段推的话每秒八次、每次几百 KB，画面还得整块重画，正在回看的人脚下的行会跟着抖。
`history_size` 变小（会话重开、`clear-history`）或改过窗口尺寸（tmux 会重排，历史与
可见屏的分界线跟着动）时整段重取——这两种时刻增量锚点是错的，而错位之后每一帧看起来
都很正常。

**行号基准只有一个：画面上看得见的那一段。** `term:rows` / `term:r<行>c<列>` / `term:match`
一律以视口第一行为第 0 行，与改动前完全一致——贴底时视口就是当前屏，两者重合。缓冲区行号
只出现在 `term scroll` 的回执与错误提示里，且明确标着是缓冲区行号。两套基准混用是这个域
最容易踩空的设计，取景差一行在回执里看不出来。

因此摄像机只认视口：要框的文字在缓冲区里但不在画面上时，`term:match` 报错并点名它在缓冲区
第几行、该发哪条 `term scroll`，而不是照着一个看不见的位置去取景——那正是"回执全绿、画面
是错的"那一类。

**视口的作者是 broker，荧幕只执行（MUST，2026-08-20 反转）。** 视口停在第几行、贴不贴底，
这两个数记在 broker 手上，随 `term.scroll` 下发；荧幕照单摆位，**不拿自己的状态再解释一遍**。
与虚拟浏览器窗口几何同源：真值只有一份。

反转掉的是"broker 读主荧幕上报的 scrollTop 反推行号"那一版。它的错法是这套系统的老熟人：
每块荧幕收到滚动指令后各自拿自己的缓冲区行数和窗口高度去夹、去判贴底，而**录制机位每次
`rec start` 都是新开的一页**——它此刻一行都还没有，目标被夹成 0、还顺手把自己判成贴底，
等快照到了就一路贴回底部。于是成片里终端停在最后一屏，而回执写着它在第 6 行，两边都不算错。

跟着反转的还有三条：

- **新连上的荧幕要补发视口位置**，紧跟在缓冲区快照后面。不补的话它按出厂状态贴底画——
  人正回看着第 20 行，一开机位录下来的却是最后一屏。
- **补发到达时视口容器可能还没有高度**（高度是 `termGrid()` 设的，而它被下面那条 `synced`
  挡在补发之后），此时 `scrollTop` 会被静静夹成 0。所以容器高度一变就重摆一次视口。
- **荧幕报回来的 scrollTop 只当对账**：与 broker 记的差出一行以上就在 `/status` 与回执里
  标 `view_mismatch`。但只在两边看的是同一份缓冲区时才比（比 `bufferLines`）——layout 是
  事件驱动的，缓冲区每 0.12 秒可能长一截，拿旧数字比必然对不上，那是误报，报几次就没人看了。

**贴底是一个状态，不是一次刷新。** 视口贴着底时新输出跟着走（真实终端就是这样）；人一往回
滚就松开，否则回看到一半会被新输出拽回底部。松开状态下 `term run` 的回执带 `view_detached`：
命令照跑、缓冲区照长，而画面停在历史里，这件事不说出来就和"一切正常"长得一模一样。

判"到底了没有"用**行号**不用像素：`scrollHeight`/`clientHeight` 是取整过的，而行高带小数，
两者一减就有半像素出入——滚到底了却算成没到底，此后所有新输出都不再跟着走。

`--to "<文字>"` 的回执 MUST 带 `matched_row` / `matches` / `matched_screen_row`。没有它们，
"命中行摆在窗口中间"这句承诺在回执里无从验证——调用方只看得到一个 `first_row`，判不出
框住的到底是不是它要的那一行，而那正是拿去对镜头的数字。

滚动的**位置**一步到位写进 `scrollTop`，视觉上的移动交给一条 CSS transition。曾经是 rAF
补间逐帧改 `scrollTop`，错法很脏：浏览器判定标签不可见时会冻住 rAF、也会把定时器压到秒级，
补间一帧不跑，滚动静默地什么都没发生而指令返回成功。画面对不对不能取决于哪个标签在前台。

### 终端的三档粒度（2026-07-24 补中间那一档）

终端是唯一一个需要三档粒度的域，因为它同时是"可以点的界面"和"要给观众看的内容"：

| 档 | ref | 拿到的东西 | 什么时候用 |
|---|---|---|---|
| 单个字符格 | `term:r12c40` | 一个字符格（十几像素见方） | 指哪儿点哪儿——鼠标要落到某个字符上 |
| **一段输出** | `term:rows 5-12` / `term:rows -8` / `term:match "error"` | 若干整行组成的横条 | **终端镜头的常用粒度** |
| 整扇窗口 | `win:term` | 整个终端窗口 | 交代"终端在桌面上的位置"这类全景 |

中间这一档才是终端镜头真正要的粒度。教学视频里终端的镜头几乎全是「刚跑出来的那
几行输出」——一条命令的结果、一段报错、一个进度条。两头那两档都表达不出来它：字符
格推到 2.5 倍也只是一小块，没有镜头用途；整窗口推近了等于没推近，观众仍然得自己在
满屏文字里找该看哪里。这一档缺席时只剩两条退路，一条是拿整窗口凑合，另一条是退回
后期裁切——2026-07-24 就是这么翻的车，目测填 crop 参数，摄像机根本没对准要说的位置。

行号一律 **0 基**，与同域的 `term:r<行>c<列>` 共用一套坐标系。同一个前缀下混用两套
基准是最容易踩空的设计：差一位的取景错误在回执里看不出来，只有抽帧才发现。

`term:rows -8` 是最常用的形态。录制时最典型的动作是「跑一条命令，把刚出来的输出推近
给观众看」，而那段输出永远在末尾；绝对行号从上往下数，命令一跑完就漂移，负数形态才
稳定。末尾从**最后一个非空行**往上数：capture-pane 恒把画面补齐到网格高度，不跳过
尾部空行的话框到的多半是一片黑。

`term:match "<文字>"` 更贴 agent 的使用方式——它知道自己在找什么，不知道那东西在第
几行。多处命中取**最后一处**（终端往下滚，最新那次才是刚发生的），并在回执里报
`matches` 总数让调用方知道有歧义；`--context N` 把命中行上下各扩 N 行，因为报错那一
行单独框住往往读不懂，得看见它前面那条命令。

矩形取整行宽（网格左边界 + `cols × cellW`），不按最长行去裁——一段输出天然是整行宽
的，按内容宽裁会让画面左右随行长抖动，一行长一行短镜头就在晃。

行范围超出可见行数时 clamp 到可见范围并在回执里注明，不报错：终端刚启动只有两行时
要求末尾 8 行是完全正常的调用。终端窗口被收起时明确报错并提示先
`window restore --target term`，被关掉时提示 `window open --target term`——两者在 UI
那边上报的都是"不占桌面"的零矩形，对着它取景摄像机会飞到桌面外的虚空，而回执里每个
字段看起来都正常。两条提示分开写是因为补救动作不同，合成一句人会敲错那一条。

区域形态只有 camera 认。`mouse to` 这条路的契约是"一个点"，而区域是一片矩形，形状
不同，不硬塞进同一条路。

### 点击的意图归属

三分判定，与真实窗口系统的命中测试一致：

- 落在浏览器内容矩形 → 转页面坐标，发真实 CDP 输入事件
- 落在终端内容矩形 → 转 tmux 位置
- 落在桌面级元素 → **由 broker 自己执行窗口管理动作**（点 dock 图标即聚焦该程序、
  程序关着就启动它；点标签即切标签）。这与真实 OS 一致：点 dock 是窗口管理器的事，
  不是应用的事。

  **标题栏那三颗红黄绿是纯装饰，点不了。** 这里曾经写着"点关闭即关窗"，那是一句空头
  支票：UI 上报的可寻址元素只有 `dock:*` / `win:*` / `win:*.titlebar` / `addr` /
  `tab:<n>` 五类，红绿灯从来不在名单里，鼠标寻不到它；`desktop_action` 也只认 `dock:`
  与 `tab:` 两个前缀，其余一律回"无点击语义"。照着这句话去做的 agent 会撞墙，而且撞得
  莫名其妙——它连那颗红灯的坐标都拿不到。关窗口走 `window close --target <w>`。

**悬停绑定**：`mouse to <ref>` 之后 broker 记住当前悬停的 ref，`click` 优先按 ref
语义执行而非纯坐标命中。这样一两像素误差不会点空。

## 6. 指令层（aos）

### 入口

配方目录内的可执行：`~/.frago/recipes/workflows/agent_os/aos`。

不进 PATH——往用户环境塞东西是侵入性变更，与"配方不越权"同源。路径是常量，写进
文档一次即可；对训练而言前缀恒定、无歧义、不依赖某台机器的 PATH 配置。

它只做三件事：把短语解析成现有 op、按注册表找到目标实例、POST 到其 `/control`。
broker 协议一条不改。

### 寻址三档

单实例隐式绑定（九成场景）；零实例明确区分"不存在"与"存在但没跑"；多实例拒绝猜测，
要求 `--instance <id>` 或环境变量 `FRAGO_AGENT_OS`（实例选择器叫 `--instance` 而不是
`--to`——`--to` 已被 `browser scroll --to "<文字>"` 占用，同名两义会让训练样本自相矛盾）。
与 frago browser 的 group 机制同构，
不发明新心智模型。

### 语法约束（为 LoRA 训练服务，MUST）

**同一语义只允许一种写法。** 不做分号串联、不做别名、不做简写——那些是给人的便利，
对模型是噪声：等价形式泛滥会让训练样本形状不一致。

**复用模型预训练见过的语法家族。** 采用 `资源 动词 --具名参数`（kubectl / docker /
gh 同族），微调容量花在学策略而非学语法上。禁止裸位置参数——`cursor 1300 420 700`
这种形态靠位置携带语义，模型需记住"第三位是毫秒"这类脆弱约定，且新增参数会使历史
样本全部作废。

**动词自带意图。** 有目标的移动与无目标的闲晃用不同动词，而非同一动词的两种参数——
模型不必靠参数形态反推意图，两类样本分布天然分离。

### 词表

```
# 实例
aos up [--id default]              # 拉起实例（身份已存在则复用）
aos down                           # 停运行态，保留身份
aos status                         # 实例与健康状态
aos elements [--in browser] [--text <文字>]   # 列出当前可寻址元素及位置

# 鼠标
aos mouse to <ref> [--ms 700]      # 移到某元素（有目标）
aos mouse drift --x 900 --y 560 [--ms 700]   # 无目标闲晃，演示节奏专用
aos mouse click                    # 点当前位置，不接受坐标

# 窗口
aos window open|close --target term|browser|image   # 开关程序：在不在桌面上
aos window min|max|restore --target term|browser|image
aos window move --target <w> --x --y --w --h [--ms]
aos focus term|browser|image        # 置前台；程序关着就顺手打开

# 视口
aos viewport refresh [--ms 300]    # 重读演员视口，按新比例重摆虚拟浏览器窗口

# 终端
aos term run "<cmd>"
aos term read [--lines 20]            # 读缓冲区末尾若干行，够得着已滚出画面的历史
aos term scroll --lines <n>           # 回看，负数往回（形状对应 browser scroll --pixels）
aos term scroll --to "<文字>"          # 滚到最后一处匹配，命中行摆在窗口中间
aos term scroll --to-end              # 回到底部，并恢复"新输出跟着走"

# 图片浏览器（第三扇窗，2026-08-06 加）
aos image open <path>              # 装一张本地图片，顺带把这个程序打开
                                   # 关它走 window close --target image，无专属 close

# 浏览器
aos browser open <url>
aos browser click --text "recipes" | --selector "<sel>"
aos browser scroll --to "<文字>" | --pixels 600
aos browser read [--selector <sel>]
aos tab open <url> | switch <index> | close <index>

# 运镜（摄像机，不是窗口）
aos camera focus --ref <ref> [--ref <ref> ...] [--zoom 1.8] [--ms 1200] [--expand-to <sel>]
aos camera pan --to <ref> [--ms 2000] [--expand-to <sel>]   # 倍率不变，只挪中心
aos camera reset [--ms 1200]                                # 回 1 倍、回桌面正中

# 时间
aos wait --for <ref> | --url <pattern> | --text "<文字>" [--timeout 30]
aos pause --ms 1200                # 纯演示节拍，与语义等待区分

# 录制与字幕
aos rec start --name <name> [--force]   # --force 绕过开录门禁，绕过会留痕
aos rec stop                            # 回执带冻帧指标与 2×3 宫格路径
aos say "<text>" [--ms 2600]
```

### 开关程序（2026-08-10 加）

在这之前，这个 OS 里的程序**关不掉**。终端和浏览器根本没有关闭这个动作，最接近的
`window min` 只是收进 dock（程序还在跑、dock 的灯还亮着）；唯一关得掉的是图片浏览器，
而它走的是自己那条 `image close`。于是同一件事有两套语义，其中一套只对三个程序里的
一个成立——想录一段"演示完把终端关掉、只留浏览器"的镜头就演不出来。

现在三个程序共用一条路：

| 指令 | 画面上发生什么 | dock |
|---|---|---|
| `window close --target <w>` | 窗口原地缩一点淡出，离开桌面 | 灯灭 |
| `window open --target <w>` | 窗口淡入回来并置前台 | 灯亮 |
| `window min --target <w>` | 窗口飞进 dock 图标 | 灯还亮着 |
| `window restore --target <w>` | 从 dock 飞回来 | — |

**close 与 min 在画面上必须一眼分得开**，所以两者的动画刻意不同（缩放淡出 vs 飞向
dock），dock 的圆点是第二个信号。圆点的语义随之改成"这个程序在不在跑"（macOS 就是
这样），前台那个再亮一档——此前它只表示"哪扇窗口是前台"，于是开着的程序反而没有
任何标记。

**关掉不动载体。** tmux 会话照常在跑、演员标签照常在收画面、已经装进图片浏览器的那张
图留着，所以 `window open` 回来的是原样。杀掉它们在画面上看不出任何区别（观众只看到
窗口没了），代价却是真的：跑了一半的会话没了、重新拉起要几十秒。回执里的
`carrier_kept` 明说这件事，免得下一个人去查一个根本没发生的"会话被杀"。

**指向某个程序的动作会把它重新打开**，与 `ensure_active` 自动置前台同源：`term run`
打在一个关掉的终端上，正确结果是终端回来并执行，不是报一句"你得先打开它"。发生了就在
`effect.launched` 里说出来。要拍空桌面，不发这类指令即可。

**三个都关掉是合法状态**，此时 `focus` 为 `null`、菜单栏退回 Finder。键盘输入在这个
状态下没有接收方，`type` / `key` 明确报错而不是往空处送——不拦的话字会被送给一扇不在
桌面上的窗口，命令看着成功而画面什么都没发生。

`/status` 与 `elements` 都带 `windows_open`。与 `content_rects` 分开报：那边关掉的程序
是个 `null`，看不出是关了还是收起来了，而两者的补救动作不同（`window open` vs
`window restore`）。

### 窗口词的语义（2026-07-24 改）

`--target browser` 的三个动词不再是"摊满/还原"这种窗口管理器的语义，它们选的是宽度：

| 指令 | 宽 | 高 |
|---|---|---|
| `window max --target browser` | 桌面宽的 85%（1920 桌面即 **1632**） | `W / r`，r 取演员视口的宽高比 |
| `window restore --target browser` | 桌面宽的 75%（即 **1440**） | 同上 |
| `window move --target browser --w <n>` | `<n>` 夹进 1440–1632 | 同上，**不接受调用方给的 `--h`** |
| `window min --target browser` | 收进 dock，与几何无关 | — |

高度永远是算出来的，不是给的：给了高就等于给了一个跟演员视口不同的比例，画面要么变形
要么留白，而这两样正是这套设计要消灭的东西。桌面可用高装不下时由高定宽，宽会跌破 1440，
回执的 `notes` 里写清楚是被高度限制了——回执里说不清为什么是这个数字，下次有人看到 1400
就会以为是 bug。终端窗口不受这套约束，它照旧把意图交给 UI 算。

**`split` 已退场。** 对开要把浏览器压到半个桌面宽（约 950），与"恒占 75%–85%"直接冲突；
两条规则无法共存，留下后者——半宽的浏览器要么违反下界，要么就得放弃与演员视口同比例，
而同比例是这套设计的全部意义。

### 运镜词的语义与三档反馈（2026-07-24 加）

`camera` 管的是**摄像机**——取景框对着桌面的哪一块；`window` 管的是**被摄物**——虚拟窗口
在桌面里多大、摆在哪。两者都会改变"元素在成片里有多大"，但改的是完全不同的东西。取景只
作用于录制落盘的帧，桌面页上人看到的画面不变，所以不录制时 `camera focus` 是一条纯预演
指令：它照样算出构图，让调用方在开录**之前**就发现这个元素在 2 倍下没法居中。

倍率钳在 1.0–2.5。下限是几何的，1 倍就是整个桌面，再缩只有黑边；上限是清晰度的，桌面页
按 1920×1080 渲染，3 倍等于把 640×360 的真实像素拉满全屏，信息量不增反减。想要更清晰的
特写得让虚拟浏览器窗口本身更大让页面重排，那是录制前的事。

`--ref` 可以给多个，取所有目标的外接矩形。旁白说"装机量最高的这几个"时要的是好几张卡并排，
按单个 ref 取景就是错的——镜头会怼在第一张上，而观众听到的是"这几个"。多目标时 `--zoom`
退化成**上限**：装不下所有目标的倍率没有意义，实际取的是外接矩形（含 40px 安全边距）能装
下的最大倍率，回执里 `zoom_fit` 与 `zoom_note` 会写清楚。

回执分三档：

| 档 | 判据 | 语义 |
|---|---|---|
| 居中 | `centered: true` | 目标落在画面正中 |
| 贴边受限 | `centered: false` + `clamped` + `offset` | 目标在画面内，但没能完全居中 |
| 出框 | `ok: false`（CameraError） | 倍率太高，或目标本身比取景框还大 |

**贴边算成功。** 元素靠近桌面边缘时取景框移到边界也无法让它完全居中，但画面确实拍到了、
构图可用，报成失败会逼调用方处理一个不用处理的情况。反过来，静默居中失败更糟——那正是
2026-07-24 翻车的模式：以为对准了，实际没对上。所以 `clamped` 明说夹在哪几条边，`offset`
明说差多少像素，两个字段合起来让调用方自己判断这一镜要不要重构图。

`clamped` 恒为数组，不因为只夹了一条边就退化成字符串：角落里的元素真的会同时夹住两条边，
只报一条是撒谎；而同一字段一会儿是字符串一会儿是数组，正是本节语法约束要挡的那种形状不
一致。回执里刻意**不提供** `min_zoom_centered` 这类"提高倍率就能居中"的建议：数学上成立
但结论荒谬——左贴边元素要推到 5.33 倍才能居中，那时取景框只剩 360×203，上下文全切掉，
画面还糊。贴边元素的正解是让它别贴边：把虚拟浏览器窗口挪到桌面中间，或滚动页面让元素落到
视口中部，然后 1.5–2 倍就够。

### 动作自动激活目标窗口（MUST，2026-07-24 加）

**规则：任何指向某扇窗口的动作，都自动把该窗口置为 active；active 窗口恒在最上层。**

| 动作 | 激活 |
|---|---|
| `mouse to --ref`（ref 落在页面里） | browser |
| `mouse to --ref`（ref 落在终端里） | term |
| `mouse to --x --y`（纯坐标，没声明目标） | 不改焦点 |
| `browser open` / `scroll` / `read` / `click`，`elements --in browser` | browser |
| `tab open` / `switch` / `close` | browser |
| `term run` | term |
| `type` / `key` | 当前 active 的窗口（键盘本来就送给前台，这里恒是 no-op；三个程序全关掉时明确报错，不往空处送） |
| `camera focus` / `camera pan`，ref 落在页面里 | browser |
| `camera focus` / `camera pan`，ref 落在终端里 | term |
| `camera reset` | 不改焦点——它回的是整个桌面，不指向任何一扇窗口 |
| `wait`、`term read` | 不改焦点，见下 |

**为什么必须是自动的，不能靠调用方记得先发 `focus`。** 2026-07-24 录 twitter 时
`camera focus --ref page:"Explore" --zoom 1.8` 的回执全绿——`ok: true`、
`target_in_frame: true`、`clamped: ["left","top"]`、几何一个数字都没错——而抽帧一看，
画面里推近框住的是终端窗口，x.com 的侧栏压在它下面。实例起来后焦点默认是 term，
整段录制里发的 `browser open` / `elements` / `camera focus` 没有一条会改焦点，
终端就一直压在上面。

`camera` 对准的是"元素在桌面坐标系里**应该**在的位置"，它没有、也不可能有"那个位置现在
显示着什么"这个信息，所以这类错误在回执里一个字都看不出来，只有录完抽帧才发现，那时现场
早没了。凡是"漏发一条指令就静默拍错、且只能事后从成片发现"的东西，都不该留给纪律。

实现是 broker 里唯一一条 `ensure_active(win)`，所有指向窗口的 op 进来先过它，不在各个 op
里散着抄 `if win != stage.focus`——散着抄正是这次一口气漏掉 navigate / exec / type /
camera.focus / camera.pan 五处的直接原因。`focus` 保留为显式动词（人明确要换焦点时用），
`ensure_active` 是它的幂等封装：已经是 active 就 no-op，不广播、不产生多余的 layout 上报。

**激活如实回报，绝不静默改状态**：发生了就在 `effect` 里带 `focus: {before, after}` 与
`focus_changed`，调用方要能从回执看出"我这条指令顺带把窗口提到了前面"。

**目标程序关着时，`ensure_active` 顺手把它打开**（2026-08-10 补）。理由与自动激活同源：
`term run` 打在一个关掉的终端上，正确结果是终端回来并执行。启动比换焦点动静大得多——
画面上多出一扇窗——所以单列 `effect.launched`，不混在 `focus_changed` 里。

**鼠标移动也算"指向窗口的动作"（2026-08-04 补）。** 上面那句"散着抄漏了五处"当时还漏了
第六处：`cursor`。它当时看起来像纯粹的画面动作、不指向任何窗口，于是没挂 `ensure_active`。

漏掉它的表现和当初那次一模一样——回执全绿、画面是错的。判断鼠标落在哪扇窗口用的是层级
顺序，浏览器被终端压着时，指向浏览器元素的坐标会被判成 term，于是悬停不转发给真实浏览器：
菜单不展开、按钮不高亮，而回执里只写着 `win: "term"`。

靠后面那步 `click` 补激活不够：`browser click` 在 aos 里恒被编译成 `cursor` + `click`
两条，激活挂在 `click` 上意味着鼠标先当着镜头从错误的窗口上划过去，窗口在按下的瞬间才跳到
前面。所以激活必须发生在**移动之前**。

判定用哪扇窗口沿用 `target_window(ref)`（与 camera 同一条），不看坐标——坐标恰恰是被层级
污染的那个量。纯坐标移动（`--x --y`）没有声明目标，不改焦点。

**观察类指令例外。** `wait` 与 `term read` 是"看"不是"做"：盯一个还没出现的元素时反复翻
窗口层级，录进片子里就是一段没人下过的指令。`wait` 的探针（走 `elements` / `exec`）因此
带 `observe: true`，broker 见到它就不激活；`term read` 直接读 tmux，根本不经过 broker。

### 开录门禁（MUST，2026-07-24）

`rec start` 在真正开录之前逐项体检，任何一项不成立就**拒绝开录**并返回 `ok:false`
（HTTP 409），载荷里给 `gate`（每条含 level / item / detail / means / if_ignored /
how_to_fix，与 health 自检同构）与 `how_to_fix` 列表。

| 判据 | 不满足时录下来是什么样 |
|---|---|
| 本实例荧幕有且仅有一块 primary，无重复客户端 | 多块荧幕轮流覆盖布局，几何来回跳 |
| tmux 会话存在（`capture-pane` 取得到内容） | 终端窗口全程空白，只有 broker.log 在刷 capture-pane 失败 |

**曾经有四项，撤掉了两项**，理由不同：

`viewport_matches_window` 随视口权威反转一并作废。它问的是"演员视口跟不跟得上虚拟
窗口"，那是覆写模型下才成立的问题；现在虚拟窗口的形状是按演员视口的比例算出来的，
两者同比例是构造出来的而不是校验出来的，这条判据恒为真——一条永远通过的闸门不是
防线，是噪声。

`ui_ready` 撤于同日，理由是它把正当镜头误判成故障。它问的是"最近 3 秒有没有新帧"，
而静止的网页本来就不产帧；想拍一个不动的界面是完全正当的镜头，此刻画布上挂的帧没有
骗人，只是没在动。拿它当开录判据等于禁止静态镜头。冻帧那类真故障改由 `rec stop` 的
`unique_ratio` / `frozen_tail_sec` 事后抓——那两个数分得开"没在动"和"该动却没动"，
开录前分不开。`ui_ready` 仍留在 `/status` 与启动自检里，那里它是信息，不是闸门。

**为什么剩下两项是硬拒绝而不是警告。** 它们的共同形态是：指令全部生效、回执全部正常、
`/status` 一切正常，只有画面是错的。警告在这种形态下没有作用——它出现在开录那一刻的
输出里，而人和 agent 此时正忙着往下走脚本，等发现不对已经是二十分钟后看成片的时候，
那时素材已经废了，重录的成本是整段重演。拦在开录前的代价只有几秒钟。这两条纪律在
2026-07-23/24 那次拍片会话里各被违反两次，其中一次就发生在 agent 刚写完反省之后：
散文形态的纪律靠自律执行，自律不可靠。能被代码拦住的，不要写进文档靠人记。

错误信息 MUST 给出可直接抄的修复命令，而不是只说哪里不对。抄不动的场合（比如就是要
拍故障现场）用 `rec start --force` 显式绕过：绕过后回执带 `gate_bypassed` /
`gate_bypassed_detail` / `gate_note`，broker.log 同时写一条 ⚠️ 记录。**绕过留痕，
不许静默**——事后回看成片发现构图不对时，要查得到当时是知情放行的。

停录侧对称地补上事后证据：`rec stop` 自动从成片按时长百分位（8/25/42/58/75/92%）抽
6 帧拼成 2×3 宫格 `<name>-contact.png`，并给出 `total_frames` / `unique_frames` /
`unique_ratio` / `effective_fps` / `frozen_tail_sec`。去重比值是冻帧故障最早的可见
信号，比人肉眼看宫格更早；`frozen_tail_sec` 超过 3 秒在回执里标 warn。抽帧与去重全部
交给 ffmpeg（mpdecimate / freezedetect / scale+stack），不在 Python 里逐像素循环。
自检恒不抛异常——诊断出错不得让停录失败，片子已经录好了。

**批量模式**：从标准输入读，每行一条，顺序执行。时序精度由 broker 内部保证，与调用
进程次数无关；这也让长路径前缀只出现一次。单条模式用于探索与调试。

### 坐标的定位

`mouse drift --x --y` 保留，但语义上明确是"自然随意的移动"——录制时鼠标轨迹要走得
像人，那时才需要绝对坐标。它不参与操作语义。

理由：像素坐标是坏的训练信号。教模型"点在 (1300, 420)"没有泛化价值，换个窗口尺寸
或页面版本立刻作废；教模型"点击文字是 recipes 的按钮"才可迁移。训练样本因此天然
分成两类——语义层教策略（主体），坐标层只教"怎么把鼠标演得像人"（仅录制场景）。


---

# 附：前端资源包（原 agent_os_ui 规格，2026-09-02 并入）

下面这一节是**原样搬过来的**，一个字没改，所以它仍按「一个独立配方」的口吻说话。
搬家之后有三处不再成立，读的时候按这里的说明折算：

- **它不再是一个配方。** `agent_os_ui` 整个配方随这次迁移作废。那四个文件现在住在
  `src/frago/desktop/assets/`，服务端直接从包里发。
- **三个 mode 只剩下半个。** `install`（把文件铺到某目录）与 `assets`（把内容念出来）
  都失去了意义——文件就在包里，没有第二份、也没有跨模块要内容这回事。`status`
  唯一还有人用的那个字段 `asset_version` 变成了包内的一个函数
  （`stage.ui_version()`）。
- **版本号的口径换了，是被迫的。** 下面写着「全部常规文件 mtime 的最大值」，还写着
  「不换成内容哈希，换了就是改契约」。那个判断在配方年代成立，进 wheel 之后不成立：
  wheel 里每个条目的时间戳被归一化成固定值（实测 `02-02-2020 00:00`），装完之后
  mtime 至多是安装时刻，**不再是资产内容的函数**。而 broker 拿这个数做**相等**比对，
  两个内容不同的 frago 版本算出同一个数，旧标签就被当成新的、几何照收——画面变形
  而没有一处报错。所以现在算的是内容哈希（名字 + 内容，取 48 位，为的是过一趟
  JavaScript 还是精确整数）。

# agent_os_ui 规格

> 这份规格由 frago recipe plan 生成，`frago recipe create agent_os_ui` 会读它。
> **下面几个字段是给机器读的，写什么，模板里就长出什么。**
> 想清楚再写：改代码容易，改一个已经被别人依赖的接口难。

## 机器读的部分

```yaml
type: atomic          # atomic（一件事）| workflow（串起几件事）
runtime: python       # 旧版是 shell。改成 python 才建得在基类 Recipe 上——
                      # 信封、warn/fail 两档、落点、总线放行都由基类给

# 这个模块能做哪几件事。一个 mode 一件事，第一个是默认。
modes:
  - install           # 把 assets/ 里的文件铺到调用方给的目录
  - status            # 现在有哪几个文件、各多大、这一整套是哪一版
  - assets            # 把这几个文件的内容念出来

# 别的模块能调哪几个 mode。MUST 是只读的：
# 不触网、不重算、不改状态、不开浏览器——别人每 5 分钟问一次也不会出事。
# status 只 stat 自己目录里的文件，assets 只读自己目录里的文件，两个都够格。
# install 往磁盘上铺文件，它在干活，所以不导出。
exports:
  - status
  - assets

# 用了谁的哪个口。写下来，对方才知道自己正在被谁读。
# 这个资源包不问任何人要东西：进来的是一个目标目录，出去的是四个文件。
imports: {}

# 要不要一张页面。
# 它**持有**页面文件，但那张页面是 agent_os 支起来的舞台，不是本模块的页面：
# 本模块不发布状态、不开浏览器、也没有人从 frago 的页面列表里点开它。
page: false
```

## 人读的部分

### 它解决什么问题

**谁**：`agent_os`——桌面舞台的编排方。
**什么时候**：舞台起来、要把桌面页交给浏览器的那一刻，它需要这几个前端文件的内容；
以及要在页面配置里写下「桌面页现在是哪一版」的时候。

这个模块本身是一个**假 macOS 桌面舞台的前端资源包**：一个 `index.html`、一个
`style.css`、两个 js。全屏打开后被录屏，画面来自真实 tmux 与真实 Chrome 标签页，
由 agent_os 的 broker 进程经 WebSocket 推给页面。页面是**只读显示器**，自己不产生
任何操作；零第三方依赖，不外链任何 CDN / 字体 / 图片。

```
assets/
├── index.html    桌面骨架：桌布画布、顶栏、Dock、两扇窗口、鼠标、字幕
├── style.css     macOS 视觉：毛玻璃、标题栏激活态、涟漪动画
├── app.js        WebSocket 客户端、帧管线、layout 上报、重连、桌布渲染
└── ansi.js       ANSI(SGR) → HTML（16 色 + 亮色、粗体、反显）
```

**这次改造真正要修的东西**：旧版 agent_os 是直接伸手进
`~/.frago/recipes/atomic/system/agent_os_ui/assets/` 复制文件的
（`recipe.py:26` 那行写死的绝对路径），并且自己 `stat` 那个目录、按所有文件 mtime
的最大值算「资产版本」。于是本模块**不知道自己正在被读**——改自己的文件时看不到
任何提示说别处依赖着这个目录、这几个文件名；断裂不在改动那一刻暴露，只在有人点开
桌面页那一刻暴露，而那时看到的是「画面被拉伸变形」，跟改了哪个文件毫无关系。

`assets` 口就是把那条路搬到总线上：调用方 `ask("agent_os_ui", "assets")`，本模块答，
依赖在两边都写在明面上。**念内容而不是交路径**——路径只在写它的那台机器上成立，
而且对方按路径来翻的话，本模块改自己的文件时照样看不到任何提示，等于换了个写法
把同一个病搬过来。

`status` 里的版本号同理：**取的是目录里全部常规文件 mtime 的最大值**。只看
`index.html` 不够——改的往往是 `app.js`，而 `index.html` 一动不动。

### 每个 mode 做什么

| mode | 输入 | 输出 | 只读？ |
|---|---|---|---|
| `install`（默认） | `target_dir`（可选） | `success` / `target_dir` / `files`——字段名与旧版逐字一致 | **否**——往磁盘上铺文件，所以不导出 |
| `status` | — | `count` / `files[{name, bytes}]` / `asset_version` | 是——只 `stat` 自己目录里的文件 |
| `assets` | — | `count` / `files[{name, bytes, type, text}]` / `asset_version` | 是——只读自己目录里的文件 |

三个 mode 的 `files` **一律按文件名升序**（`ansi.js` / `app.js` / `index.html` /
`style.css`）。一套顺序管三个口，调用方不用记哪个口是哪个顺序。

#### install

把 `assets/` 里的每个常规文件原样铺到目标目录，内容逐字节相同。

- `target_dir` 给了就落那儿。**必须是绝对路径**；目录不存在就 `mkdir -p` 建出来；
  同名文件直接覆盖，不留副本、不报错——铺设是幂等的，铺第二遍和第一遍结果一样。
- `target_dir` 不给**不是错**，落 `self.store.path("assets")`，也就是平台交代的落点
  底下。旧版在这里 `exit 1`，新版 **NEVER 报错退出**。落点由平台交代，
  **NEVER 自己拼 `~/.frago/data/...`**。
- 返回里的 `success` 与信封的 `ok` 是重复的，**故意保留**：旧调用方读的是
  `data.success`，安静去掉它就是安静地把老调用方打断。
- `files` 是**实际铺过去的文件名**，不是写死的四个。写死的清单在少铺一个文件时
  也照报四个，那种成功比失败更贵。
- **不保证 mtime 跟源文件一致。**版本走 `status` / `assets` 那条路，
  **NEVER 从铺出去的副本上重算版本**——副本的 mtime 是复制那一刻，不是资产的年纪。

#### status

`count`、每个文件的 `name` 与 `bytes`、以及 `asset_version`。

`asset_version` 是**整数（Unix 秒）** = `assets/` 下全部常规文件 mtime 的最大值取整。
桌面页每次上报 layout 都带着它，broker 拿它做**相等**比对（`got != want` 就整条丢
弃并叫那个标签自己刷新）。所以这个数字本身没有意义，唯一的要求是**资产变了它就变**。

已知的钝处，写在明面上：复制、重装、`touch` 都会让它前进而内容一个字节没改。
后果只是让开着旧标签的页面多刷新一次，不是错误——这是它比内容哈希便宜的地方，
也是不换成哈希的理由（换了就是改契约，broker 那边的相等比对得跟着一起改）。

#### assets

把这几个文件的内容念出来。文本类按 UTF-8 解码后放进 `text`，并给出 `type`
（`index.html` → `text/html`，`.js` → `text/javascript`，`.css` → `text/css`）。

- 单个文件**超过 2 MB**：只报 `name` / `bytes` / `type`，`text` 为 `null`，并 `warn`。
- 单个文件**念不动**（读权限没了、不是合法 UTF-8）：同样 `text` 为 `null` + `warn`，
  **它自己仍然出现在 `files` 里**，另外三个照常带内容。
- 两种情况都 `warn`，是因为 `text` 为 `null` 有两个原因，不喊出来调用方分不出是
  「太大了别念」还是「这个文件坏了」，也不知道该去看什么。
- 一并返回 `asset_version`，省掉一次往返，也保证「拿到手的这几个字节」和「记下来
  的这个版本号」出自同一次读取。

### 它不做什么

- **不采集、不操控、不录制、不起 broker。**那些是 agent_os 的活。tmux 抓帧、Chrome
  截帧、WebSocket 服务端、录屏，本模块一样都不碰。
- **不自己开页面给人看。**不 `publish` 状态、不 `frago recipe open`、不开浏览器。
  舞台是 agent_os 支的，本模块只是那张页面的仓库。
- **不改 `assets/` 里的四个文件。**改造只换外壳：`index.html` / `style.css` /
  `app.js` / `ansi.js` 从旧配方原样搬过来，**一个字节都不动**。
- **不交路径。**`status` 和 `assets` 的返回里没有 `path`、没有 `assets_dir`，
  一个都不给。要文件就拿内容。`install` 回的 `target_dir` 是调用方自己给进来的那
  条路径原样回声，不是本模块的内部位置。
- **不管调用方拿去干什么。**铺完就完，不校验目标目录后来变成什么样，不做增量、
  不做清理、不删目标目录里别人的文件。
- **不读别的配方的目录、不 import 别的配方的代码。**`imports` 为空不是还没填。
- **不带旧目录里的备份文件。**旧 `assets/` 里那个 `app.js.bak-20260824-wp` 不搬过来。
  它会被 `install` 一并铺到目标目录，也会顶着 mtime 参与版本计算——有人 `touch`
  一下备份文件，桌面页就集体刷新一次，而没有任何东西变了。
  **`assets/` 里只放这张页面真正要用的文件。**

### 数据

**本模块自己不存业务数据。**没有账本、没有缓存、没有历史。同一份 `assets/` 问一百遍
给的是同一个答案。

`assets/` 目录是**本模块自己的源码文件**（跟 `recipe.py` 同级，用
`Path(__file__).parent / "assets"` 读），不是数据目录，也不是别人的数据——读它不
违反「跨模块只走接口」。

`install` 唯一写的东西就是铺出去的那几个文件：给了 `target_dir` 就落那儿，
那是**调用方的落点**、由调用方负责；不给才落 `self.store.path("assets")`。
两条路都不由本模块拼路径。

### 出错怎么办

| 情况 | 怎么报 | 数据 |
|---|---|---|
| 平台没交代落点（且没给 `target_dir`） | 基类抛 `NoLandingSpot`，**配方不接不兜底** | 不动 |
| `assets/` 目录不存在 | **致命** `raise self.fail`，错误信息里带上它该在哪 | 不动 |
| `assets/` 在，但一个常规文件都没有 | **致命**。空资源包铺出去是一张打不开的页面，而且版本算不出来（对空集取最大值） | 不动 |
| `target_dir` 不是绝对路径 | **致命**。路径一律绝对 | 不动 |
| `target_dir` 指向的是一个已存在的**文件** | **致命**，不去猜它是不是想要目录 | 不动 |
| `target_dir` 指向的目录不存在 | **不报**，`mkdir -p` 建出来 | 建目录 |
| `target_dir` 里已有同名文件 | **不报**，直接覆盖 | 覆盖 |
| `assets` 里某个文件念不动（权限、不是 UTF-8） | **不致命** `self.warn`，点名那个文件；它的 `text` 为 `null` | 不动 |
| `assets` 里某个文件超过 2 MB | **不致命** `self.warn`，只报名字和大小 | 不动 |
| 铺文件时某个文件写不进去（目标目录只读、盘满） | **致命**。铺了一半的资源包是一张半张的页面，比没铺更难查 | 已铺的留在原地，错误信息里说清铺到哪一个断的 |

分界线只有一条：**这套资产还答不答得出来。**一个文件念不动，另外三个还是真的，
答案还有用 → `warn`；目录没了、一个文件都没有、路径根本不合法 → 答案作废 → `fail`。

`install` 那条例外要单拎出来说：铺文件是**写**，写到一半停下不是「部分可用」，
是留下一个内容不全的目录，而那个目录接下来会被当成一整套资产使用。所以它按致命处理。

### 怎么验

下面每条都能直接跑。`frago recipe run` 把信封的 `data` 打在 stdout、把
`[recipe] …` 那行摘要打在 stderr，所以一律 `2>/dev/null | jq`。
`warnings` 非空时会跟着 data 一起出现。

先把目录记下来：

```bash
A=~/.frago/recipes/atomic/system/agent_os_ui/assets
RUN() { frago recipe run agent_os_ui --params "$1" 2>/dev/null; }
```

#### 1. status 报得出四个文件

```bash
RUN '{"mode":"status"}' | jq -e '.count == 4 and
  ([.files[].name] == ["ansi.js","app.js","index.html","style.css"])'
```
依据：「`assets/` 里只放这张页面真正要用的文件」（四个）+「`files` 一律按文件名
升序」。这条同时守着备份文件那条边界——`app.js.bak-…` 混进来 `count` 就是 5。

#### 2. status 报的大小就是磁盘上的大小

```bash
RUN '{"mode":"status"}' | jq -r '.files[] | "\(.name) \(.bytes)"' > /tmp/aosui-said.txt
for f in ansi.js app.js index.html style.css; do
  echo "$f $(stat -f%z $A/$f)"
done > /tmp/aosui-disk.txt
diff /tmp/aosui-said.txt /tmp/aosui-disk.txt && echo OK
```
依据：`bytes` 是文件实际大小。循环顺序与升序规则一致，所以两份能直接 diff。

#### 3. asset_version = 全部文件 mtime 的最大值

```bash
want=$(for f in $A/*; do stat -f%m "$f"; done | sort -n | tail -1)
got=$(RUN '{"mode":"status"}' | jq -r '.asset_version')
[ "$want" = "$got" ] && echo "OK $got"
```
依据：「`asset_version` = `assets/` 下全部常规文件 mtime 的最大值取整」。

**期望值 MUST 现算，NEVER 写死一个数。**旧目录里这个值是 `1787549479`
（2026-08-24 13:31:19，`app.js` 的 mtime），但 `frago recipe create` 复制文件时
mtime 会变成复制那一刻——把 `1787549479` 写进验收单，照着验会得出「配方错了」的
结论，而错的是期望值。

#### 4. 改的是 app.js，版本也得跟着动

```bash
orig=$(stat -f%m $A/app.js)
touch -t 203001010000 $A/app.js                 # 只动 mtime，内容一个字节不改
[ "$(RUN '{"mode":"status"}' | jq -r '.asset_version')" = "$(stat -f%m $A/app.js)" ] && echo OK
touch -t $(date -r $orig +%Y%m%d%H%M.%S) $A/app.js   # MUST 还原
```
依据：「只看 `index.html` 不够——改的往往是 `app.js`，而 `index.html` 一动不动」。
用一个未来时间而不是 `touch` 到当下：`create` 刚复制完时四个文件的 mtime 就是当下，
`touch` 到同一秒会让「变大了」这个断言变成 51% 的运气。

#### 5. assets 四个文件都念得出内容

```bash
RUN '{"mode":"assets"}' | jq -e '
  ([.files[] | select(.text == null)] | length) == 0 and
  (.files[] | select(.name == "index.html") | .text | test("<html"))'
```
依据：`text` 为 `null` 只有两个原因——超过 2 MB，或念不动。四个文件里最大的是
`app.js` 55220 字节（54 KB），离 2 MB 差两个数量级，权限也是正常的，所以四个
`text` 都该有内容。`index.html` 第二行就是 `<html lang="zh">`，含 `<html`。

#### 6. assets 交的是内容，不是路径

```bash
RUN '{"mode":"assets"}' | jq -e '[.files[] | keys[]] | index("path") == null'
RUN '{"mode":"status"}' | jq -e 'has("assets_dir") | not'
```
依据：「不交路径」那条边界。

#### 7. install 铺到空目录，四个文件齐全且逐字节相同

```bash
T=$(mktemp -d /tmp/aosui-install.XXXXXX)        # 全新的空目录，不用手工清
RUN "{\"mode\":\"install\",\"target_dir\":\"$T\"}" | jq -e --arg t "$T" '
  .success == true and .target_dir == $t and
  (.files == ["ansi.js","app.js","index.html","style.css"])'
diff -r $A $T && echo "逐字节相同"
```
依据：「原样铺过去，内容逐字节相同」+「返回字段 `success` / `target_dir` / `files`
与旧版逐字一致」+ 升序规则。`diff -r` 只在两边文件集完全相同时才干净通过，所以它
同时验着「不带备份文件」——`assets/` 里多一个 `.bak`，这条也会红。

#### 8. 铺第二遍和第一遍一样

```bash
RUN "{\"mode\":\"install\",\"target_dir\":\"$T\"}" > /dev/null
diff -r $A $T && echo OK
```
依据：「同名文件直接覆盖，不留副本、不报错——铺设是幂等的」。

#### 9. 不给 target_dir 不报错

```bash
out=$(RUN '{"mode":"install"}'); echo "exit=$?"   # 期望 0。管道里的 $? 是 jq 的，
                                                  # 要配方自己的退出码就得先接住
printf '%s\n' "$out" | jq -e '.success == true and (.target_dir | startswith("/"))'
```
依据：「`target_dir` 不给不是错，落 `self.store.path("assets")`，
**NEVER 报错退出**」。期望退出码 0，`target_dir` 是平台落点底下的绝对路径。
旧版在这里 `exit 1`——这条验的就是旧行为已经改掉。

#### 10. 默认 mode 是 install

```bash
RUN "{\"target_dir\":\"$T\"}" | jq -e '(.files | length) == 4'
```
依据：`modes` 第一个是默认，`modes` 的第一个是 `install`。

#### 11. install 没被导出

```bash
grep -n "exports" ~/.frago/recipes/atomic/system/agent_os_ui/recipe.py
```
期望：`exports = ("status", "assets")`，里面没有 `install`。
依据：「exports MUST 只读」+「`install` 往磁盘上铺文件，它在干活，所以不导出」。

这是**静态声明检查**，说清楚为什么：总线上的放行由内核照这个元组判，而
`frago recipe run` 是自己跑自己、不过总线，跑一条命令验不出「别人调不到」。
真要动态验，得让另一个模块 `self.ask("agent_os_ui", "install")` 去撞 `NotExported`。

#### 12. target_dir 是相对路径要拒跑

```bash
RUN '{"mode":"install","target_dir":"relative/dir"}' > /dev/null; echo "exit=$?"
```
期望：非 0。依据：「必须是绝对路径」那条致命。

#### 13. assets 目录不存在是致命的

```bash
mv $A $A.off
RUN '{"mode":"status"}' > /dev/null; echo "exit=$?"     # 期望非 0
mv $A.off $A                                            # MUST 立刻还原
```
依据：「`assets/` 目录不存在 → 致命」。这个目录就是本模块的正身，
**验完 MUST 马上改回来**，别让下一条验收跑在一个残废的模块上。

#### 14. 一个文件念不动，另外三个不许跟着消失

造那个时刻：

```bash
chmod 000 $A/ansi.js
out=$(RUN '{"mode":"assets"}'); echo "exit=$?"    # 期望 0：不致命
printf '%s\n' "$out" | jq -e '
  (.files | length) == 4 and
  ([.files[] | select(.name == "ansi.js") | .text] == [null]) and
  ((.warnings | join(" ")) | test("ansi.js")) and
  ([.files[] | select(.name != "ansi.js") | select(.text == null)] | length) == 0'
chmod 644 $A/ansi.js
```
依据：「单个文件念不动 → `self.warn`，它自己仍然出现在 `files` 里，另外三个照常带
内容」。root 身份下 `chmod 000` 拦不住读，这条要用普通用户跑。

**接住返回值之后 MUST 用 `printf '%s\n'` 喂给 jq，NEVER 用 `echo "$out"`。**
zsh 的内建 `echo` 默认解转义：`assets` 返回的 `text` 里全是 `\n` 和 `\"`，`echo`
会把它们当成真的换行和引号还原出去，jq 收到的已经不是合法 JSON 了，报的是
「control characters must be escaped」——看起来像配方吐了坏 JSON，实际是验收单
自己把它拆了。跑这一条的时候真撞上过。

#### 15. 超过 2 MB 只报名字和大小

这条**不在正身目录上验**，也 **MUST 单独跑，不与第 1 条同时跑**——它要往 `assets/`
里放第五个文件，跑的时候 `count` 是 5。

```bash
dd if=/dev/zero of=$A/huge.js bs=1m count=3 2>/dev/null
RUN '{"mode":"assets"}' | jq -e '
  ([.files[] | select(.name == "huge.js") | .text] == [null]) and
  ([.files[] | select(.name == "huge.js") | .bytes] == [3145728]) and
  ((.warnings | join(" ")) | test("huge.js")) and
  ([.files[] | select(.name != "huge.js") | select(.text == null)] | length) == 0'
# 收尾 MUST 做：这个假文件留着，第 1 条和第 7 条都会红
mv $A/huge.js "$HOME/.Trash/aosui-huge-$(date +%s).js"
```
依据：「单个文件超过 2 MB → 只报 `name` / `bytes` / `type`，`text` 为 `null`，并
`warn`」。3 MB = 3145728 字节，`dd bs=1m count=3` 出来的就是这个数。
