# desktop-usage

分类: 替代（MUST）

## 是什么

一块假 macOS 桌面，上面两扇窗口装的是**真东西**：左边是一个真实 tmux 会话，右边是一个真实 Chrome 标签页。整块桌面可脚本操控——鼠标移动、点击、窗口层级、镜头推拉都能下指令，所以一段自动化流程可以被演成"人在操作"的样子录下来。

入口是 `{{frago_launcher}} desktop`，与 `{{frago_launcher}} browser` 同级：一个驱动真实浏览器，一个驱动这块舞台。

## 怎么用

**标准路径三步，顺序不能省。** 和用浏览器前先 `browser status` 是同一个道理：

```
{{frago_launcher}} desktop status                       # 舞台在跑吗
{{frago_launcher}} desktop up                           # 不在就拉起来
{{frago_launcher}} desktop browser open https://...     # 然后才是干活
```

`status` 回执里 `ok: false` 且 `error` 写着"没在运行"，就是该 `up` 的信号，`hint` 里有现成的命令可以照抄。

动词地图（裸跑 `{{frago_launcher}} desktop` 也会列出来）：

| 资源 | 动词 |
|---|---|
| 生命周期 | `status` / `up` / `down` |
| 浏览器窗口 | `browser open <url>` / `browser click --text\|--selector` / `browser scroll --to\|--pixels` / `browser read` |
| 标签页 | `tab open <url>` / `tab switch <n>` / `tab close <n>` |
| 终端窗口 | `term run "<命令>"` / `term read` |
| 鼠标 | `mouse to --ref <ref>` / `mouse drift` / `mouse click` |
| 窗口 | `window min\|max\|restore\|move` / `focus term\|browser` |
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

**停了就是停了。** `down` 之后有一个守护服务**不会**把它拉回来——注册表里记的是"人想不想让它跑"，`down` 把这个意图改成了"不想"。所以看到桌面页面空着、状态是 stopped，那不是故障，是上一次有人停过它。`up` 会把意图改回来。

**指向窗口的动作自动把那扇窗口提到最前。** `browser open`、`browser click`、`tab switch`、`mouse to --ref page:...`、`camera focus` 落在页面上——这些都会先激活浏览器窗口再动作，不需要先发 `focus`。激活如实写在回执的 `effect.focus` 里。反过来，纯观察（`wait`、`term read`）不动焦点。

**桌面页面是只读显示器。** 它自己不产生任何操作，画面变化全部来自指令。页面断线会自行重连，重连后补发最近状态，所以录制中抖一下不会永久黑屏。

## 不要做

- 不要直接跑配方目录里的 `aos` 脚本——`{{frago_launcher}} desktop` 是同一份实现的正式入口，回执里的提示也按这个名字写
- 不要手拼 JSON POST 到 broker 的 8770 端口
- 不要不查 `status` 就直接发指令：舞台没跑时任何指令都没有接收方，而错误信息只会告诉你连不上某个端口，不会告诉你原因
- 不要为了换焦点而手动补 `focus`，它是自动的；显式 `focus` 只在"人明确要换窗口"这个语义下用
