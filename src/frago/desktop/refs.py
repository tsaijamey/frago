"""`page:` 这一域的寻址判型。broker 与 aos 共用同一份。

为什么单独成一个模块
--------------------
判型此前在三处各抄一遍：``broker.resolve_ref``（鼠标/点击）、
``broker.camera_target``（取景）、``aos._ref_probe_step``（语义等待）。
三份判据必然漂移，而漂移的表现极难归因——同一个字符串，`mouse to` 找得到、
`camera focus` 找不到，看上去像页面问题，实际是两段代码对同一个 ref 给出了
不同解释。判型只该有一处。

判型为什么不能靠引号
--------------------
原来的判据是"这一截首尾是不是双引号"：是就按可见文字找，不是就当 CSS 选择器。
它在 JSON 里成立，在命令行上不成立——``--ref page:"某段文字"`` 走一趟 shell，
双引号被吃掉，送到这里的是不带引号的裸串，于是被判成选择器；而那段中文/英文
文字当然不是合法选择器，一路走到"ref 未命中"。照字面读，那句话说的是
"页面上没这个元素"，于是人去改选择器、加等待、怀疑页面没加载完——**排查方向
从第一步就偏了**，真因在一层之外。

现在的判据是**内容本身**，引号只是其中一种显式写法：

    page:"文字"      引号裹住 → 按可见文字找（原样保留，既有脚本一个字不用改）
    page:text:文字   显式按文字找（不依赖引号，命令行上安全）
    page:css:选择器  显式按选择器找（关掉回退，选择器写错就报选择器写错）
    page:裸串        先当选择器解析；解析不成或零命中，再当可见文字找

裸串那条回退只在**今天必然报错**的位置上生效：选择器命中了就照旧走选择器，
命中不了原本就是一句 RefError。所以它不会改变任何一条现在能跑通的调用，
只会把原本的失败变成成功——这是"改语义"里代价最小的一种形状。
"""

from __future__ import annotations

PAGE_PREFIX = "page:"
TEXT_PREFIX = "text:"
CSS_PREFIX = "css:"

#: 写法一览，进回执的 hint 与错误消息，两处引同一份，别各写各的。
FORMS_HINT = (
    'page:"文字"（引号裹住，JSON 里最直接）、'
    "page:text:文字（显式按文字，命令行上不怕引号被 shell 吃掉）、"
    "page:css:选择器（显式按选择器，写错就报写错）、"
    "page:裸串（先当选择器，不成再当文字）"
)


def is_page_ref(ref: str) -> bool:
    return isinstance(ref, str) and ref.strip().startswith(PAGE_PREFIX)


def page_body(ref: str) -> str:
    """剥掉 `page:` 前缀，剩下要判型的那一截。"""
    return ref.strip()[len(PAGE_PREFIX):].strip()


def parse_page_ref(arg: str) -> dict:
    """把 `page:` 后面那一截解析成一份寻址计划。

    ``attempts`` 是按顺序要试的 (怎么找, 找什么)，第一个命中的就是答案。
    只有裸串形态有两个，其余形态都只有一个——显式写法就该只走它说的那条路，
    回退在那里是帮倒忙：人明说了按选择器找，却悄悄按文字命中一个别的元素，
    比直接报错更难查。
    """
    arg = (arg or "").strip()
    if not arg:
        return {"raw": arg, "form": "empty", "attempts": [],
                "why": "page: 后面是空的"}
    if len(arg) >= 2 and arg[0] == '"' and arg[-1] == '"':
        body = arg[1:-1]
        return {"raw": arg, "form": "quoted", "attempts": [("text", body)],
                "why": "首尾有双引号 → 按可见文字找"}
    if arg.startswith(TEXT_PREFIX):
        body = arg[len(TEXT_PREFIX):].strip()
        return {"raw": arg, "form": "text", "attempts": [("text", body)],
                "why": "text: 前缀 → 按可见文字找"}
    if arg.startswith(CSS_PREFIX):
        body = arg[len(CSS_PREFIX):].strip()
        return {"raw": arg, "form": "css", "attempts": [("selector", body)],
                "why": "css: 前缀 → 按 CSS 选择器找，不回退"}
    return {"raw": arg, "form": "bare",
            "attempts": [("selector", arg), ("text", arg)],
            "why": "裸串 → 先当 CSS 选择器解析，解析不成或零命中再当可见文字找"}


def matched_note(form: str, matched_by: str | None, needle: str | None) -> str | None:
    """命中之后要不要多说一句。

    只有"裸串按文字回退命中"这一种要说：调用方写的时候心里想的可能是选择器，
    而它实际是按文字命中的——两者命中的元素完全可能不是同一个，回执里不说破，
    就又变成一次"看上去正常"的错。
    """
    if form == "bare" and matched_by == "text":
        return (f"{needle!r} 不是能命中元素的 CSS 选择器，已按**可见文字**找到目标。"
                f"要锁死按文字找就写 page:text:{needle}；"
                f"要锁死按选择器找就写 page:css:{needle}")
    return None


def miss_message(ref: str, tried: list[dict]) -> str:
    """全都没命中时说清楚"我都试了什么、各是什么结果"。

    只说"未命中"是没法自救的——那句话读起来像"页面上没这个元素"，而真因
    可能是这一截压根不是合法选择器。把每一跳摊开，判型这一层就不再是黑盒。
    """
    if not tried:
        # `page:` 后面什么都没有。这不是"没找到"，是这条 ref 压根没说要找什么，
        # 报成未命中会让人去页面上找一个不存在的问题。
        return f"page ref 是空的：{ref}——page: 后面要跟目标。写法：{FORMS_HINT}"
    parts = []
    for t in tried:
        needle = t.get("needle")
        if t.get("how") == "selector":
            if t.get("valid_selector") is False:
                parts.append(f"当 CSS 选择器解析 `{needle}` —— 它不是合法选择器")
            else:
                parts.append(f"当 CSS 选择器查 `{needle}` —— 合法，但页面上没有匹配的元素")
        else:
            parts.append(f"当可见文字查 {needle!r} —— 页面上没有含这段文字的元素")
    body = f"page ref 未命中：{ref}；试过 " + "；".join(parts)
    if any(t.get("how") == "selector" and t.get("valid_selector") is False
           for t in tried):
        body += ("。命令行上的双引号会被 shell 吃掉，"
                 '`--ref page:"文字"` 送到这里就是不带引号的裸串；'
                 "按文字找写 `--ref page:text:文字`，"
                 """或者把双引号裹进单引号 `--ref 'page:"文字"'`""")
    return body
