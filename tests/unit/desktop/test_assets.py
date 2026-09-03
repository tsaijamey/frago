"""桌面页那四个前端文件。原件是配方 agent_os_ui 的 test_agent_os_ui.py，
搬进本体时大幅缩水：那个配方的三个 mode 里，install（把文件铺到某目录）和
assets（把内容念出来）都没有意义了——文件就在包里，服务端直接从这儿发。
剩下的只有一件事：**这四个文件真的跟着 wheel 走**。

为什么这条要写成断言而不是靠「实测过一次」：打包配置里
``packages = ["src/frago"]`` 已经把整棵包树纳入，底下那张按扩展名列的 include
是叠加的、实际冗余的——所以 .js / .css / .html 今天都进得去。但哪天有人加一条
exclude 把 assets 排掉，wheel 少了这四个文件，装起来一切正常，只有点开桌面页
的那个人看到一张打不开的页面。这条断言就是为那一天写的。
"""

from __future__ import annotations

import hashlib
from importlib.resources import files

from frago.desktop import stage

#: 桌面页的正身。少一个都是一张打不开的页面。
ASSET_NAMES = ("index.html", "style.css", "app.js", "ansi.js")


def test_assets_ship_with_the_package():
    """按包资源取，不按仓库路径取——装到别处也必须找得到。"""
    for name in ASSET_NAMES:
        assert files("frago.desktop").joinpath("assets", name).is_file(), name


def test_asset_files_lists_exactly_those_four_in_name_order():
    assert [p.name for p in stage.asset_files()] == sorted(ASSET_NAMES)


def test_the_page_is_a_page():
    """index.html 得真的是一张 HTML，别哪天被换成一个占位符。"""
    index = files("frago.desktop").joinpath("assets", "index.html").read_text(
        encoding="utf-8")
    assert "<html" in index.lower()


def test_ui_version_covers_every_asset():
    """版本号是这四个文件（名字 + 内容）的函数，一个都不能漏。

    漏掉一个的后果不是报错：那个文件改了而版本号不动，broker 拿版本号做**相等**
    比对，于是把开着旧资产的标签当成新的，几何照收——画面变形而没有一处报错。
    """
    digest = hashlib.sha256()
    for p in stage.asset_files():
        digest.update(p.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(p.read_bytes())
        digest.update(b"\0")
    assert stage.ui_version() == int(digest.hexdigest()[:12], 16)
