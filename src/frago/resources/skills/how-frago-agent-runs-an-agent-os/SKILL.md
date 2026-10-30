---
name: how-frago-agent-runs-an-agent-os
description: 指导 agent 作为「主操作员」驱动 frago desktop（agent_os 虚拟桌面），并拉起常驻的「主持人」（驻场解说与盯面板）与「参谋」（场外协商）组成三角色协同：一边推进事务，一边在虚拟桌面上实时英文语音讲解、操纵窗口与鼠标指针、响应桌面右下角对话面板的人类输入，或同步录制带英文配音的演示视频（how frago agent runs an agent os）。当需要在虚拟桌面上边干活边讲解演示、遥控 frago-stage 终端会话、或录制桌面操作视频时使用。
---

# How Frago Agent Runs an Agent OS

观众（或录制机位）只看得到虚拟桌面画面，看不到你所在的主控会话文字。你在这场演出里是**主操作员**：一边推进手头的事务（自己执行或派后台 worker 在桌面终端里跑），一边把思考与进展演出来。**旁白是「我」**——你就是那个接活干活的人，NEVER 把自己讲成监工。

## 三角色协同架构

一场演出由三个角色分工完成，三者都是 agent 会话，各占一条线：

| 角色 | 是谁 | 独占什么 | NEVER 碰什么 |
|---|---|---|---|
| **主操作员**（Operator，主线会话） | 当前接活、并绑定桌面右下角对话面板（`?userInput=true&session=<会话编号>`）的那个主控会话，就是你 | 虚拟桌面的**键鼠与程序操作权**：`frago desktop term run`、`browser open/click/scroll`、`image open`、`video open/play`、`window`、`mouse to/drift/click`；以及工作目录下的**共享协商账本 `ledger.md`** | 不自己抢麦克风（有主持人时） |
| **参谋**（Advisor，场外协商常驻会话） | 你用 `frago agent start claude --name <参谋名>` 拉起的常驻会话 | 只读代码与日志；把挑刺、备选方案、根因推演写进 `ledger.md` 的「参谋挑刺与备选方案」栏 | **零舞台触碰权**：NEVER 调任何 `frago desktop` 命令，NEVER 改业务文件 |
| **主持人**（Presenter，驻场解说与盯面板常驻会话） | 你拉起舞台后，用 `frago agent start claude --name <主持人名>` 拉起的驻场会话 | **声画导播权**：`say --speak`、`voice synth`、`strap show/hide`、`slide open/close`、`camera focus/pan/reset`、`mouse drift`（只在主操作员未动鼠标的等待期做呼吸感微移）；以及**静默读屏**（`--observe`） | NEVER 执行 `term run`、`browser open/click`、`window close` |

**工具载体绝不是代理角色。** 虚拟桌面上的 `frago-stage` 终端、9222 演员浏览器、图片查看器、视频播放器、虚拟鼠标，统统是**虚拟桌面这台电脑上的被操作工具**，绝不是「主操作员」。「主操作员」指的是驱动这些工具的 agent 会话，两者 NEVER 混称。

## 适用场景

1. **边执行事务边为用户讲解演示（默认）**：观众打开桌面页实时观看，一边推进任务，一边用连续语音、字条、全屏讲稿和窗口焦点向观众讲解正在发生什么。只要用户原话没有明示要求「录视频 / 录屏 / 录成片」，一律按本场景直接现场开演，不开启录制。
2. **后台 worker + 人类输入行协同**：耗时任务交由后台 worker 借住在桌面终端（`--tmux-target frago-stage`）里执行，主操作员在外围轮询终端与产物，随时把观众在桌面右下角对话面板（输入行）敲下的补充要求转达给 worker。
3. **同步录制演示视频（仅在用户明示要求录屏时开启）**：当用户明确要求把演示录成视频交付时，开启舞台机位（`rec start`）把画面与英文语音合成为可交付的 MP4 视频。

## 何时用三角色，何时退回单人

- **默认走三角色**：复杂任务、排障、开放式构建、需要长时间推演或反复权衡的活。参谋补上单 agent 缺的思考深度与广度，主持人把幕后协商翻译成观众听得懂的解说，主操作员专心把事做成。
- **可以退回单人一拍一动**：仅限 **1–2 分钟纯静态脚本回放演示**——没有真实排障、没有方案权衡、画面按写好的幕脚本走一遍就结束。这时不必拉主持人也不必拉参谋，主操作员自己发声即可（见「一拍一动同轨剧本」）。只要任务里出现「要先想清楚怎么做」，就回三角色。

## 主操作员标准开场五步

**第一步：检查并拉起舞台，立刻发声。** 先 `frago desktop status`；没在跑就 `frago desktop up`。舞台一起来，MUST 先挂首帧字条并开口说 2–3 句开场白（约 15–25 秒音频）——这两条是你在这个舞台上做的第一件事，不许先忙别的，也不许让 `status` 回执里那些 WARN 的书面回应挡在画面之前（书面回应照写，但 MUST 在同一回合里紧接着发出首帧）。

**第二步：建共享协商账本 `ledger.md`。** 在工作目录下建本场协同目录，写一份 `ledger.md`，四节固定：

```text
# 任务与追加需求        ← 原始任务 + 人类从面板追加的每一条（原话照抄）
# 参谋挑刺与备选方案     ← 参谋写这里
# 主操拍板与当前动作     ← 主操作员每推进一个关键动作就更新这一节
# 阶段进展与产物        ← 到哪一步了、产出了什么（路径写绝对路径）
```

账本是三个角色唯一的共享事实源，也是主持人播报的素材来源。

**第三步：拉起常驻主持人，交接声画与面板。** 把麦克风、字条、镜头，以及**盯导演对话面板做秒级应答**的职责正式交给主持人：以 `presenter-prompt.md` 为模板，填入你自己的 `session_id` 与 `ledger.md` 的绝对路径，用 `frago agent start claude --name <主持人名>` 后台拉起驻场（`run_in_background: true`）。交接之后，主操作员不再自己写台词合成配音。

**第四步：按需拉起参谋。** 以 `advisor-prompt.md` 为模板，用 `frago agent start claude --name <参谋名>` 拉起。遇到方案权衡、架构设计或报错排障时，先把问题写进 `ledger.md`，等参谋的挑刺与备选方案落到「参谋挑刺与备选方案」栏，再在「主操拍板与当前动作」里拍板。

**第五步：专心干活，边干边记账。** 专心调用 `frago desktop term run`、`browser open/click/scroll`、`image open`、`video open/play`、`mouse to` 在虚拟桌面上把事情做成；每推进一个关键动作，同步更新 `ledger.md` 的「主操拍板与当前动作」。任务收尾时通知主持人播报终幕、按需 `rec stop`，并用 `frago agent stop <主持人名>` / `frago agent stop <参谋名>` 回收两个常驻会话。

## 舞台铁律

1. **舞台由主操作员自己拉起，起了就不许再动它。** 接到活先跑 `frago desktop status`；没在跑就自己跑 `frago desktop up`（这一条是允许的，也是必须的），等它就绪再往下走。此后 NEVER 执行 `frago desktop down`、`frago server restart`、`frago browser -b cdp start`、`tmux kill-session`——桌面必须一直活着，它是人唯一的窗口（演员浏览器就住在 9222 端口上，`browser -b cdp start` 会把演员连人带登录态顶掉）。
2. **后台 worker 必须跑在桌面终端里，人才看得见。** 派长耗时子任务时，用 `--tmux-target frago-stage` 让 worker 借住在虚拟桌面终端盯着的那个 tmux 会话里跑，且 MUST 用 Bash 工具 `run_in_background: true` 起；跑完 harness 会通知你。NEVER 从外面套 `timeout` 或 `kill`；NEVER 自己在桌面终端里手敲交互式 `claude`。
3. **声画同轨，严禁把「排语音」和「跑操作」拆成两张皮。** 桌面上一直有话说，而且**嘴里正在说的事必须就是屏幕上此刻正在发生的事**。做前台操作演示时，MUST 把每一句 `say --speak --async`、鼠标移动 `mouse to`、窗口动作和匹配语音时长的 `pause --ms` 写在同一份「一拍一动（Beat-by-Beat）」幕脚本里（做法见「一拍一动同轨剧本」一节）——NEVER 先往语音队列塞十几句异步台词，再单独跑一个没有停顿的脚本狂切窗口。NEVER 向人解释底层代码或琐碎过程细节——说他画面上看得见的东西。
4. **先开口，再按幕小步接力（严禁开场后冷场准备几分钟）。** **每次台下准备的时间决不能超过台上正在播放的语音剩余时长（20 秒红线）**——开场白播放期间只准备第一幕（3–5 拍，约 30 秒），第一幕立刻上台开演；第一幕演出期间再准备第二幕。NEVER 开场说一两句后就躲在后台花两三分钟翻源码、画图、一口气合成十几句音频，把观众晾在静音静止的桌面上；反过来，也 NEVER 等所有操作全做完了，才对着一动不动的画面干念一分多钟的事后总结。
5. **舞台不是试验场，严禁在台上裸跑无停顿脚本或当众试错。** 拿不准有哪些可点击元素先在台下跑 `frago desktop elements`，拿不准窗口状态先查 `frago desktop status`。上台执行的每一拍动作都必须有语音预告、指针引导和 `pause --ms` 视觉停留——NEVER 在舞台上跑 `for` 循环或无停顿的探测脚本（如 10 秒内连续闪切十几扇窗），也 NEVER 把拿不准语法的命令直接打在舞台上报错重来。
6. **需要人处理时只在桌面上当面喊话，严禁发工作台交互卡。** 观众守在虚拟桌面页（`/app/agent_os`）看画面，看不到你所在的主控会话页面；在主控会话里调 `frago app ask` 或写 `answer-needed-by-human` 交互卡，桌面页上一字不显，还会当场阻断你自己的运行。遇到认证墙或必须由人处理的硬阻塞（如 worker 退出码 2）时，一律用 `frago desktop say "需要你处理：<原因>"` 在桌面与右下角对话框里喊话。
7. **开放式题目默认直接现场开演，严禁开演前停下反问。** 用户没提录屏就默认只做现场演示（不调 `rec start`），没指定时长或深度就由你直接定下合理的分幕与篇幅（3–5 分钟核心脉络）立刻上台开演——NEVER 在开场前停下来追问「要不要录成 MP4 成片」「按几分钟 / 什么深度讲」。
8. **窗口与键鼠只有主操作员能动，读屏只有主持人能静默读。** 主操作员是唯一碰 `term run` / `browser open/click` / `window` / `mouse` 的角色；主持人要观察画面，只能走静默读屏 `--observe`（见下节），绝不抢夺或改变主操作员当前的窗口置顶焦点。

## 开口与解说

人只看桌面，你自己的会话他看不到。所以「我在做什么」必须由桌面上的动作说出来。

**两条通道别混。** 对人说，用 `say`（一句句流过的旁白，加 `--speak` 才开口）、`strap`（挂着的字条）、`slide`（整屏讲稿）、`camera`（推近）、`image`、`video`、`pause`；对终端里那个会话说话才用 `focus term` → `type` → `key Enter`。

**首帧。** 舞台一起来，先 `strap show "接活：<一句话>" --style chip` 挂着，紧接一句 `say` 说明你打算怎么干。这两条 MUST 是主操作员在这个舞台上做的第一件事——`status` 回执里那些 WARN 的书面回应写在你自己的会话里，但**必须在写出书面回应的同一个回合里紧接着调用 Bash 发出首帧 `strap show` 与 `say`**，NEVER 只输出文字回应就结束回合（`end_turn`），一旦没带工具调用就结束回合，整场演出就会卡死在起跑线上。

**旁白是「我」。** 你就是那个接活干活的人，NEVER 把自己讲成监工。旁白的主语 MUST 是「我」，NEVER 把终端里那个会话当主语——「它刚把参考资料翻了一遍」是转述，人听到的是一个旁观者在解说别人；「我刚把参考资料翻了一遍，想弄清接口的真实规矩」才是员工在讲自己手上的活。同一个事实，两种讲法，人只信后一种。默认带 --speak 真开口：只说字幕不出声，人一低头就断了。

**手要一直动（注意 `mouse to` 是位置参数，不带 `--ref`）。** 桌面上的指针 MUST 跟着旁白走：每做一拍操作前，先用指针把观众视线带过去——指到画面里具体的东西上用 **`frago desktop mouse to <元素>`**（如 `mouse to dock:browser`、`mouse to page:"确认提交"`，先跑 `elements` 拿名字；**注意：`mouse to` 的目标是位置参数，严禁写成 `mouse to --ref <元素>`，只有镜头命令 `camera focus --ref <元素>` 才带 `--ref`**），只是表示"我在想 / 在等"就用 `frago desktop mouse drift --x <坐标> --y <坐标>`。等后台任务的那段时间 NEVER 只发 `term read` 干等，那一帧帧画面在滚、指针却钉死在原地，人一眼就看出屏幕里没有活人。

**注意力在哪扇窗，哪扇窗自动置顶（严禁为了换层级手动补 `focus`）。** 舞台自带 MRU（最近使用顺序）窗口层级栈：任何指向某扇窗口的动作——`term run` / `term read` / `term scroll` / `term fontsize`、`browser open` / `browser click` / `browser scroll` / `tab switch`、`image open`、`video open` / `video play`、`window move|max|restore`、以及落在页面或终端上的 `mouse to` / `camera focus`——**都会自动把目标窗口提到最顶层**，关闭或最小化当前窗口时焦点也会自动退回上一扇看过的窗口。因此：

- **做操作演示时 NEVER 手动调用 `focus <窗口>`**——直接执行那个软件的业务动作（如 `browser open`、`image open`、`video play`、`term run`），让它因为被你使用而自然升到最前，并在动作后给足 `pause --ms` 让观众看清它处于顶层。
- **NEVER 刚打开图片/浏览器/视频还没停留展示，就立刻调 `focus term` 把它盖住**——每一扇切出来的窗口至少要在顶层停留完这一拍的语音时长（通常 4–8 秒）。只有在「后台 worker 正在终端持续输出、需要切回终端盯进度」的场景下，才在展示完其他窗口后用 `term read` 或 `focus term` 回到终端。
- **多角色同场时，主持人读屏必须静默。** `term read` / `browser read` / `elements` 这三个动词带 `--observe` 时只取值、**不激活目标窗口**，焦点一个字节都不动：`frago desktop term read --lines 40 --observe`、`frago desktop browser read --observe`、`frago desktop elements --observe`。主持人轮询画面走这一条，主操作员正在展示的那扇窗就不会被顶掉。

**桌面布局与常驻进度板。** 终端字号用 `frago desktop term fontsize 18`（纯录制终端可给到 `26`）。**桌上永远至少两扇窗**——一扇终端，另一扇是会变化的东西（浏览器页面、进度板图片、讲稿或视频播放器）。只有明确不需要浏览器页面的纯后端任务，才允许在开场布局那一处执行一次 `frago desktop window close --target browser`；**window close 整场只允许用在这一处**，别的地方 NEVER 随便关窗——窗口的存亡本身就是给人看的信息。可在图片窗口里挂一张常驻的「进度板」PNG（从磁盘现读真实进度数据画图，NEVER 凭记忆手填），第一次画完用 `frago desktop window move --target image --x 1320 --y 60 --w 560 --h 490` 把板子摆好。

**说到点子上。** 细节不要走字条（它上限 60 字）：一页 `slide` 讲一件事，字要大——人隔着屏幕看；讲完 MUST `slide close`，铺着的时候 `mouse` / `click` / `camera` 会被拒绝。要看页面或窗口里某个具体的东西，先 `frago desktop elements` 拿到可寻址的名字，再 `camera focus --ref <那个名字>` 推近，看完 `camera reset`——NEVER 猜 `ref`（终端里的文字行一律不推镜，靠调大字号和 `term scroll` 展示，回看过必须 `term scroll --to-end` 滚回底部）。

**台词一律用英文写。** 语音层只说英文（`frago.desktop.voice` 里两处开关锁着）：正文里出现中日文字符，合成当场被拒，回执就是 `say 失败 — ValueError: 语音层只说英文…`，那句一个字也念不出来。**被拒会把同一条命令里排着的余下步骤一起带停**（回执里 `not_reached`）——幕脚本里混进一句中文，那一幕后面的话连同画面动作一条都不发。所以每句台词写进幕脚本前都要过一次 `voice synth`：它先跑同一道语言关并返回准确的 `duration_ms`，验过了再写进幕脚本。`say` 的正文同时就是字幕，所以写成英文，声音与字幕一起是英文。

## 一拍一动（Beat-by-Beat）同轨剧本

演示失败最常见的病根，是**把「排音频队列」和「跑窗口操作」拆成两个独立文件**：先往语音队列里塞十几句 `--speak --async`（要念 90 秒），紧接着跑一个没有 `pause` 的操作脚本（10 秒内把所有窗口闪切一遍）。结果观众耳朵里还在听开场铺垫，屏幕上的操作早就闪完停死了；等语音念到具体步骤时，画面反而一动不动。

要让声音与操作真正同轨，MUST 先区分当前处于哪一种场景：

### 模式 A：前台交互演示（操作软件、切换窗口、点击页面、展示图表/视频）—— 必须走「一拍一动同轨幕脚本」

只要你是在向观众演示桌面操作，**声音和动作就必须绑在同一个幕脚本文件（`acts/actN.txt`）里，以「一拍（Beat）」为原子单位交织编写，绝对不允许单独建纯语音队列文件或单独跑无停顿的操作脚本！**

1. **什么是「一拍（Beat）」—— 四步同轨公式**：
   每一拍只做一件事、说透一句话（英文 15–35 词，约 4–9 秒），在幕脚本里严格按以下 4 步组织：
   - **第 1 步（字条 + 开口预告）**：`strap show "<步骤说明>" --style chip` + `say "<告诉观众这一拍要操控哪个软件、看什么变化>" --speak --async --voice en-US-AndrewMultilingualNeural`（`--async` 让声音立即起播，不阻塞紧随其后的窗口与指针动作）。
   - **第 2 步（触发窗口/软件动作，自动开窗并置顶）**：执行本拍真正的业务指令（如 `term run "<命令>"`、`browser open <url>`、`image open <图片>`、`video open <视频>` + `video play`）。该动作会自动把目标窗口打开并提到最顶层（`z_order` 首位）。
   - **第 3 步（指针跟随视线）**：用 `mouse to win:term` / `mouse to win:browser`（或 `mouse drift --x <x> --y <y>`，若已用 `elements` 确认了具体元素名则用 `mouse to <元素>`，**切记不带 `--ref`**）把鼠标指针带到当前置顶窗口上。**注意：切勿在窗口尚未打开或未跑 `elements` 确认前盲写 `mouse to dock:...` 或 `mouse to win:image`，因为批处理中一旦某个 `ref` 不存在报 `RefError`，同一幕余下步骤会被全部中止（`not_reached`）。**
   - **第 4 步（呼吸与留白，决不可省！）**：`pause --ms <本句 duration_ms + 800~1500ms>`。**这一行保证了：在这一拍的话还没讲完、观众还没看清当前置顶窗口之前，绝不会跳进下一拍！**
2. **按幕小步接力（一幕 3–5 拍，约 25–45 秒）**：
   - 不要试图在开演前把整场 15 句台词全部写完合成完（那会让桌面冷场好几分钟）。
   - **标准接力节奏**：
     1. 写出当前这一幕的 3–5 句英文台词（每句 5–10 秒）。
     2. 先跑 `voice synth` 预合成这 3–5 句，既做英文校验，又拿到每句准确的 `duration_ms`：

        ```text
        frago desktop voice synth "<Beat 1 台词>" --voice en-US-AndrewMultilingualNeural
        ```

     3. 把每句的 `duration_ms + 1000` 填入对应拍末尾的 `pause --ms`，写成 `acts/act1.txt`。
     4. 用 `frago desktop - < acts/act1.txt` 一条命令整幕演完（脚本会按每拍的 `pause --ms` 稳稳走完 30 秒，声画严丝合缝）。
3. **标准「一拍一动」幕脚本样例（`acts/act_demo.txt`）**：

   ```text
   # 每一拍 = 挂字条 + 开口解说(--async) + 软件动作(自动开窗并置顶) + 指针跟随 + 匹配语音时长的停顿(pause --ms)
   # Beat 1: 操控终端（假设 voice synth 测得本句 duration_ms = 5184）
   strap show "1/4 终端：执行命令自动置顶" --style chip
   say "First, I will run a command in the terminal, and watch how the terminal window rises to the front on its own." --speak --async --voice en-US-AndrewMultilingualNeural
   term run "echo 'Step 1: Terminal is active at the top of the window stack'"
   mouse to win:term
   pause --ms 6200

   # Beat 2: 操控浏览器（假设 duration_ms = 5496）
   strap show "2/4 浏览器：打开页面自动置顶" --style chip
   say "Next, I move to the browser and open a page. Touching the browser immediately brings it above the terminal." --speak --async --voice en-US-AndrewMultilingualNeural
   browser open http://127.0.0.1:8093/app/agent_os
   mouse to win:browser
   pause --ms 6500
   wait --speech all
   ```
4. **节奏底线**：
   - 任意两次切换窗口或需要注意的画面变化之间，留白**不少于 4–6 秒**（即一句完整解说 + 约 1 秒视觉停留），严禁出现 1 秒切一扇窗的走马灯闪切。
   - 全屏讲稿幕（`slide open`）同理：打开讲稿后 pause 1.5 秒 → 逐句 `say --speak --async` 配对应时长的 `pause --ms` → 讲完 `slide close`。

### 模式 B：后台长任务等待（Worker 在终端持续跑数/编译，几分钟内无窗口切换）—— 才用「并行垫音层 + 插播层」

**只有**当你在桌面终端里起了后台长任务（`--tmux-target frago-stage`），接下来几分钟画面都停留在终端上看它滚动输出时，才使用「批量排入并行垫音 + 变化时 `--interject` 插播」。**说话是一条队列，不是一次次的临时起意**：你的回合之间有思考时间，那段思考在桌面上就是静音——想到一句说一句，人听到的必然是「憋一阵、说一句」。所以顺序反过来：先写话，再排音频。

1. **先写话。** 动手之前先把这一场要说的话整段写出来，落到工作目录下的 `script.md`，一行一句。一个阶段一批，写完再进下一步。
2. **切短句。** 一句 5–14 秒的量（英文约 15–40 个词）。长了切成两句——短句好排队、好插、好对齐。
3. **逐句合成。** 每句过一次 `frago desktop voice synth "<这一句>" --voice en-US-AndrewMultilingualNeural`，回执里的 `duration_ms` 抄下来。嗓子就用 Andrew，`say` 与 `voice synth` 都带上同一个 `--voice`，两次不一致缓存对不上，演的时候又得重合成一遍。
4. **排队放。** 一批话写进文件、一条命令整批发（见下「一次排一长串」）；单句只在插播时发。两种写法都是 `frago desktop say "<这一句>" --speak --async --voice en-US-AndrewMultilingualNeural`。`--async` 是必须的：它立刻返回，下一条马上跟上，几句就接成一条不断的声。要等某一句讲完再往下走时，用 `frago desktop wait --speech <编号>`（编号在回执里）或 `wait --speech all`。
5. **边放边续。** 队列快空了（大约还剩一句）就回到第 1 步续下一批。**NEVER 让它空**——空一次，人听到的就是那十几秒 gap。续批也是写文件、整批发，别一句一句敲。

**两类话，一层一层放。**

- **并行层（随口聊的那种）**：介绍思路、讲讲这条路为什么这么走、顺带一点背景知识，像跟正在看屏幕的人闲聊。可以提前写好一大批排着，讲得慢一点也没关系，被后面的变化盖掉也不可惜。终端里十几分钟没动静时，全靠这一层撑着。
- **插播层（此刻在做什么、为什么）**：画面一变就要说，晚一拍就没意义。变化来的话**插播**一句
  （`--interject`）：

      frago desktop say "<这一句>" --speak --async --interject --voice en-US-AndrewMultilingualNeural

  它掐掉正在说的那一句、让这一句**立刻**说，**排着的留着**接着说——画面变了就说，说完原来的接着走。NEVER 用 `--interrupt`（也 NEVER 用 `voice stop`）：那两条把排着的整队丢掉，声音断成一片空白，正好是这一节要防的事。
- 两层的比例大约是「并行层常年不停、插播层有事才来」。插播来了就紧跟着说，说完接着回并行层。

**一次排一长串：一条命令排一批。** `frago desktop - < <文件>` 是把文件里的行**一次读完、整批执行**的（不是一行一条命令）。所以把一批话写进文件、一条命令发出去，就能在**一个回合**里排进十几句——**回合之间的思考只静音一次，不是每句一次**。文件里就是一行一条指令（与幕脚本同一种写法，空行与 `#` 开头的行会被跳过）：

```text
# 并行层
say "..." --speak --async --voice en-US-AndrewMultilingualNeural
say "..." --speak --async --voice en-US-AndrewMultilingualNeural
```

**一批多长：10–20 句（约 1–2 分钟音频），别排到十分钟。** 两头都有代价：批太短 → 续批的回合多，gap 就多；批太长 → **转向变慢**：队列里压着十分钟，人从输入行提了新要求、或方向要改时，那十分钟还在照旧讲原来的打算。1–2 分钟的批够把续批的思考藏在声音底下，又能在两分钟内掉头。边放边写下一批，NEVER 让队列空。

**排好的那部分写成幕。** 它是这场演出的主线，不是空档里的加分项：把一批话连同对应的画面动作一起写成幕脚本。一幕一个文件，一行一条桌面指令（不带 `frago desktop` 前缀），用 `frago desktop - < <文件>` 按行执行；节奏用 `pause --ms` 写进脚本里。幕脚本与讲稿放在工作目录的 `acts/` 与 `slides/` 下，讲稿一页只讲一件事、字要大。

**看后台终端的节奏照旧**：每 5–10 秒 `frago desktop term read --lines 40` 看一次它到了哪，有阶段变化就换字条：`strap show "<n>/<总> <阶段> 已花 <分钟>" --style chip`——人关心的是「到哪一步、还要多久」，不是一个抽象的阶段名。主持人盯屏时用 `frago desktop term read --lines 40 --observe`，静默读、不顶窗。

## 人会跟你说话（桌面右下角的对话面板 / 输入行）

桌面右下角常驻客服式对话入口（人类输入行）：当桌面页地址带 `?userInput=true&session=<会话编号>` 时，右下角对话交互面板默认展开（可收起为右下角胶囊图标）；不带参数时收起为右下角胶囊图标（录制机位自动隐藏）。人看着桌面，随时能打字给你：他打的字**不进桌面终端**，而是作为**新消息**排进地址里那场主控会话（主操作员）的队列。

1. **收到人追加的消息后立刻响应**：
   - **三角色模式下由主持人做秒级口头确认**：主持人轮询主操作员的会话记录（`GET /api/workbench/sessions/<主操作员session_id>/records?after=<last_seq>&limit=50`，或 `frago session show <主操作员session_id>`），一旦发现新的观众消息，立刻 `frago desktop say "Received, passing it on: <英文简短摘要>" --speak --async --interject --voice en-US-AndrewMultilingualNeural`（同时触发面板气泡回显），并把新需求记进 `ledger.md` 的「任务与追加需求」栏提醒主操作员。
   - **单人模式下由主操作员自己确认**：`frago desktop say "Received, passing it on: <short summary>" --speak --async --interject --voice en-US-AndrewMultilingualNeural`（纯字幕可用中文 `frago desktop say "收到，已转达：<不超过 20 字的摘要>"`）。
   - 后台 worker 还在跑时，把原话排进终端里 worker 的输入队列：

         frago desktop focus term
         frago desktop type "<原话>"
         sleep 2
         frago desktop key Enter

   - 后台 worker 已经结束时，把原话追加进任务需求文件末尾，重新起一轮后台 worker。
2. **宽泛题目自己拍板开演，只有撞上硬阻塞才在桌面上喊话**：
   像「讲解太阳系」「演示某功能」这类开放式要求，由你直接定下分幕与形式立刻开演，别停下来让人做选择题。只有中途撞上没有人类输入就走不下去的硬阻塞（如登录验证码、缺失密钥、worker 退出码 2）时，才直接说一句 `say "I need your input — please reply in the chat box at the bottom-right corner of the screen." --speak --async --interject --voice en-US-AndrewMultilingualNeural`（或中文纯字幕 `frago desktop say "需要你处理：<原因>"`），且 NEVER 使用 `frago app ask` 或 `answer-needed-by-human` 卡片。
3. **窗口焦点跟随当前讲解对象（不盲目锁死终端）**：
   正在讲解或操控哪个软件，就让哪个软件的窗口随着业务指令自然置顶并停留展示（4–8 秒以上），NEVER 为了换焦点手动补 `focus`，也 NEVER 刚打开浏览器/图片/视频还没让观众看清就切回终端。只有当后台 worker 正在终端里持续跑任务、需要带观众回看终端实时输出时，才用 `term read`（自动激活终端）或 `focus term` 把终端请回最前。只在有事发生时切换画面，NEVER 为了"看看"反复空切。

## 同步录制视频（需要交付录屏成片时）

当任务要求把演示或执行过程录制成视频（或边讲解边录屏）时，叠加以下录制规矩：

1. **开录前准备干净现场**：开窗、关掉多余程序、登录、初始导航全部在开录前做完；要铺 `slide` 的，先架机位或开录再 `slide open`，让成片从第一帧起完整。
2. **直接 `rec start`，不要在有人开着桌面页时单独 `camera up`**：
   开录门禁要求「本实例有且仅有一块主荧幕 + tmux 会话存在」。如果没人开桌面页，`frago desktop rec start --name <片名>` 会自己架起 9223 机位并通过门禁；如果已经有人开着桌面页，再起机位会变成两块荧幕导致 409 门禁拒绝（排查时用 `camera down` 再 `status`）。
3. **防休眠塌帧**：
   macOS 一旦进入休眠（Sleep），CDP 停止产帧但命令不报错，几十分钟的动线会被压成几秒。整段录制脚本外层用 `caffeinate -dimsu` 包裹，并确认没有合盖；停录后用 `pmset -g log` 检查录制期间是否有 `Entering Sleep` / `DarkWake`。
4. **收尾必保 `rec stop` 完全返回**：
   把 `frago desktop rec stop` 放进 `finally` / `trap` 里，先 `wait --speech all` 等语音说完再停录。停录会把录制期间每一句 `say --speak` 的音频按开口时刻（含 `--interject` 的 `cut_ms` 截断位置）贴成音轨封进 MP4。长片编码耗时数分钟，**必须等 `rec stop` 完全返回后**再用 `ffprobe -count_frames` 核验帧数与时长，并抽查音频片段与 `<片名>-voice/` 副本的相似度（正常接近 1.000，叠音约 0.70），防止半途读取报 `moov atom not found` 或漏检叠音。
5. **收尾回收常驻会话**：终幕播完、`rec stop` 返回后，用 `frago agent stop <主持人名>` / `frago agent stop <参谋名>` 收走两个常驻角色；舞台本身保持活着（NEVER `frago desktop down`）。
