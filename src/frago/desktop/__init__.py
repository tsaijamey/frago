"""虚拟桌面舞台：一块可脚本操控、可录屏的假 macOS 桌面。

这块能力从前是两个配方（``agent_os`` 与 ``agent_os_ui``），住在每台机器的
``~/.frago/recipes/`` 下、靠手工同步。于是换一台机器，``frago desktop`` 这条命令在、
能力不在——命令正常应答一句「本机没有虚拟桌面配方」，然后什么也做不了。搬进本体
之后它跟着版本号一起分发：装了 frago 就有虚拟桌面。

包里各是什么
------------
``aos``       短指令入口。``frago desktop <资源> <动词>`` 的全部语义在这儿，
              输出恒为单行 JSON。
``stage``     把舞台拉起来（``up``）、说清它现在什么样（``status``）。
``broker``    采集与操控中枢，长驻子进程：CDP 客户端 + tmux 轮询 + 小服务器。
``registry``  实例台账：身份层（门牌号，永不重算）与运行态层（pid/端口）分离。
``health``    启动自检，只报会静默出错的项。
``refs``      ``page:`` 这一域的寻址判型，broker 与 aos 共用同一份。
``assets/``   桌面页那四个前端文件。服务端直接从这儿发，不再复制到任何地方。

这里只 re-export 三个入口，别的东西按模块名取：``from frago.desktop import broker``
会把 fastapi / uvicorn / websockets / PIL 一起拉进来，那是长驻进程才需要付的钱。
"""

from .aos import main
from .stage import status, up

__all__ = ["main", "status", "up"]
