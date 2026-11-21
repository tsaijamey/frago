# recipe-spec-writing

分类: 效率（AVAILABLE）

## 解决什么问题
agent 直接写 recipe 时容易遗漏边界情况、把读写访问级别混在一起、或顺手决定对外接口。通过 `frago recipe plan` 先写清 `spec.md`，再由 `frago recipe create` 按规格里的机器可读 YAML 块生成继承 `Recipe` 基类的模板，确保接口契约与访问级别只定一次。

## spec.md 文件位置
spec.md 与 recipe.md 同级，放在 recipe 目录内：
  ~/.frago/recipes/atomic/system/<name>/spec.md
  ~/.frago/recipes/atomic/chrome/<name>/spec.md
  ~/.frago/recipes/workflows/<name>/spec.md

> **现行入口**：由 `frago recipe plan <name>` 自动生成最新模板（细节见 `frago book recipe-creation`）。以下「机器读的部分」与「人读的部分」为 `frago-recipe/1` 契约的现行标准格式；旧版 `Inputs / Outputs / Error Scenarios / Test Cases` 分段形态已淘汰，仅供兼容非 Python 旧型配方（`chrome-js` / `shell`）参考。

## spec.md 必需结构（现行 `frago-recipe/1` 标准形态）

### 1. 机器读的部分（YAML 块）
`frago recipe create` 直接解析这一段 YAML 块长出模板，字段对齐 `recipe-creation`：

```yaml
type: atomic          # atomic（一件事）| workflow（串起几件事）
runtime: python       # python | chrome-js | shell

# 每个 mode 一件事、一个访问级别（三选一）：
#   export  -> 生成 @export 装饰器（只读契约，别的模块和页面都读得到，MUST 只读）
#   action  -> 生成 @action 装饰器（页面可触发，允许干活；page: false 时禁止写 action）
#   留空    -> 不标装饰器（仅主人可跑，默认）
modes:
  status: export
  save: action
  refresh:

default_mode:         # 不写 mode 时跑哪一个；留空则为上面第一个
imports: {}           # 用了谁的哪个只读口，例：cn_etf_data_feed: [status, read]
page: false           # 是否生成 assets/ 空页面骨架；整行不写按「要」处理
```

- 访问级别写入每个 `mode_*` 方法装饰器（`@export` / `@action` / 不标）；**NEVER** 在 `spec.md`、`recipe.md` 或类属性里手写 `exports` / `page_actions` 名单。
- 规格自相矛盾时 `create` 当场拒绝：级别超出 `export` / `action` / 留空三选一、`default_mode` 不在 `modes` 里、或 `page: false` 却给某个 mode 写了 `action`。

### 2. 人读的部分
- **它解决什么问题**：一句话说清谁在什么时候会需要它。
- **每个 mode 做什么**：列出每个 mode 的输入、输出、开给谁（`export` / `action` / 只有主人）。
- **它不做什么**：写清边界，防止后续扩展越位。
- **数据**：自己存什么走平台交代的落点（`self.data_dir` / `self.store`），NEVER 自拼路径；跨模块拿数据走 `imports` 声明 + `self.ask`，NEVER 读对方文件。
- **出错怎么办**：区分致命（`raise self.fail(...)`，退出码非 0）与不致命（`self.warn(...)`，不影响 ok）。
- **怎么验**：写成能直接执行的命令与断言（如 `frago recipe run <name> --params '{"mode":"status"}'`），每条写明依据哪条规则。

### 3. 旧形态兼容说明（仅 `chrome-js` / `shell` 等无模板配方参考）
早先未走 `Recipe` 基类模板的规格曾使用 `Goal / Type & Runtime / Inputs / Outputs / Error Scenarios / Test Cases / Chrome-JS 专属 / Workflow 专属` 分段。新写 Python 配方一律使用上面 `plan` 生成的 `modes / default_mode / imports / page` 形态；`create` 对新形态解析失败会直接退出。

## 怎么从一句话需求推导

  1. 提取动词与对象 → 确定每个 `mode` 做什么
  2. 判断是否需要浏览器与是否编排多步 → 选 `type`（`atomic` / `workflow`）与 `runtime`
  3. 逐个 mode 定访问级别 → 只读对外开标 `export`、页面按钮触发标 `action`、其余留空（仅主人）
  4. 判断是否跨模块拿数据 → 填写 `imports`
  5. 判断是否需要交互页面 → 设置 `page`（`false` 或省略）
  6. 写清边界（不做什么）、数据落点、出错处理与可执行验收命令

## 不做什么
- spec 只定义需求与接口契约，不写实现代码
- 不手动新建 `recipe.md` 或 `recipe.py`——一律交给 `frago recipe create` 从 spec 生成模板
- 不再在 spec 或 `recipe.md` 里手写 `exports` / `page_actions` 名单
