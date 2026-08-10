# desktop-usage

分类: 替代（MUST）

## 是什么

一块假 macOS 桌面，上面两扇窗口装的是**真东西**：左边是一个真实 tmux 会话，右边是一个真实 Chrome 标签页。整块桌面可脚本操控——鼠标移动、点击、窗口层级、镜头推拉都能下指令，所以一段自动化流程可以被演成"人在操作"的样子录下来。

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
| 终端窗口 | `term run "<命令>"` / `term read` |
| 图片浏览器 | `image open <本地图片路径>` |
| 鼠标 | `mouse to --ref <ref>` / `mouse drift` / `mouse click` |
| 开关程序 | `window open\|close --target term\|browser\|image` |
| 窗口 | `window min\|max\|restore\|move` / `focus term\|browser\|image` |
| 镜头 | `camera focus --ref <ref> --zoom <k>` / `camera pan` / `camera reset` / `camera up\|down` |
| 录制 | `rec start --name <n>` / `rec stop` |
| 讲解 | `say "<旁白>"` / `overlay` |
| 等待与观察 | `wait` / `elements` / `viewport refresh` |

`ref` 是元素地址：页面里的写 `page:"按钮文字"` 或 `page:<css选择器>`，终端里的写 `term:...`，桌面级的写 `dock:browser` / `tab:0`。用 `elements` 先看有哪些可寻址的东西，别猜。

## 什么时候用

- 要录教学视频、产品演示，画面里需要看得见鼠标移动和点击过程
- 要把一段自动化流程演成人在操作的样子
- 要复现一段操作并逐帧检查

本篇只讲舞台。真正把镜头、旁白、节奏组织成一支片子是另一件事，走 `video_pipeline_studio` 配方，工艺随它的阶段任务书下发。

## 关键约定

**这条命令依赖本机装了配方，没有配方就完全不可用。** `frago desktop` 随 frago 包分发，但它驱动的舞台不随包走——真正干活的 `agent_os` 与 `agent_os_ui` 两个配方住在 `~/.frago/recipes/` 下。所以换一台机器，命令在、能力可能不在，而且 `frago init` **装不来**它们（包里只带另外两个配方，init 会正常跑完并报告成功，然后这条命令依然找不到舞台）。

缺配方时命令会明确说出来——回执写 `error: 本机没有虚拟桌面配方`，并列出缺哪两份。看到这条别去排查端口或进程，那是另一回事：配方不在，连"舞台没在跑"都还谈不上。

**停了就是停了。** `down` 之后有一个守护服务**不会**把它拉回来——注册表里记的是"人想不想让它跑"，`down` 把这个意图改成了"不想"。所以看到桌面页面空着、状态是 stopped，那不是故障，是上一次有人停过它。`up` 会把意图改回来。

**指向窗口的动作自动把那扇窗口提到最前。** `browser open`、`browser click`、`tab switch`、`mouse to --ref page:...`、`camera focus` 落在页面上——这些都会先激活浏览器窗口再动作，不需要先发 `focus`。激活如实写在回执的 `effect.focus` 里。反过来，纯观察（`wait`、`term read`）不动焦点。

**关掉程序和收起窗口是两件事。** `window close --target term` 让终端离开桌面——窗口缩着淡出、dock 上那颗灯灭掉；`window min` 只是把窗口飞进 dock，程序还在跑、灯还亮着。两者在画面上刻意长得不一样，因为观众要分得出"退出了"和"收起来了"。三扇窗（term / browser / image）走的是同一条 `window open|close`，图片浏览器没有自己的关法。

**关掉不动载体。** tmux 会话照常在跑、演员标签照常在收画面、已经装进图片浏览器的那张图留着，所以 `window open` 叫回来的是原样，不是一个新开的空程序。看到窗口没了别去查会话被谁杀了——回执里的 `carrier_kept` 就是说这件事。

**指向某个程序的动作会把它重新打开。** 终端关着时 `term run` 的正确结果是终端回来并执行，不是报一句"你得先打开它"；发生了就在回执的 `effect.launched` 里写着。要拍空桌面，别发这类指令就是了——三个程序全关掉是合法状态，那时 `focus` 是 `null`，键盘输入没有接收方，`type` / `key` 会明确报错。

**桌面页面是只读显示器。** 它自己不产生任何操作，画面变化全部来自指令。页面断线会自行重连，重连后补发最近状态，所以录制中抖一下不会永久黑屏。标题栏上那三颗红黄绿是纯装饰，**点不了**——它们不在可寻址元素名单里，关窗口一律走 `window close`。

## 不要做

- 不要直接跑配方目录里的 `aos` 脚本——`frago desktop` 是同一份实现的正式入口，回执里的提示也按这个名字写
- 不要手拼 JSON POST 到 broker 的 8770 端口
- 不要不查 `status` 就直接发指令：舞台没跑时任何指令都没有接收方，而错误信息只会告诉你连不上某个端口，不会告诉你原因
- 不要为了换焦点而手动补 `focus`，它是自动的；显式 `focus` 只在"人明确要换窗口"这个语义下用
