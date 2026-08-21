---
name: whitebox_scene_studio
type: workflow
runtime: python
version: "0.6.1"
created_at: "2026-08-21T02:10:00+08:00"
updated_at: "2026-08-21T13:35:00+08:00"
description: "白膜场景生图工作台：左边用基础体块搭 3D 白膜场景，右边把白膜图 + 语义分割图当参考图喂给生图模型，让相机角度、构图、物体位置稳定可控"
use_cases:
  - "文生图构图老抽卡：想要「人在左、车在右、镜头压到膝盖高度」，每次出来都不一样"
  - "手上没有 ControlNet 需要的结构参考图，又不想为一张构图去建模或翻照片"
  - "人指挥 agent 摆世界：agent 按语义放置物体、解算相机，人在浏览器里同时看到场景变化"
  - "同一机位反复出图，只换材质与细节描述，构图保持不动"
tags:
  - interactive
  - image
  - 3d
  - composition
  - controlnet
output_targets:
  - stdout
dependencies:
  - doubao_seedream_image
inputs:
  action:
    type: string
    required: false
    default: "view"
    description: "要做的事。项目：project_list / project_create / project_switch / project_rename / project_delete。场景：scene_get / scene_put / object_add / object_update / object_delete / scene_clear / place（放新的）/ move（挪已有的）。测量：measure / validate。相机：camera_set / camera_frame。出图：snapshot / preview / legend / generate / critique / history。指挥：instruct（一句人话翻成动作）。出图前：preflight（体检）/ expand_prompt（把题目扩写成草稿）。草稿：draft_get / draft_put（人写到一半的东西属于项目）。界面：view（默认）/ catalog"
  slot:
    type: string
    required: false
    default: "default"
    description: "页面槽位。同时开多个场景时给每个场景一个槽位，默认 default"
  no_open:
    type: boolean
    required: false
    default: false
    description: "view 时只返回地址、不请主人的浏览器打开它"
  scene:
    type: dict
    required: false
    description: "scene_put 必填：整份场景对象（canvas / camera / objects）。版本号由服务端说了算，传什么都不作数"
  project:
    type: string
    required: false
    description: "在哪个项目上做这件事，缺省是当前 active。slug 不存在会明确报错，NEVER 静默落回 active"
  text:
    type: string
    required: false
    description: "instruct 必填：一句人话，比如「在车左边两米放个人，机位压到人眼高度」"
flow:
  - step: 1
    action: "resolve_data_dir"
    description: "读 FRAGO_RECIPE_DATA_DIR 定位数据目录，缺省回落 ~/.frago/data/image/recipe-caches/whitebox_scene_studio；不存在就建出来，并保证 scene.json / commands.json 有一份可用的初值"
    inputs:
      - source: "env.FRAGO_RECIPE_DATA_DIR"
    outputs:
      - name: "data_dir"
        type: "string"
  - step: 2
    action: "dispatch_action"
    description: "按 action 分发。view 把 dataDir、色卡与体块词表交给 frago recipe publish 发布成页面状态；场景类动作过 clean_scene 校验后原子写 scene.json 并递增版本号，页面轮询到版本变化即重载；出图类动作走 render.py 软件光栅器，不依赖浏览器"
    inputs:
      - source: "params.action"
      - source: "step.1.data_dir"
    outputs:
      - name: "open_url"
        type: "string"
---

# whitebox_scene_studio · 白膜场景生图工作台

把文生图里最不稳的一环——空间——从抽卡变成摆位。

左边是一个 3D 白膜编辑器：拖几个方块、圆柱、胶囊，摆成人、车、楼、树，转到你要的机位。
右边是生图台：白膜图（交代体积与透视）和语义分割图（交代哪块是人、哪块是车）自动当参考图，
配上一段系统生成的色卡图例，一起喂给火山方舟 Seedream。出图就按你摆的来。

完整产品说明见同目录 `spec.md`。

## 现在能用到哪一步

**v0.5.0：项目化 + 页面实时同步 + UI 里能指挥 agent。**

- 项目是一等公民：每个项目一份独立的场景与产物，互不串台。
- 页面显示的一切，真值都在磁盘上：终端里改了什么，页面 800ms 内跟上，不用刷新。
- 左栏底下有个指挥台：一句人话，agent 翻成动作去执行。

```bash
frago recipe run whitebox_scene_studio
# → open_url: http://localhost:8093/app/whitebox_scene_studio/
```

### agent 怎么用它摆一个场景

```bash
R() { frago recipe run whitebox_scene_studio --params "$1"; }

R '{"action":"object_add","shape":"plane","semantic":"ground"}'
R '{"action":"object_add","shape":"box","semantic":"vehicle","label":"银色轿车","rotation":[0,-20,0]}'
# 不用自己算世界坐标：说清挨着谁、在哪边、隔多远
R '{"action":"place","shape":"capsule","semantic":"person","label":"打伞的女人",
     "relative_to":"obj_2","direction":"left","distance":2}'
R '{"action":"camera_frame","margin":0.15}'   # 退到刚好装下全部主体
R '{"action":"validate"}'                     # 穿模？悬空？出画？
R '{"action":"snapshot"}'                     # 不开页面也能出图
R '{"action":"critique"}'                     # 交给多模态模型看构图
R '{"action":"generate","prompt":"黄昏的城市街角，湿漉漉的路面"}'
```

### 项目

每个项目一份独立的场景与产物，磁盘上就是一个目录：

```
$DATA_DIR/
  state.json              # 页面每 800ms 只读这一个：active / 三个版本号
  projects.json           # 清单与当前 active
  projects/<slug>/
      scene.json          panel.json        # 场景真值 / 右栏真值
      agent_log.jsonl     history.jsonl
      snapshots/  generated/  preview/
```

```bash
R '{"action":"project_create","name":"雨夜天台"}'   # 建完自动切过去
R '{"action":"project_list"}'
R '{"action":"place","project":"street-corner", ...}'  # 指名道姓在哪个项目上做
```

所有 action 都接受可选的 `project`，缺省是当前 active。**slug 不存在会明确报错**，
NEVER 静默落回 active——那会让 agent 以为自己改的是 A、其实改的是 B，两边都显示「成功」。

删项目不物理删除，产物移进 `.trash/`；只剩一个项目时拒绝删，并说清楚为什么。

### UI 里指挥 agent

```bash
R '{"action":"instruct","text":"在车左边两米放个人，机位压到人眼高度"}'
```

模型只能吐**本配方已有的 action 调用**，不另发明一套 DSL——这样命令行验过的每一条契约
在 UI 上原样成立，出错信息也是同一套人话。执行前整批预检，过不了就整批拒绝；
执行中万一出错，整份场景回滚。做不到的事（改天空颜色、加材质光影）明确说做不到，不瞎改场景。

**让最自然的说法能落地，靠的是四件事**（都是被真实失败逼出来的）：

1. **`move` 是独立动作。** 「往左挪半米」以前没有对应动作，模型只能硬套 `place`，
   于是要么多出一个物体、要么因为缺 shape 整批被拒。`place` 放新的、`move` 挪已有的，
   两者的 `distance` 含义也不同：前者是两物之间的净空，后者是这个物体自己挪了多远。
2. **凡收物体的地方，id 和名字都认。** 调用方在放下一个新物体之前无从知道服务端会分配
   哪个 id，「用自己起的名字去指刚放下的东西」是唯一合理的写法。重名和找不到都要报清楚，
   含糊地挑一个会让人以为改的是 A、其实改的是 B。
3. **`shape` 可以省略**，按语义取默认形状。「放一把椅子」里「椅子」这个信息已经够了，
   非要它再说一遍「用方块」是多余的；可选字段写错（比如 `align`）就退回默认并说一声，
   不因此拒掉整句话。
4. **取景永远排除地面与水面**，即使被显式点名。「框住天台上所有东西」里地面确实是一个物体，
   照字面算进去就要框住一块 30×30 米的地板——相机被推到几十米外，
   而他要看清的恰恰是地板上那些东西。

**刻意不含 `generate`**：一句「摆个街角然后出图」会直接花掉主人的钱，
而人说这句话时未必意识到自己在下单。出图必须是他自己按那个按钮。

### agent 接口的四条约定

- **`place` 的 `distance` 是净空，不是中心距。** 「把人放在车左边 2 米」，
  人要的是 2 米空地。按中心距算的话，车半长 2.3 米，人会站在车里。
- **方向按「相机此刻的朝向」解释。** `left` 是画面里的左边，不是世界的 -X。
  相机一转，同一句话指向另一个方向——这跟人说话的方式一致。
- **尺寸可以直接给米数。** `dims: [4.6, 1.5, 1.9]` 比 `scale` 好使，
  也不用记「胶囊的单位体比别的窄一半」。给了 `dims` 就不用再给 `scale`。
- **失败时 stdout 是空的。** runner 把配方的非零退出转成一行 `Error: ...` 发到
  **stderr**，结构化返回拿不到。所以读错误信息别把 stderr 丢掉；
  正常路径则 NEVER 加 `2>&1`，那会把 `[recipe]` 执行记录混进 JSON。

### 各语义的默认尺寸（米，宽×高×深）

| 语义 | 尺寸 | 语义 | 尺寸 |
|---|---|---|---|
| 人物 | 0.5 × 1.7 × 0.35 | 建筑 | 8 × 12 × 8 |
| 车辆 | 4.6 × 1.5 × 1.9 | 家具 | 1.2 × 0.75 × 0.6 |
| 植被（锥形） | 3 × 5 × 3 | 墙面 | 4 × 2.8 × 0.2 |
| 植被（球冠） | 3 × 3 × 3 | 地面 | 40 × 0.02 × 40 |

放置时按语义自动取，之后随便调。**白膜的尺度错了，模型看到的比例关系就全错**——
半米高的人站在巴士大小的车旁边，出图不会是你摆的那个世界。

### 页面上能做什么

| 事情 | 怎么做 |
|---|---|
| 放一个体块 | 从体块库**拖**到地面；或**点**体块库选中、再**点**地面落位 |
| 改语义（决定分割图颜色） | 先点语义色卡再放；已放的在「选中物体」里改 |
| 起名字 | 选中后在「名字」里填。这行字会写进给模型的图例，是「这块红色是谁」的答案 |
| 平移 / 旋转 / 缩放 | 选中后拖 gizmo，模式按钮或 G / R / S 切换 |
| 删除 / 复制 | 工具条按钮，或 Delete 键 |
| 吸附 | 「贴地」保证平移时不离地，「网格吸附」按 0.5m / 15° / 0.1 倍走 |
| 换机位 | 四个预设按钮（人眼 1.6m / 低 0.4m / 高 3m / 俯瞰），或鼠标轨道 |
| 定画幅 | 四个画幅按钮 + FOV 滑杆，画面里那个亮框就是将来出图的范围 |
| 下载出图 | 结果网格里每张右下角有「下载」；对比那一屏有一个整宽的下载按钮，文案里就写着会存下什么文件名 |

**两条路都要在**：拖是给人的，点是给 agent 的——驱动页面的一方只会点、不会拖，
少了点选放置这条路，这个工具对 agent 就是不可用的。相机预设与 FOV 同理，
所以它们是可点击的 DOM 控件而不是只有鼠标手势。

## 几条不显然的约定

- **旋转存的是度数，不是弧度。** agent 说「转 90 度」比说 1.5708 顺手得多，
  前端在边界上转换。
- **`scale` 是倍数，不是米数。** 每种形状在前端都是一个单位体（y 从 0 到 1，
  底面中心在原点），所以 `position` 直接就是贴地点。胶囊天生比方块窄，
  硬让 scale 等于米数，同一个数字在不同形状上就是不同的宽度。
  所以对外一律用 `dims`（米），换算在 `scene_ops.dims_to_scale` 里做。
- **取景按包围盒逐角点解，不按包围球。** 包围球对横向铺开的街景太浪费，
  主体会缩成一小块。另外相机有 0.3 米的地面下限——主体越高、原机位越低，
  沿原方向退得越远就扎得越深，不拦会解到地底下。
- **相机有两个 FOV。** `scene.json` 里那个是出图用的，也是安全框内的真实视野；
  three 相机上跑的那个更大，大出来的部分正好是框外那圈能看见的余量。
- **`scene_put` 要么整份成功、要么整份拒绝。** 半份落盘比拒绝更糟：人看到编辑器里
  东西还在、磁盘上已经少了几个，下一次轮询又把少掉的那份灌回来，等于凭空删物体。
- **渲染是双通道，服务端那条是主路径。** `render.py` 是一个纯 Python 软件光栅器
  （numpy + pillow，自己做网格、投影、z-buffer）。所以 agent 不开页面也能出图，
  没有 GPU 的浏览器也能完整使用这个工具，端到端测试才跑得通。
  浏览器 WebGL 只是加速路径：有就用实时视口，没有就退化成服务端预览，
  放置、删除、机位、FOV、画幅、生图全部照常。
- **seg 通道 NEVER 超采样。** 混出来的中间色会让图例里那句「#E74C3C 红色 = 人物」失真。
  这条在 `render.py` 里是强制的，clay 才走 2× 超采样。
- **取景不把地面算进去。** 地面板动辄 40×40 米，算进包围盒会把机位推到几十米外，
  画面里人和车缩成两个点。服务端 `scene_ops.framing_aabb`、前端 `scenemath.framingBounds`
  都排除 ground / water。
- **出图尺寸跟着画幅走。** 方舟只认 `WIDTHxHEIGHT` 或 `2k/3k/4k`，且面积至少
  3,686,400 像素（正好 2560×1440）。画幅比按这个下限等比放大，比例一点不改——
  参考图和出图不同画幅的话，「构图跟没跟住」就无从谈起。

## 白膜之外，还有三件工具必须替人兜住

这三条都是「委托方按了生成、四张图全废」之后逐条查实的，没有一条是他的错。

### 一、position 是底面贴地点——这件事必须对模型说死

多数三维工具里 position 是几何中心，所以模型默认按中心摆：
一栋 8 米高的图书馆给 y=4，白模上它就悬在 4 米高的空中。实测一整轮五个物体，
四个的 y 恰好等于自身高度的一半。

提示词里写死约定，**但不能因为写了就省掉兜底**：提示词是劝说，兜底是保证。
执行前扫一遍，y 恰好等于半高（正负都算）就归零，并在回话里说明「我把 X 落回了地面」。
这个错的代价是整批出图作废，而且人未必看得出来——白模里一栋浮空的楼，乍看只像构图有点怪。

同理，`place ... direction=below` 挨着一个站在地上的东西放，照字面算会把它整个埋进土里。
埋了就看不见，人只会觉得「怎么少了一样东西」。现在会落到地面上并说一声。

### 二、图例 NEVER 把语义色说成物体的颜色

原来写「#8E44AD 紫色 = 道具（1 个：行李箱）」，模型读成了「行李箱是紫色的」：
出的图里人是纯红、箱子是紫、树是绿，五个颜色跟色卡一一对应，
**连分割图的黑色背景都被当成黑夜空画了出来**。提示词弱的时候没有别的信息压住它，
这个误读就整个暴露。

现在图例必须先讲死三件事：这些颜色只是标记区域归属的记号、成片里 NEVER 出现这些颜色、
黑色区域是「那里没有东西」而不是黑夜。色块的中文颜色名也去掉了——
「紫色 = 道具」这种写法本身就是在教它上色。

### 三、按下生成之前得有人拦一下

浮空 `validate` 报得出，提示词只有一个书名也看得出，但人按「生成」时什么提示都没有，
四张图的钱花完才发现。现在按生成先走一遍 `preflight`：几何问题 + 提示词强度，
摆出来让人自己选「我先去修」还是「照样生成」。

**一条都不强制拦**：浮空在超现实场景里可能正是他要的，提示词简陋也可能是故意的。
工具的位置是「说出来」，不是「替他决定」。体检面板出现时会主动滚进视野——
它是一个在问人问题的地方，问完了按钮却在视野外，等于没问。

### 四、「提示词我没有心情写」不是懒，是工具没接这一棒

场景里已经有物体名、机位、画幅、语义，够写出一段像样的描述了。所以加了两样：
风格/时间/天气/光线的**可点标签**（拼进去，NEVER 替换掉人写的那部分），
以及**一句话扩写**——把题目连同场景里的物体名一起交给模型，扩写成草稿填进输入框。
明说是草稿：替人做决定和帮人起头是两回事。

## 「人现在在看哪个项目」只有一个说了算的地方

`state.json` 的 `active` **只能**来自注册表，NEVER 由「这次动作操作的是哪个项目」决定。

犯过一次，现象很唬人：切到别的项目，过几秒自己弹回默认项目，切一次弹一次，
看起来就像切换按钮坏了。真相是几秒前那个还在路上的请求——它跑完时把 active
写成了自己操作的那个项目，页面看到 active 变了就整页切过去。
动作越慢越明显（`generate` 四十秒），而人根本想不到是旧请求在作祟。

同源的一条：`panel_rev` 和 `scene_version` 说的是「活动项目现在什么样」，
动作打在非活动项目上时**不许动它们**，否则页面会为一个它根本没在看的项目
白重拉一遍右栏，人正在写的东西也跟着被刷掉。

`test_state_sync.py` 把这个时序钉死了——不起后台进程、不靠 sleep 抢时机，
直接重演「动作拿着旧注册表、期间 active 被改、它最后才写盘」。
退回旧写法时这条测试会准确地报出 `state.active 实得 'X'`。

## 人写到一半的东西也属于项目

提示词框曾经不属于任何项目，只是页面上一个临时输入框。于是切项目时上一个项目的
文字留在那儿：图例元信息写着 A 的场景版本、提示词却是 B 的内容，
人看到的是一份自相矛盾的界面，而且看不出哪半边是错的。

现在每个项目一份 `draft.json`：提示词正文、图例是否手改过、出图参数。
切项目时整套换过去，没有草稿的项目就是干净的空框，**不是继承上一个项目的**。
切换过程中防抖回写会被冻住，否则 A 的草稿会被写进 B。

风格标签那一排也归这里管：

- **能取消**，而且取消时只撤自己拼进去的那一段，NEVER 动他自己写的字。
- **组内单选**：「写实摄影 + 日式漫画 + 水彩 + 油画」拼在一句话里本身是自相矛盾的，
  点第二个自动把第一个换掉；跨组可以叠加。
- **高亮完全由正文反推**，不另存一份状态——两份状态迟早对不上，
  而对不上时人只能信眼睛看到的那份，也就是正文。
- 有一个「清掉所有标签」的出口。上一版没有，委托方七个全点亮之后自己出不来。

这段字符串手术在 `assets/js/promptdraft.js` 里单独一个模块，`test_prompt_draft.mjs`
钉着它。抽出来是因为它动的是人自己写的字：撤一个标签时多吃掉一个字、
或者把他写的一句话连带删了，是这种功能最容易出、也最伤人的错。

## 一条容易重犯的并发陷阱

注册表（`projects.json`）**临写前必须重新读盘**，NEVER 把进程启动时那份整份写回去。

一个动作可能跑很久——`generate` 四十秒、`instruct` 五六秒——而页面每 800ms
就会触发一次动作，每次都是一个新进程。这期间任何人新建或删掉了项目，
都会被那份几十秒前的副本覆盖：**新建的项目凭空消失，注册表看起来还毫无异常**，
谁也说不清是怎么没的。

已实测复现：一边跑 `instruct`、一边 `project_create`，旧写法下新项目必丢。
现在只更新自己那一项的物体数，且写前重读（`touch_registry`），
窗口从「整个动作的时长」缩到几微秒。要彻底消除还得上文件锁，
但对「一个人 + 一个页面」这个用法，这一步已经把实际风险拿掉了。

## 页面怎么保持实时

**页面显示的一切，真值都在磁盘上；发布快照只服务于访客。**

页面每 800ms 只读一个极小的 `state.json`，里面是四个数：`active`、`projects_rev`、
`panel_rev`、`scene_version`。哪个跟自己记的不一样就重拉哪一份——
`active` 变了整页换项目，`scene_version` 变了重载场景，`panel_rev` 变了刷新右栏。

拆成四个文件各轮一遍是行不通的：轮询次数翻倍，而且几份东西到达时机不同，
页面会在半秒内闪过几种自相矛盾的状态。

右栏的真值是每个项目自己的 `panel.json`（图例 + 最新快照 + 最近一次生成），
由服务端在每个动作结束时重写，`rev` 自增。所以「终端里出了张图、页面右栏当场跟着换」
不需要任何推送机制。

**图例有一条特殊规则**：它是从场景推出来的，场景一变就该跟着变——但人手改过就不能覆盖。
所以第三种做法：照旧显示他写的那份，上面挂一条「场景已变，图例可能过时了」，点了才换。
直接覆盖会把人写了半天的东西冲掉；完全不提示，他会拿着一份过时的图例去出图。

## 下载与访客模式

下载走 `<a download>` 直指 `data/` 下的静态文件，**不经后端**。文件名是
`whitebox-<时间戳>-<序号>.png`，跟落盘目录一一对应，存一堆到桌面上也认得出谁是谁。

不经后端是硬要求，不是偷懒：`frago recipe expose` 的 public 模式下，访客拿到的
`config.json` 里 `apiBase` 是 `null`、`readOnly` 是 `true`，`/api/recipes/<n>/run`
对他一律 401。任何「点一下、后端给你打个包」的做法在那边都是死路。

同理，**结果清单本身也得随页面状态发布**（`public.recent`），否则访客看到的是
一个空网格加一排下载按钮——按钮在、没东西可下，等于没做。页面启动时先认发布的那份，
拿不到才退回 `history` action。

访客模式下页面自动进只读：改场景、重新生成、读历史这些入口收起来，
留下看参考图、拉对比滑杆、下载原图。收起来而不是留着报错——
留着的话人点了只会得到一句「apiBase 是 null」，那不是给人看的话。

## 页面在哪

页面由 `frago server`（固定 8093）从本配方的 `assets/` 目录直接发，配方自己 NEVER 起 HTTP 服务：

- `http://localhost:8093/app/whitebox_scene_studio/` → `assets/index.html`
- `.../config.json` → 服务端每次请求现合成，带 `apiBase` / `recipeName` / `appBase` / `slot`
- `.../data/<相对路径>` → 从发布的 `dataDir` 按需读（`scene.json`、`commands.json`、快照图……）

## 数据落在哪

`~/.frago/data/image/recipe-caches/whitebox_scene_studio/`

| 文件 | 装什么 |
|---|---|
| `scene.json` | 场景真值：画幅、相机、物体清单。y 轴朝上，单位米，地面 y=0，物体 position 是底面中心贴地点 |
| `preview/latest.png` | 退化模式下的视口画面，每次改动重渲 |
| `snapshots/<stamp>/` | `clay.png` / `seg.png` / `depth.png` / `meta.json` |
| `generated/<stamp>/` | 生成图与对应参数 |
| `history.jsonl` | 每次生成记一笔 |

真值在磁盘上，页面轮询同步——所以 agent 改了场景，人的浏览器里立刻动；人拖了物体，agent 下一次读就看得到。

## 自测

```bash
cd ~/.frago/recipes/workflows/whitebox_scene_studio
uv run test_render.py       # 光栅器：单位体、欧拉序、seg 逐位精确、三通道对齐、近平面裁剪
uv run --no-project test_scene_ops.py   # 几何：默认尺寸、包围盒、相对方向、place 净空、体检、取景
uv run --no-project test_instruct.py    # 指挥台：一组最自然的说法，报命中率（会真的调模型）
uv run --no-project test_state_sync.py  # 切项目不被在途请求拽回去（确定性重演时序）
node test_prompt_draft.mjs              # 标签的拼/撤/换，人写的字一个不动
```

`test_instruct.py` 是**回归用例**不是单测：十五句人话覆盖挪、放、删、改名、换机位、
框住、放大、贴地、问距离、做不到十类，每句跑前重置到同一份固定场景，
判的是「场景真的变成了他要的样子」而不是「模型有没有回话」。
没命中的会把模型原话和被拒理由一起打出来——只报一个命中率，下一步该改哪里是猜不出来的。

这两套验的都是**看画面看不出来的东西**——物体照样画得出来，只是位置不对、
尺寸不对、颜色差一个色阶。改 `render.py` / `scene_ops.py` / `scenemath.js`
任何一处之后必跑，三者的约定是逐位对齐的。

## 两条纪律

- **NEVER `expose --runnable`**：这个配方会调生图模型，花的是主人的钱。
- **凭证不自己读**：生图 subprocess 调 `doubao_seedream_image`，runner 按子配方名从 `~/.frago/recipes.local.json` 注入。
