# recipe-creation

分类: 纪律（MUST）

## 解决什么问题

配方怎么产生。**答案只有一条路，别的路平台都不认。**

这篇以前教的是「agent 拿到 spec 之后，把需求映射成 recipe.md 和脚本代码」——
也就是 agent 自己写文件。那条路已经废了，为什么见最后一节。

## 标准流程

    frago recipe plan <名字> --prompt "<需求>"     一、定规格
            ↓  人看一眼规格，尤其是 exports
    frago recipe create <名字>                     二、按规格生成模板
            ↓  在模板上填业务逻辑
    frago recipe validate <目录>                   三、查
    frago recipe run <名字> --params '{...}'       四、跑

`frago recipe create <名字> --prompt "<需求>"` 是把前两步并成一条命令，
**不是跳过第一步**——它照样先生成规格、让 agent 填完，再按规格生成模板。

### 一、plan 产出什么

一份 `spec.md`，分两半。

**上半给机器读**，`create` 照着它长出代码：

    type: atomic          # atomic（一件事）| workflow（串起几件事）
    runtime: python
    modes: [status, refresh]    # 能做哪几件事，一个 mode 一件，第一个是默认
    exports: [status]           # 别的模块能调哪几个
    imports: {}                 # 用了谁的哪个口
    page: false                 # 要不要一张页面

**下半给人读**：它解决什么问题、每个 mode 干什么、**它不做什么**、数据存什么。

写清边界比写清能力更省事——下一个人照着扩展时，知道哪儿不该伸手。

### 二、create 产出什么

    recipe.py     契约描述头 + 继承 Recipe + 按规格声明的 modes/exports/imports
                  + 每个 mode 一个方法骨架
    recipe.md     元信息，exports/imports 与代码一致
    assets/       空页面骨架（规格里 page: true 才生成）

**在模板上改，NEVER 另起炉灶重写文件。**

## 四条硬规矩

### 1. 能力建在基类上

    from frago_recipe import Recipe

    class MyBoard(Recipe):
        name = "my_board"
        modes = ("status", "refresh")
        exports = ("status",)
        imports = {}

        def mode_status(self):
            return {"rows": len(self.store.read_jsonl("ledger.jsonl"))}

    MyBoard.main()

基类由平台在起进程时递给配方，**不用在依赖里声明**。它管四件事：

| 要做的事 | 基类给的 |
|---|---|
| 数据写哪儿 | `self.store` / `self.data_dir` |
| 说话 | `self.progress()` / `self.warn()` / `self.log()` |
| 问别的模块要数据 | `self.ask(模块, mode)` |
| 页面 | `self.publish(渲染状态)` |

NEVER 自己拼数据路径，NEVER 留「平台没给就用我自己的」那种兜底——
那句话不报错，只让同一份数据悄悄散成好几份。

### 2. 导出的 mode 必须只读

`exports` 里的 mode 是**对外的承诺**：不触网、不重算、不改状态、不开浏览器，
别人每 5 分钟问一次也不会出事。

内核在总线上按这份声明放行，没导出的一律调不到；页面也只能调导出的。
**不确定要不要开放就先留空——开出去容易，收回来难。**

### 3. 跨模块只走接口

    imports = {"cn_etf_data_feed": ("status", "read")}
    ...
    data = self.ask("cn_etf_data_feed", "read", {"symbol": "159995"})

NEVER 读对方的文件，NEVER import 对方的代码。

对方**不知道自己正在被读**：它的作者改自己的东西时看不到任何提示，
断裂发生在跟改动毫无关系的地方，往往要等到有人点开某张页面才暴露。

### 4. 页面是前端，配方是后端

`publish()` 只发渲染状态，**NEVER 发路径**。页面要数据就调本模块导出的只读 mode：

    // assets/app.js
    const data = await ask("status");

页面拿到绝对路径就是前端伸手进后端的文件系统：访客机器上没那个文件；
能读任意路径的接口对访客一律关死；配方落点一挪，页面还在读老地方，
而每次刷新都显示成功。

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

## 为什么不许自己写文件

三百个配方各自解决了同一批问题——数据写哪儿、怎么报结果、怎么找到另一个模块——
每一份看着都合理，没有两份一样。结果是一本交易账本在一台机器上存在四份，
分别记着 48、45、45、37 笔，页面显示三天前那份，而每次刷新都报「成功」。

模板存在的意义不是省打字，是**让这些决定只做一次**。

平台在起配方那一刻检查契约描述头，**没有就不启动**。

## 下次召回

    frago book recipe-creation
