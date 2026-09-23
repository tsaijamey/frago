"""结对页在小屏上够不够得着——一条能在本机反复跑的检查。

## 为什么要有它

结对页上「发起」和「加入」都会在顶栏底下展开一块表单，而那块表单比手机屏还高。外层
不给滚，于是确认按钮掉在屏幕下边缘外面，人怎么划都划不到——这一步就走不完。

这个缺陷**只在小屏上出现**，而开发时看的永远是大屏。没有这条检查的后果已经发生过：
改完只能说「应该好了」，真伪要等有人拿另一台机器在小屏上撞一次才知道，同一件事来回
好几轮，而每一轮的代价都由用户付。

## 它怎么测

走 CDP 把视口**真的**设成手机尺寸（``Emulation.setDeviceMetricsOverride``），不是改某个
元素的高度——改元素高度不影响按视口算出来的 CSS 尺寸，量出来的是假的，而假的结论比
没有结论更坏（这一点踩过）。

然后把每一条路走到底，断言两件事：

1. **确认按钮在可视区内**，必要时把沿途每一层能滚的都滚到底——人在小屏上就是这么做的。
   够不着就是这一步走不完。
2. **两列没有被挤没**。表单占满整个高度的话，人看不见自己正在哪一场会话里挑，而那正是
   这一步要他判断的东西。

## 怎么跑

    uv run python src/frago/client/scripts/check_teaming_small_screen.py

要一个开着调试端口的 Chrome。没有就先起一个：``frago browser start -b cdp``。

退出码 0 表示每一档在每个尺寸上都够得着；非 0 会把哪一档在哪个尺寸上够不着原样列出来。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request

try:
    from websocket import create_connection  # type: ignore
except ImportError:  # pragma: no cover - 缺依赖时说清楚怎么补
    print("缺 websocket-client：uv run --with websocket-client python <这个脚本>", file=sys.stderr)
    raise SystemExit(2) from None


#: 测哪几个尺寸。三个都是真机常见的下限。
SCREENS = [
    ("iPhone SE 竖屏", 375, 667),
    ("小安卓机竖屏", 360, 640),
    ("笔记本半屏", 640, 520),
]

#: 每一档走到哪、要够得着哪个按钮。两种语言的说法都收，界面语言切换时这条检查不该失灵。
FLOWS = [
    ("发起 · 用一场现成的", ["Start"], r"Start with this one|用这一场发起"),
    ("发起 · 新开一场", ["Start", "A fresh one"], r"Open one and start|新开并发起"),
    ("加入 · 填码", ["Join with a code"], r"^(Next|下一步)$"),
]


class Page:
    """一个开着的标签页，能发 CDP 命令。"""

    def __init__(self, port: int, url: str) -> None:
        self._port = port
        raw = self._http(f"/json/new?{urllib.parse.quote(url, safe='')}", method="PUT")
        self._id = raw["id"]
        self._ws = create_connection(raw["webSocketDebuggerUrl"], suppress_origin=True)
        self._seq = 0

    def _http(self, path: str, method: str = "GET") -> dict:
        req = urllib.request.Request(f"http://127.0.0.1:{self._port}{path}", method=method)
        with urllib.request.urlopen(req, timeout=10) as res:
            body = res.read().strip()
        # 关标签页那条回的是一句 "Target is closing"，不是 JSON。它不是失败，
        # 但照着 JSON 去解会在收尾时抛一个跟这次检查毫无关系的错。
        if not body.startswith(b"{"):
            return {}
        return json.loads(body)

    def send(self, method: str, params: dict | None = None) -> dict:
        self._seq += 1
        self._ws.send(json.dumps({"id": self._seq, "method": method, "params": params or {}}))
        while True:
            got = json.loads(self._ws.recv())
            if got.get("id") == self._seq:
                if "error" in got:
                    raise RuntimeError(f"{method}：{got['error'].get('message')}")
                return got.get("result", {})

    def js(self, expression: str):
        """在页面里跑一段，把值取回来。"""
        got = self.send(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        if "exceptionDetails" in got:
            raise RuntimeError(got["exceptionDetails"].get("text", "页面里那段代码抛了"))
        return got.get("result", {}).get("value")

    def close(self) -> None:
        try:
            self._ws.close()
        finally:
            self._http(f"/json/close/{self._id}")


def click_by_text(text: str) -> str:
    """点一个写着这些字的按钮。

    **按整段文字的开头对，NEVER 用「包含」。** 这一页上「Start」这个词同时出现在顶栏
    那个按钮和「A fresh one / Start something new together…」那张卡的说明里；用包含去找，
    点中的是后者，于是面板开了又关，看起来像「这一步点不动」，而真正的毛病在检查脚本
    自己身上——排查要绕一大圈。
    """
    return r"""(function(){
      var want=%s;
      var all=[].slice.call(document.querySelectorAll('.page-slot button'));
      var b=all.filter(function(x){
        var t=x.innerText.trim();
        return t === want || t.split('\n')[0].trim() === want;
      })[0];
      if(b && !b.disabled){ b.click(); return true; }
      return false;
    })()""" % json.dumps(text)


def wait_click(page: "Page", text: str, seconds: float = 8.0) -> bool:
    """等这个按钮出现再点。

    NEVER 用固定时长：面板是点完上一步才画出来的，画多久取决于这台机器此刻多忙。
    等固定时长的后果是这条检查自己时灵时不灵，而它的全部价值就在于结论可信。
    """
    deadline = time.time() + seconds
    while time.time() < deadline:
        if page.js(click_by_text(text)):
            return True
        time.sleep(0.25)
    return False


def measure(pattern: str) -> str:
    """那个确认按钮此刻在哪、够不够得着、两列还在不在。"""
    return """(function(){
      var slot=document.querySelector('.page-slot');
      if(!slot) return {ok:false, why:'这一页还没画出来'};
      var re=new RegExp(%s);
      var btn=[].slice.call(slot.querySelectorAll('button')).filter(function(b){
        return re.test(b.innerText.trim());
      })[0];
      if(!btn) return {ok:false, why:'找不到确认按钮'};

      // 沿途滚到底——但**只滚人划得动的那几层**。
      //
      // 这里踩过一次，而且踩得很深：用脚本设 scrollTop，即便那一层是 overflow:hidden
      // 也照样滚得动，于是按钮总能被"滚"进可视区，检查永远是绿的。可人在屏幕上对着
      // 一个 hidden 的容器怎么划都不动——那正是这个缺陷本身。量"程序能不能滚到"，
      // 量的是一件跟人无关的事。
      var node=btn.parentElement;
      while(node && node !== document.body){
        var how=getComputedStyle(node).overflowY;
        var byHand = (how === 'auto' || how === 'scroll' || how === 'overlay');
        if(byHand && node.scrollHeight > node.clientHeight) node.scrollTop = node.scrollHeight;
        node = node.parentElement;
      }
      // 整页那一层也算：body 能滚的话人也划得动。
      if(document.scrollingElement) {
        document.scrollingElement.scrollTop = document.scrollingElement.scrollHeight;
      }

      var r=btn.getBoundingClientRect();
      var floor=window.innerHeight;
      var why='';
      if(r.bottom > floor + 1) why='确认按钮掉在可视区下面，滚不到';
      else if(r.top < -1) why='确认按钮被顶到可视区上面';
      return {
        ok: why === '',
        why: why,
        bottom: Math.round(r.bottom),
        floor: floor,
        columns: !!slot.querySelector('section')
      };
    })()""" % json.dumps(pattern)


def run(site: str, port: int) -> int:
    page = Page(port, f"{site}/#/teaming")
    bad: list[str] = []
    try:
        page.send("Runtime.enable")
        page.send("Page.enable")

        for name, width, height in SCREENS:
            page.send(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": width,
                    "height": height,
                    "deviceScaleFactor": 1,
                    "mobile": width < 500,
                },
            )

            for flow, steps, confirm in FLOWS:
                # **每一档从真正的重载开始，NEVER 只换 hash。**
                #
                # 换 hash 不会重挂这一页，上一档留下的面板仍然开着；这一档再点一次
                # 「发起」，点中的是同一个开关，于是面板被关掉——看起来像「这一步点
                # 不动」，而真正的原因是上一档没收干净。踩过一次，排查绕了一大圈。
                page.send("Page.navigate", {"url": f"{site}/#/teaming"})
                time.sleep(0.6)
                page.send("Page.reload", {"ignoreCache": False})
                time.sleep(3.0)

                walked = True
                for step in steps:
                    if not wait_click(page, step):
                        seen_now = page.js(
                            "document.querySelector('.page-slot').innerText.slice(0,160)"
                        )
                        bad.append(
                            f"{name} · {flow}：点不到「{step}」。"
                            f"此刻页面上是：{' '.join(str(seen_now).split())[:110]}"
                        )
                        walked = False
                        break
                    time.sleep(0.6)
                if not walked:
                    continue

                seen = page.js(measure(confirm))
                if not seen or not seen.get("ok"):
                    why = (seen or {}).get("why", "量不出来")
                    where = ""
                    if seen and seen.get("bottom") is not None:
                        where = f"（按钮底边 {seen['bottom']}，可视区底 {seen['floor']}）"
                    bad.append(f"{name}（{width}×{height}） · {flow}：{why}{where}")
                elif seen.get("columns") is False:
                    bad.append(f"{name} · {flow}：表单把两列挤没了")
                else:
                    print(f"  ✓ {name}（{width}×{height}） · {flow}")
    finally:
        page.close()

    if bad:
        print("\n小屏上这几档走不完：", file=sys.stderr)
        for one in bad:
            print(f"  ✗ {one}", file=sys.stderr)
        return 1
    print("\n每一档在每个尺寸上都够得着。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default="http://127.0.0.1:8093", help="本机 frago 服务的地址")
    ap.add_argument("--port", type=int, default=9222, help="Chrome 的调试端口")
    args = ap.parse_args()
    try:
        return run(args.url.rstrip("/"), args.port)
    except Exception as err:  # noqa: BLE001 — 跑不起来要说清楚是哪一步
        print(f"跑不起来：{err}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
