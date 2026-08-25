"""The file a recipe starts life as.

A recipe used to start as an agent prompt: `frago recipe create` wrote no
files, it told an agent to go read the book and produce some. Whatever came out
was a recipe. That is where three hundred divergent solutions to the same four
problems came from — each author worked out again where to write, how to
report, how to reach another recipe, and each answer looked reasonable on its
own.

So creation now produces a file, and the agent fills in the middle of it. What
the template carries is not a style preference; it is the parts that must be
identical across every module for the system to be a system:

* the header that says which contract this file follows
* the base class, so the contract is inherited rather than reimplemented
* the exported surface, declared and therefore checkable
* an empty page, so a module that grows a UI has one shape to grow into

The agent's job is the middle: what this module actually does. Everything
around it is already decided, which is the point — a decision that is made once
cannot be made differently three hundred times.
"""

from __future__ import annotations

from frago.recipes.birth import CONTRACT, HEADER

SPEC_MD = """# {name} 规格

> 这份规格由 frago recipe plan 生成，`frago recipe create {name}` 会读它。
> **下面几个字段是给机器读的，写什么，模板里就长出什么。**
> 想清楚再写：改代码容易，改一个已经被别人依赖的接口难。

## 机器读的部分

```yaml
type: {type}          # atomic（一件事）| workflow（串起几件事）
runtime: python

# 这个模块能做哪几件事。一个 mode 一件事，第一个是默认。
modes:
  - status

# 别的模块能调哪几个 mode。MUST 是只读的：
# 不触网、不重算、不改状态、不开浏览器——别人每 5 分钟问一次也不会出事。
# 不确定要不要开放就先留空，开出去容易收回来难。
exports: []

# 用了谁的哪个口。写下来，对方才知道自己正在被谁读。
# 例：cn_etf_data_feed: [status, read]
imports: {{}}

# 要不要一张页面。要的话 create 会生成空页面骨架。
page: false
```

## 人读的部分

### 它解决什么问题

TODO：一句话。说清楚**谁**在**什么时候**会需要它。

### 每个 mode 做什么

| mode | 输入 | 输出 | 只读？ |
|---|---|---|---|
| status | — | TODO | 是 |

### 它不做什么

TODO：写清边界比写清能力更省事——下一个人照着扩展时，知道哪儿不该伸手。

### 数据

它自己要存什么（走平台交代的落点，NEVER 自己拼路径）；
要别的模块的数据就走 imports 声明 + 接口调用，NEVER 读对方的文件。

### 出错怎么办

逐个场合写清楚：**什么情况 → 报什么 → 数据动不动**。

分两类，NEVER 混在一起：

- **致命**——答案作废。`raise self.fail(...)`，退出码非 0。
- **不致命**——答案还有用。`self.warn(...)`，进 warnings，不影响 ok。
  一个文件坏了，不该让另外二十五个从页面上消失。

| 情况 | 怎么报 | 数据 |
|---|---|---|
| 平台没交代落点 | 基类抛 NoLandingSpot，**配方不接不兜底** | 不动 |
| 账本解不动 | 致命 | **NEVER 覆盖重建**，原文一个字节不动 |
| 缺必填参数 | 致命，一次报全，不要报一个等人再来 | 不动 |
| TODO：这个配方特有的 | | |

### 怎么验

写成**能直接跑的命令**，一条一个断言。规格里的每个 mode 至少一条，
边界那几条也要有——写了「不做什么」却没有对应的验，等于没写。

**每一条都要写清它验的是上面哪条规则。** 这不是形式：

> 「今天标成没做 → 最长连续 = 4」
> 依据：第 2 条「只有做了才续得上」+ 第 4 条「一律在全量记录上算」

写依据的时候会发现算不出 4 来——按那两条规则实际是 3。**期望值是拍脑袋写的，
规则是想清楚的，两者对不上时错的通常是期望值。** 不写依据就发现不了，
照着验会得出「配方错了」的结论，而真正错的是规格。

三个 agent 里已经有两个撞上这个，各自花了时间去证明是规格错了不是自己错了。

```bash
frago recipe run {name} --params '{{"mode":"status"}}'   # 期望：... 依据：第 N 条
```

跨天、跨周、并发这类只在特定时刻才错的，单独列出来怎么造那个时刻。

**交付之前把这一节从头跑一遍。** 跑不通的先改规格，别留给下一个人。
"""


RECIPE_MD = """---
name: {name}
type: {type}
runtime: python
version: 0.1.0
description: "{description}"
use_cases:
  - "TODO：一句话说清什么时候该用它"
output_targets:
  - stdout
# 别的模块可以调本模块的哪些 mode。导出的 mode MUST 只读：
# 不触网、不重算、不改状态、不开浏览器——那是别人每 5 分钟问一次也不会出事的口。
exports: {exports}
# 本模块用了谁的哪个口。写下来，对方才知道自己正在被谁读。
imports: {imports}
inputs:
  mode:
    type: string
    required: false
    description: "{modes_doc}"
---
# {name}

TODO：这个模块解决什么问题。

## 它做什么

TODO

## 它不做什么

TODO：写清边界比写清能力更省事——下一个人照着扩展时，知道哪儿不该伸手。
"""

RECIPE_PY = '''#!/usr/bin/env python3
{header}
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""{description}

TODO：这个模块解决什么问题、为什么这么解。
"""

from frago_recipe import Recipe


class {cls}(Recipe):
    """TODO：一句话说清这个模块是什么。"""

    name = "{name}"
    version = "0.1.0"

    #: 本模块能做的事。第一个是默认。
    modes = {modes}

    #: 别的模块能调哪几个。导出的 MUST 只读——不触网、不重算、不改状态。
    #: 内核在总线上按这份声明放行，没导出的一律调不到。
    exports = {exports}

    #: 用了谁的哪个口。NEVER 自己去读别的模块的文件：对方不知道自己正在被读，
    #: 它改自己的东西时看不到任何提示，断裂会发生在跟改动毫无关系的地方。
    imports = {imports}

{methods}

{cls}.main()
'''

#: One method per declared mode. Generated rather than left to the author,
#: because a mode declared and not implemented is the failure that sent a
#: read-only probe into the middle of a state machine that called a live API.
_METHOD = '''    def mode_{safe}(self) -> dict:
        """TODO：{mode} 做什么。{readonly}

        自己的数据走 self.store（落点由平台交代，NEVER 自己拼路径）。
        要别的模块的数据走 self.ask(模块名, mode)，先在 imports 里声明。
        跑得久就 self.progress("...")，出了不致命的问题就 self.warn("...")。
        """
        raise self.fail("mode_{safe} 还没写")
'''


def _method(mode: str, exported: bool) -> str:
    note = ("这个 mode 导出给别的模块，MUST 只读："
            "不触网、不重算、不改状态、不开浏览器。") if exported else ""
    return _METHOD.format(safe=mode.replace("-", "_"), mode=mode, readonly=note)


def _py_tuple(items: list) -> str:
    if not items:
        return "()"
    inner = ", ".join(f'"{i}"' for i in items)
    return f"({inner},)" if len(items) == 1 else f"({inner})"


def _py_imports(imports: dict) -> str:
    if not imports:
        return "{}"
    parts = [f'"{k}": {_py_tuple([str(m) for m in (v or [])])}'
             for k, v in imports.items()]
    return "{" + ", ".join(parts) + "}"


def _yaml_list(items: list) -> str:
    return "[]" if not items else "\n" + "\n".join(f"  - {i}" for i in items)


def _yaml_map(m: dict) -> str:
    if not m:
        return "{}"
    out = []
    for k, v in m.items():
        out.append(f"  {k}:")
        out += [f"    - {one}" for one in (v or [])]
    return "\n" + "\n".join(out)


PAGE_HTML = """<!doctype html>
<meta charset="utf-8">
<title>{name}</title>
<link rel="stylesheet" href="app.css">
<main id="app">
  <h1>{name}</h1>
  <p class="hint">这张页面还没写。它是前端，配方是后端。</p>
  <pre id="state"></pre>
</main>
<script src="app.js"></script>
"""

PAGE_JS = """// 这张页面是前端，配方是后端，两者只通过接口说话。
//
// NEVER 在这里读文件路径。页面拿到绝对路径就是前端伸手进后端的文件系统：
// 访客机器上没有那个文件；能读任意路径的接口对访客一律关死；而且配方的落点
// 一挪，页面还在读老地方，每次刷新都显示成功。
//
// 要数据就调本配方导出的只读 mode，跟别的模块调它走的是同一个口。
// 没导出的 mode 调不到，会收到 403——那不是 bug，是内核在挡。

async function ask(mode, params = {}) {
  const r = await fetch(`api/${mode}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || `${mode} 失败：${r.status}`);
  if (!body.ok) throw new Error(body.error?.message || `${mode} 没给出结果`);
  return body.data;
}

// 一个输入框边打字边搜的时候，先发的请求可能后到——不比一下序号，页面会
// 显示上一次的结果。这种错只在手快的时候出现，平时测基本撞不上：
//
//   let seq = 0;
//   async function search(kw) {
//     const mine = ++seq;
//     const data = await ask("search", { keyword: kw });
//     if (mine !== seq) return;          // 已经有更新的请求发出去了，这份作废
//     render(data);
//   }

// 首屏：配方 publish 过的渲染状态在 config.json 里，先渲染它，页面立刻有东西看；
// 再调接口拿实时数据。两步分开是因为发布状态是快照，接口才是当下。
async function boot() {
  const box = document.getElementById("state");
  try {
    const cfg = await fetch("config.json").then((r) => r.json());
    box.textContent = JSON.stringify(cfg.state ?? cfg, null, 2);
  } catch {
    box.textContent = "（还没发布过页面状态）";
  }
  // TODO: 换成这个配方真正导出的 mode
  // try {
  //   const data = await ask("status");
  //   render(data);
  // } catch (e) {
  //   box.textContent = e.message;
  // }
}

boot();
"""

PAGE_CSS = """:root { color-scheme: light dark; }
body { font: 15px/1.6 system-ui, sans-serif; margin: 0; padding: 2rem; }
#app { max-width: 60rem; margin: 0 auto; }
h1 { font-size: 1.4rem; margin: 0 0 .5rem; }
.hint { opacity: .6; }
pre { overflow-x: auto; padding: 1rem; border-radius: .5rem;
      background: rgba(127,127,127,.12); }
"""


def class_name(recipe_name: str) -> str:
    """A class name from a recipe name. ``etf_dma_signal_push`` → ``EtfDmaSignalPush``."""
    parts = [p for p in recipe_name.replace("-", "_").split("_") if p]
    return "".join(p[:1].upper() + p[1:] for p in parts) or "MyRecipe"


def render_spec(name: str, *, kind: str = "atomic") -> str:
    """The spec a new recipe starts from. What `frago recipe plan` lays down.

    Planning used to write nothing: it handed an agent a prompt and whatever
    prose came back was the spec. `create` then read that prose and produced
    code from it, which meant the two halves of the pipeline agreed only by
    luck — the spec could describe modes that never got declared, or declare an
    exported surface that the code never exposed, and nothing anywhere noticed.

    So the spec now has a machine-readable half. What is written there is what
    `create` builds: the modes become methods, the exported surface becomes the
    declaration the hub enforces, the imports become the dependency both sides
    can see. Deciding those things is the actual work of planning; the prose
    around them is for the person who has to maintain it afterwards.
    """
    return SPEC_MD.format(name=name, type=kind)


def read_spec(spec: str) -> dict:
    """Pull the machine-readable half out of a spec.

    Missing or unparseable comes back as an empty dict rather than an error: a
    spec that predates this, or one somebody wrote by hand, should still
    produce a recipe. It produces the plain template instead of a filled-in
    one, and that difference is visible in what gets generated.
    """
    import re

    import yaml

    m = re.search(r"```yaml\n(.*?)```", spec, re.S)
    if not m:
        return {}
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def render(name: str, *, description: str = "TODO：一句话说清它做什么",
           kind: str = "atomic", with_page: bool | None = None,
           spec: dict | None = None) -> dict[str, str]:
    """The files a new recipe starts as, as ``{relative path: content}``.

    ``spec`` is the machine-readable half of what planning decided. What it
    says, this builds — so the two halves of the pipeline cannot drift apart
    while both look correct.
    """
    spec = spec or {}
    cls = class_name(name)
    kind = spec.get("type") or kind
    modes = [str(m) for m in (spec.get("modes") or ["status"]) if m]
    exports = [str(e) for e in (spec.get("exports") or []) if e]
    imports = spec.get("imports") or {}
    if with_page is None:
        with_page = bool(spec.get("page", True))

    bad = [e for e in exports if e not in modes]
    if bad:
        raise ValueError(
            f"规格里导出了 {'、'.join(bad)}，但 modes 里没有它们。"
            f"导出的必须是这个模块真有的 mode。"
        )

    files = {
        "recipe.md": RECIPE_MD.format(
            name=name, type=kind, description=description,
            exports=_yaml_list(exports), imports=_yaml_map(imports),
            modes_doc=" | ".join(modes),
        ),
        "recipe.py": RECIPE_PY.format(
            header=HEADER, name=name, cls=cls, description=description,
            modes=_py_tuple(modes), exports=_py_tuple(exports),
            imports=_py_imports(imports),
            methods="\n".join(_method(m, m in exports) for m in modes),
        ),
    }
    if with_page:
        files["assets/index.html"] = PAGE_HTML.format(name=name)
        files["assets/app.js"] = PAGE_JS
        files["assets/app.css"] = PAGE_CSS
    return files


__all__ = ["render", "class_name", "CONTRACT"]
