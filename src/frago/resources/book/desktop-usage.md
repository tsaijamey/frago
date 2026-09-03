# desktop-usage

分类: 替代（MUST）

## 是什么

一块假 macOS 桌面，上面三扇窗口装的是**真东西**：一个真实 tmux 会话、一个真实浏览器标签页、一个图片浏览器。整块桌面可脚本操控——鼠标移动、点击、窗口层级、镜头推拉都能下指令，所以一段自动化流程可以被演成"人在操作"的样子录下来。

入口是 `frago desktop`，与 `frago browser` 同级：一个驱动真实浏览器，一个驱动这块舞台。

## 怎么用

**标准路径三步，顺序不能省。** 和用浏览器前先 `browser status` 是同一个道理：

```
frago desktop status                       # 舞台在跑吗
frago desktop up                           # 不在就拉起来
frago desktop browser open https://...     # 然后才是干活
```

`status` 回执里 `ok: false` 且 `error` 写着"没在运行"，就是该 `up` 的信号，`hint` 里有现成的命令可以照抄。

动词地图（裸跑 `frago desktop` 也会列出来）：

| 资源 | 动词 |
|---|---|
| 生命周期 | `status` / `up` / `down` |
| 浏览器窗口 | `browser open <url>` / `browser click --text\|--selector` / `browser scroll --to\|--pixels` / `browser read` |
| 标签页 | `tab open <url>` / `tab switch <n>` / `tab close <n>` |
| 终端窗口 | `term run "<命令>"` / `term read` / `term scroll --lines <n>\|--to "<文字>"\|--to-end` |
| 图片浏览器 | `image open <本地图片路径>` |
| 鼠标 | `mouse to --ref <ref>` / `mouse drift` / `mouse click` |
| 开关程序 | `window open\|close --target term\|browser\|image` |
| 窗口 | `window min\|max\|restore\|move` / `focus term\|browser\|image` |
| 镜头 | `camera focus --ref <ref> --zoom <k>` / `camera pan` / `camera reset` / `camera up\|down` |
| 录制 | `rec start --name <n>` / `rec stop` |
| 讲解 | `say "<旁白>"` |
| 等待与观察 | `wait` / `elements` / `viewport refresh` |

`ref` 是元素地址：页面里的写 `page:"按钮文字"` 或 `page:<css选择器>`，终端里的写 `term:...`，桌面级的写 `dock:browser` / `tab:0`。用 `elements` 先看有哪些可寻址的东西，别猜。

## 什么时候用

- 要录教学视频、产品演示，画面里需要看得见鼠标移动和点击过程
- 要把一段自动化流程演成人在操作的样子
- 要复现一段操作并逐帧检查

本篇只讲舞台。真正把镜头、旁白、节奏组织成一支片子是另一件事，走 `video_pipeline_studio` 配方，工艺随它的阶段任务书下发。

## 关键约定

**装了 frago 就有虚拟桌面，不用另外装什么。** 舞台的代码（含桌面页那几个前端文件）在 `frago` 包里，跟着版本号一起分发。换一台机器，命令在、能力也在，不需要往 `~/.frago/` 下同步任何东西。

2026-09-02 之前不是这样：那时真正干活的是 `agent_os` 与 `agent_os_ui` 两个配方，住在 `~/.frago/recipes/` 下、靠手工同步，于是换台机器命令在、能力不在，而 `frago init` 会正常跑完并报告成功。如果你在别处读到"缺配方时回执写 `本机没有虚拟桌面配方`"，那是旧说法——那条回执连同它描述的那种状态一起没了。舞台起不来现在只有一种解释：舞台没跑、或者它自己说得出的某个原因（没有 tmux、broker 没就绪……），回执里写着，照着排就是。

**停了就是停了。** `down` 之后有一个守护服务**不会**把它拉回来——注册表里记的是"人想不想让它跑"，`down` 把这个意图改成了"不想"。所以看到桌面页面空着、状态是 stopped，那不是故障，是上一次有人停过它。`up` 会把意图改回来。

**指向窗口的动作自动把那扇窗口提到最前。** `browser open`、`browser click`、`tab switch`、`mouse to --ref page:...`、`camera focus` 落在页面上——这些都会先激活浏览器窗口再动作，不需要先发 `focus`。激活如实写在回执的 `effect.focus` 里。反过来，纯观察（`wait`、`term read`）不动焦点。

**关掉程序和收起窗口是两件事。** `window close --target term` 让终端离开桌面——窗口缩着淡出、dock 上那颗灯灭掉；`window min` 只是把窗口飞进 dock，程序还在跑、灯还亮着。两者在画面上刻意长得不一样，因为观众要分得出"退出了"和"收起来了"。三扇窗（term / browser / image）走的是同一条 `window open|close`，图片浏览器没有自己的关法。

**关掉不动载体。** tmux 会话照常在跑、演员标签照常在收画面、已经装进图片浏览器的那张图留着，所以 `window open` 叫回来的是原样，不是一个新开的空程序。看到窗口没了别去查会话被谁杀了——回执里的 `carrier_kept` 就是说这件事。

**指向某个程序的动作会把它重新打开。** 终端关着时 `term run` 的正确结果是终端回来并执行，不是报一句"你得先打开它"；发生了就在回执的 `effect.launched` 里写着。要拍空桌面，别发这类指令就是了——三个程序全关掉是合法状态，那时 `focus` 是 `null`，键盘输入没有接收方，`type` / `key` 会明确报错。

**终端窗口画的是一整块可回看的缓冲区，不是最后一屏。** 命令输出再长也全在里面（历史 + 当前屏），`term read --lines 200` 够得着已经滚出画面的部分，`term run` 的回执按整个缓冲区算新增行。想让**画面**回到前面那段，只有 `term scroll` 这一条路——桌面页对键鼠完全免疫，人手滚不动它，也别去 tmux 那边翻页，回看的视口在页面这一侧，两套滚动会打架。

视口默认贴着底，新输出跟着走；一旦 `term scroll` 回看过，它就停在那儿不再跟——这时 `term run` 的回执会带 `view_detached`，意思是命令照跑、缓冲区照长，但画面停在历史里，录下来那一段是白录的，补救就一句 `term scroll --to-end`。取景同理：`term:rows` / `term:match` 的行号一律以**画面上看得见的那一段**为准，文字在缓冲区里却不在画面上时会明确报错并告诉你该滚哪条。

**演员是一台无头浏览器，不是你屏幕上的窗口。** 右边那扇虚拟浏览器窗口里的画面，来自一台独立无头 **Edge**（CDP 端口 **9222**）的一个标签。它有过一段时间是驱动人日常浏览器里的一个真实标签，问题是那条路只给**前台**标签产帧——标签一被切走画面就停，于是它必须一直占着人的屏幕，而这块舞台本来就是为了不占屏幕才存在的。

登录态跟着 `~/.frago/profiles/edge/9222/` 那份 profile 走，它由 frago 从人真实的 Edge profile 播种过一次，所以舞台一起来就带着人已经登过的那批站点。要新登一个站点，得人自己去这份 profile 里登——演员是无头的，没有窗口给人当场接手；而且同一份 profile 只能有一个实例，人去登的时候舞台必须先停。

**⚠️ 舞台跑着的时候，不要执行 `frago browser -b cdp start`。** 演员就在默认的 9222 上，而 `-b cdp start` 默认会先杀掉该端口上已有的浏览器进程再起自己的。顶掉之后：新实例是一份空 profile，舞台的自愈机制会接管它的落地页，状态照报"演员活着"——命令、日志、状态三层没有一层报错，只有画面是错的，而这种错只有回看成片才发现。要独立无头实例，先 `frago desktop status` 确认舞台是 stopped。同理别在 9222 上开标签：那就是演员那台实例，你开的标签会出现在虚拟标签条里。

机位是另一台 Edge，占 **9223**，从 `camera up`（或 `rec start` 自动架机位）起存在，`rec stop` / `camera down` 把整台收走。这两个端口你都不用自己碰。

**桌面页面是只读显示器。** 它自己不产生任何操作，画面变化全部来自指令。页面断线会自行重连，重连后补发最近状态，所以录制中抖一下不会永久黑屏。标题栏上那三颗红黄绿是纯装饰，**点不了**——它们不在可寻址元素名单里，关窗口一律走 `window close`。

## 不要做

- 不要去找那个 `aos` 脚本自己跑（不管是配方目录里那份旧的，还是包里的 `python -m frago.desktop.aos`）——`frago desktop` 就是同一份实现的正式入口，回执里的提示也按这个名字写
- 不要手拼 JSON POST 到 broker 的 8770 端口
- 不要不查 `status` 就直接发指令：舞台没跑时任何指令都没有接收方，而错误信息只会告诉你连不上某个端口，不会告诉你原因
- 不要为了换焦点而手动补 `focus`，它是自动的；显式 `focus` 只在"人明确要换窗口"这个语义下用
