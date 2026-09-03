# recipe-creation

分类: 纪律（MUST）

## 解决什么问题

配方怎么产生。**答案只有一条路，别的路平台都不认。**

这篇以前教的是「agent 拿到 spec 之后，把需求映射成 recipe.md 和脚本代码」——
也就是 agent 自己写文件。那条路已经废了，为什么见最后一节。

## 标准流程

    frago recipe plan <名字> --prompt "<需求>"     一、定规格
            ↓  人看一眼规格，尤其是每个 mode 的访问级别
    frago recipe create <名字>                     二、按规格生成模板
            ↓  在模板上填业务逻辑
    frago recipe validate <目录>                   三、查
    frago recipe run <名字> --params '{...}'       四、跑

`frago recipe create <名字> --prompt "<需求>"` 是把前两步并成一条命令，
**不是跳过第一步**——它照样先生成规格、让 worker 填完，再按规格生成模板。

**没有规格就不生成配方。** create 读不到规格里那段机器可读的 yaml 就直接退出，
一个文件都不写。这是实测出来的：一个新 agent 找到 `create --prompt`，不写规格，
让写实现的那一轮顺手决定这个模块导出什么——而导出的 mode 是别的模块要依赖的承诺，
顺手定下来的承诺收不回来。

### plan / create MUST 后台跑（agent 调用方）

这两条命令都是**阻塞的**：它们各派一个 worker 去写文件，跑完那一轮才退出。
一份认真的任务书要 worker 写十几到几十分钟，命令本身**不设时间上限**
（缺省 `--timeout 0`，与 `frago agent` 同一个契约）。

```bash
# 主控：Bash 工具带 run_in_background: true
frago recipe plan <名字> --prompt-file <任务书.md>
```

前台起会被砍：Claude Code 的 Bash 工具对前台命令有 **10 分钟硬上限，提不动**。
砍掉的只是这条命令，**worker 不会跟着停**——它还在写同一个配方目录，而磁盘上
的东西一样没回滚。人看到「失败」去重跑，于是两个 worker 在一个目录里打架。
2026-08-27 已经实测踩过两次：文件都写好了，CLI 却报 timed out。

真要卡表就 `--timeout N`，那个数字交给 `frago agent` 执行，它到点会把自己的
tmux 会话收掉。**NEVER 从外面套杀手**（`timeout 600 frago recipe plan ...`、
或任何 kill）——外面杀掉的是 CLI，tmux 是独立守护进程，留下的是一条谁也认领
不了、还在写盘的孤儿会话。

同一条纪律的上游版本见 `frago book agent-worker-driving`。

### 一、plan 产出什么

一份 `spec.md`，分两半。

**上半给机器读**，`create` 照着它长出代码：

    type: atomic          # atomic（一件事）| workflow（串起几件事）
    runtime: python
    modes:                # 能做哪几件事（一个 mode 一件），每件开到什么程度
      status: export      #   export = 只读契约：别的模块能调，页面也读得到
      save: action        #   action = 这张页面上能按，允许干活
      refresh:            #   不写 = 只有主人能跑（默认，而且默认是对的）
    default_mode:         # 不写 mode 时跑哪一个，留空就是上面第一个
    imports: {}           # 用了谁的哪个口
    page: false           # 要不要一张页面。**整行不写按「要」处理**

**下半给人读**：它解决什么问题、每个 mode 干什么、**它不做什么**、数据存什么、
出错怎么办、怎么验。

写清边界比写清能力更省事——下一个人照着扩展时，知道哪儿不该伸手。

规格自相矛盾时 `create` 当场拒，三种：级别写了 export / action / 留空以外的东西；
`default_mode` 指的那个 mode 不在 modes 里；`page: false` 却给某个 mode 写了
`action`——action 的意思就是「这张页面上能按」，没有页面就没有这回事。

### 二、create 产出什么

    recipe.py     契约描述头 + 继承 Recipe + name / version / imports +
                  每个 mode 一个方法骨架，方法上带着规格里定的访问级别
                  （@export / @action / 不标），文件底部一行 <类名>.main()
    recipe.md     元信息。**NEVER 往里写 exports / page_actions**——
                  这两个字段已作废，写了 validate 直接报错
    assets/       空页面骨架三个文件（index.html / app.js / app.css），
                  规格里 page 不是 false 才生成

**在模板上改，NEVER 另起炉灶重写文件。** 头三行那个 `frago-recipe/1` 描述头
MUST 原样保留：平台起 python 配方之前只查这一件事，没有它不启动。

recipe.py 顶部带一段 PEP 723 声明块。要第三方包就写进它的 `dependencies`；
基类 `frago_recipe` **不要写进去**，它由平台在起进程时递过来，本身只用标准库。

## 硬规矩

### 1. 能力建在基类上

    from frago_recipe import Recipe, export

    class MyBoard(Recipe):
        name = "my_board"          # MUST 与目录名、recipe.md 里的 name 一致
        version = "0.1.0"
        default_mode = "status"    # 不写就是第一个 mode_* 方法
        imports = {}

        @export
        def mode_status(self) -> dict:
            return {"rows": len(self.store.read_jsonl("ledger.jsonl"))}

        def mode_refresh(self) -> dict:
            ...

    MyBoard.main()

**没有 modes 名单要维护**——平台扫 `mode_*` 方法，按方法上的标记决定各自开给谁。
自己写 `modes` / `exports` / `page_actions` 会被当场拒绝（类一 import 就抛，
validate 也报）：手写的那份跟方法一旦对不上，页面和总线各按各的答案走，而且不报错。

基类由平台在起进程时递给配方。它管这些事：

| 要做的事 | 基类给的 |
|---|---|
| 数据写哪儿 | `self.data_dir`；`self.store` 上有 `path` / `read_json` / `write_json` / `append_jsonl` / `read_jsonl`，写一律先写临时文件再改名 |
| 别人交出来的共读数据 | `self.common_dir`（只读）、`self.seed_dir`（起始数据，拷一次之后归自己） |
| 这一轮是谁在跑 | `self.caller` / `self.slot` / `self.is_visitor` |
| 说话 | `self.progress()` / `self.warn()` / `self.log()` |
| 出错 | `raise self.fail(...)`；`self.require("a", "b")` 一次报全缺了哪些参数 |
| 问别的模块要数据 | `self.ask(模块, mode, 参数)` |
| 跑 frago 自己的命令 | `self.ask_frago(["user", "list", "--format", "json"])` |
| 页面 | `self.publish(渲染状态)`、`self.open_page(地址)` |
| 不让两轮叠在一起 | `with self.lock():` |

还有两个类属性：`requires = {"save": ("id",), "*": (...)}` 声明哪个 mode 缺哪个
参数就不许起跑（`"*"` 对每个 mode 都生效）；`reads_common` 点名要读谁的共读数据。

NEVER 自己拼数据路径，NEVER 留「平台没给就用我自己的」那种兜底——
那句话不报错，只让同一份数据悄悄散成好几份。平台没交代落点时 `self.data_dir`
**直接抛，配方不接不兜底**。

### 2. 访问级别写在方法上

一个 mode 一个级别，三选一：

| 标记 | 谁够得着 | 允许干活 |
|---|---|---|
| `@export` | 别的模块（走总线）+ 这个配方自己的页面（`POST /app/<名字>/api/<mode>`） | 不允许，MUST 只读 |
| `@action` | 只有这个配方自己的页面（`POST /app/<名字>/run`，体里 `{"params": {"mode": "…"}}`） | 允许 |
| 不标 | 只有主人 | 允许 |

**`@export` MUST 只读**：不触网、不重算、不改状态、不开浏览器。别人每 5 分钟
问一次也不会出事。不确定要不要开放就先别标——开出去容易，收回来难。

**`@action` 是权限不是形式**：谁打得开那张页面谁就能按，而按下去是在主人的机器上、
用主人的凭证跑。**会花钱、会以主人身份对外做事的 mode NEVER 标 @action。**

- **一个 mode 一个级别，不叠加。**「既导出又给页面按」本来就没有意义：
  `@export` 已经意味着页面读得到，页面直接调 `api/<mode>` 即可，不需要按钮。
  同时标两个，validate 直接报错。
- 标了 `@action` 就 MUST 用 `self.store` / `self.data_dir`（或读
  `FRAGO_RECIPE_DATA_DIR`），否则 `validate` 直接报错——不然每个人按下去写的都是
  主人那一份。同理，一旦有 `@action`，代码里那种从家目录派生出来的固定写入位置
  会在 `frago recipe expose` 时被拦下（没有 action 时它只是一条警告）。
- 页面能按什么，**不再由开放页面时的开关决定**。`--runnable` 已经取消，
  命令现在直接报错。这个答案随配方走，在每台机器上一样。

#### 别的模块能调什么 ≠ 页面能按什么

这两件事不嵌套，NEVER 照着 C++ 的 public / protected / private 去想——那是全序，
一层套一层。这里不是：一个 mode 可以允许页面触发却不允许别的模块调用，
因为总线那条路额外承诺只读，而页面这条明确不承诺。要类比就类比
Rust 的 `pub(crate)`——可见性带着「对谁」。

#### 平台怎么读到这个标记：读源码，不导入

问一个模块开了什么，不该把它跑起来——文件底部那行 `main()` 是裸调的，
import 它就等于跑它。所以平台按语法树读装饰器的**名字**：
`@export` 和 `@frago_recipe.export` 都认得出，
**`from frago_recipe import export as pub` 这种起了别名的认不出来**，
那个 mode 会被当成没标，页面和总线都够不着它，而文件上明明写着开了。
NEVER 给这两个装饰器起别名。

### 3. 跨模块只走接口

    imports = {"cn_etf_data_feed": ("status", "read")}
    ...
    data = self.ask("cn_etf_data_feed", "read", {"symbol": "159995"})

NEVER 读对方的文件，NEVER import 对方的代码。

对方**不知道自己正在被读**：它的作者改自己的东西时看不到任何提示，
断裂发生在跟改动毫无关系的地方，往往要等到有人点开某张页面才暴露。

**拒绝发生在总线，不在配方里。** 调用带着本模块声明的 imports 一起发出去，
服务端来判，四种拒法：没在 imports 里点过这个模块；点了模块但没点这个 mode；
对方没把这个 mode 标 `@export`；对方压根不是建在基类上的模块。
而且每一次调用——成了的和被拒的——都记进账本。本地先拦一道会快一点、话也好听，
代价是「谁伸手要了它没声明过的东西」这件事从此没人看得见，
而那正是这套东西里最该被看见的一件事。

`@action` 只开给这个配方自己的页面，**别的模块调不到**。

### 4. 要跑 frago 自己的命令，走 self.ask_frago

    out = self.ask_frago(["user", "list", "--format", "json"])
    if out["code"] == 0:
        roster = json.loads(out["stdout"])

**NEVER 自己起 frago 子进程。** 配方跑在一个只看得见本次落点的视图里，
在那里面起的 frago 命令读不到平台自己的账本——而它不报错：
`frago user list` 在一台有 23 个账号的机器上返回空列表、退出码 0，
页面照着画出一张空表，标题还写着一切正常。走这条路，命令在服务端自己的进程里跑，
配方拿回 `code` / `stdout` / `stderr` 三样，跟自己起子进程读到的形状一样。
不拼命令行、不经过 shell，参数里带空格引号都不用转义。

确实有必须在配方进程里起命令的情况（驱动浏览器、桌面这类）。那时在 recipe.md
写一行 `uses_frago_cli: true`，把 frago 命令自己的工作目录交出来；不写，
`frago recipe validate` 直接拒，隔离下那条命令也跑不动。
**能走总线的优先走总线。**

### 5. 页面是前端，配方是后端

`publish()` 只发渲染状态，**NEVER 发路径**。这不是劝告：基类会递归扫一遍要发布的
状态，遇到 `/`、`~/`、`./`、`C:\` 开头的字符串当场抛，并指出是哪个键。

页面要数据就调本模块导出的只读 mode：

    // assets/app.js
    const data = await ask("status");        // 内部是 POST api/<mode>

页面拿到绝对路径就是前端伸手进后端的文件系统：打开页面的人机器上没那个文件；
能读任意路径的接口对主人以外一律关死（登录了也不行）；配方落点一挪，
页面还在读老地方，而每次刷新都显示成功。

页面按下去要走的那道写入门（`POST /app/<名字>/run`）**按 recipe.md 的 `inputs`
严格校验参数**：没在 inputs 里声明过的键一律打回，主人和登录用户一视同仁。
所以页面要传的参数 MUST 在 recipe.md 的 inputs 里声明齐。

## 说话的规矩

配方的 stdout 是一串消息，每行一条 JSON，最后一条是结果。
**NEVER 直接 print 到 stdout**——混一句进去，整段就解不动了。

| 场合 | 用什么 |
|---|---|
| 跑得久 | `self.progress("扫到第 3 只", step=3, of=288)` |
| 不致命的问题 | `self.warn("...")`，进 warnings，不影响 ok |
| 致命的问题 | `raise self.fail("...")`，ok 为假**且退出码非 0** |
| 给人看的日志 | `self.log(...)`，走 stderr |

致命和非致命一定要分开：一道菜写坏了，不该让另外 25 道从页面上消失。

最后那条结果的信封是固定的，由基类成型，配方只管 `data` 那一块：
模块名、版本、契约号、这次跑的哪个 mode、`ok`、`data`、`warnings`、`error`、耗时。
所以 **mode 方法 MUST 返回一个对象**——返回 None 按空对象处理，
返回别的类型当场判失败。

不认识的 mode **NEVER 落到默认那条路上**：基类直接拒，并列出本模块支持哪几个。
一次只读的探问就是这样掉进状态机、真的去调了外部接口。

## frago recipe validate 会拒什么

写完之后唯一的自查。它拒的东西分五层，下面每一条都是 error：

**这是不是一个模块**——带着描述头却没继承 Recipe；类上没写 `name`；
`name` 跟目录名不一致；一个 `mode_*` 方法都没有；文件底部没有 `<类名>.main()`
（没有它这个文件跑起来什么都不做，还安安静静地退出码 0）；
契约号比本机这份 frago 认得的新。

**访问级别声明本身**——一个 mode 标了两个级别；同一个 mode 定义了不止一次；
把级别标在不是 mode 的方法上；类上还写着 `modes` / `exports` / `page_actions`；
`default_mode` 指向一个不存在的 mode。

**元信息**——recipe.md 里写了 `exports` 或 `page_actions`（已作废）；
必填字段缺或不合格：`name` 只能是字母数字下划线连字符，`type` 是 atomic 或
workflow，`runtime` 是 python / chrome-js / shell，`version` 形如 1.0 或 1.0.0，
`description` 必填且不超过 200 字，`use_cases` 至少一条，`output_targets`
取值只能是 stdout / file / clipboard。workflow 还必须有 `flow`，
每一步要有编号、action 和描述，步骤里点名的配方要在 `dependencies` 里。

**落点与凭证**——配方自己拼数据路径；伸手读别的配方的数据目录；
往 frago 自己维护的目录里写；在模块顶层读落点变量（这样一 import 这个文件就死，
任何检查工具、测试、元信息探测都碰不了它）；从 params 里读凭证；
硬编码读某个配方专属的环境变量；声明了 `secrets` 却不读 `FRAGO_SECRETS`；
标了 `@action` 却不读落点；`reads_common` 点名的生产者不存在、或对方没写 `shares`。

**隔离预检**——代码里写下的路径落在本次视野之外；
或者起了 frago 命令却没在 recipe.md 写 `uses_frago_cli`。

另有几条在这里只报警告，但页面要开放给别人时会在 `frago recipe expose` 那一步
被拦下：页面按绝对路径去平台取文件；代码里有只在这台机器上存在的绝对路径；
从家目录派生出来的写入位置（配方声明了 `@action` 时这条升级成拦）。
还有一条自始至终是警告：相对路径没有以自身位置起算——配方跑在数据目录里，
不站在自己的目录里，读自己带的文件要写 `Path(__file__).parent / ...`。

## 为什么不许自己写文件

三百个配方各自解决了同一批问题——数据写哪儿、怎么报结果、怎么找到另一个模块——
每一份看着都合理，没有两份一样。结果是一本交易账本在一台机器上存在四份，
分别记着 48、45、45、37 笔，页面显示三天前那份，而每次刷新都报「成功」。

模板存在的意义不是省打字，是**让这些决定只做一次**。

平台在起配方那一刻检查契约描述头，**没有就不启动**，并告诉你去
`frago recipe create <名字> --force` 生成模板、把现有逻辑搬进 `mode_*` 方法。
这一条只卡 `runtime: python` 的配方——chrome-js 跑在浏览器里，没有基类可继承。

描述头本身是约定不是防线：能写文件的东西都能写那三行。它的用处有两个——
标明这个文件照哪一版契约写的，以及给检查器一个立脚点，让它接着去查那些有牙齿的：
建没建在基类上、声明的 mode 存不存在、导出的那一面是不是真的。

## 下次召回

    frago book recipe-creation
