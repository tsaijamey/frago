"""环境仪表盘上那颗升级按钮：把一样东西升到最新，活派给 agent 干。

**为什么不在这里拼升级命令。** 同一个名字在不同机器上是不同的东西：这台 Mac 上 tmux
和 ffmpeg 归 Homebrew，codex 是个 cask，opencode 是 Cellar 里的 formula，git 是系统自带
的那份，claude 装在用户自己的目录里。换一台 Linux 就全变了。把这些分支写死在服务端，等于
把「机器长什么样」这件事猜一遍，猜错的那次表现是命令报错，而人看到的只是升级失败。

**改成给 agent 一份事实清单，让它自己判断。** 服务端负责的是把上下文备齐——这一样东西
是什么、在 frago 里管哪种能力、本机现在哪一版、外面到哪一版、这条命令的真实落点（连符号
链接指向哪儿一起给，装法从这里就能看出来）、这台机器有哪些包管理器。判断和执行归 agent。

**边界写进任务书，不靠事后检查。** 只动这一样、不许用要密码的提权（无人值守会卡在密码
提示上）、不碰 frago 的源码检出。最后一行必须是一句机器读得懂的结论，服务端据此判成败。

**一次只跑一个。** 升级动的是这台机器上共用的包管理器，两个 agent 同时装东西会互相锁住；
排队跑慢一点，但每一样的成败都说得清。
"""

import asyncio
import logging
import os
import platform
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from frago.server.services.environment_service import (
    EnvironmentService,
    catalog,
    frago_install_source,
    probe_local,
)

logger = logging.getLogger(__name__)

# 每一样东西在 frago 里管什么。这是任务书里最要紧的一句：agent 知道它为什么重要，才不会
# 在升级失败时自作主张换一条路（比如把 tmux 换成别的复用工具）。
PURPOSE: dict[str, str] = {
    "frago": "frago 本体。",
    "git": "取源码、拉更新靠它。frago 本体的安装与升级都要用。",
    "uv": "建 Python 环境、把 frago 装成系统命令。没有它 frago 装不上。",
    "tmux": "派活（frago agent）、主代理、frago remote 全靠它。缺了 worker 永远起不来。",
    "browser": (
        "浏览器自动化（frago browser）。frago 自带一份 Chrome for Testing，"
        "放在 ~/.frago/tools/chrome-for-testing/，不是用户日常那个浏览器。"
    ),
    "ffmpeg": "录标签页、虚拟桌面录制（frago desktop）。缺了只有录制会失败。",
    "gh": "创建私有仓库备份、GitHub 相关操作。",
    "bwrap": "Linux 上跑配方的沙箱。缺了配方会被直接拒绝运行。",
    "claude": "agent 命令行。frago 的会话注入与派活都可以落在它上面。",
    "codex": "agent 命令行。frago 的会话注入与派活都可以落在它上面。",
    "opencode": "agent 命令行。frago 的会话注入与派活都可以落在它上面。",
    "codebuddy": "agent 命令行（WorkBuddy 桌面应用自带）。",
}

# 任务书末尾要求的那一行。服务端只认这一行，其余都是给人看的过程。
RESULT_PREFIX = "RESULT:"

# 每一样东西最多给多久。装包要下载，跨境链路上慢是常态；但一样东西卡住半小时就该收手，
# 否则排在后面的永远轮不到。
ITEM_TIMEOUT_SECONDS = 1800


def _which(name: str) -> str | None:
    from frago.server.services.environment_service import _search_path

    return shutil.which(name, path=_search_path())


def _binary_facts(item_id: str) -> list[str]:
    """这条命令在本机的真实落点。装法基本能从这里看出来。"""
    from frago.server.services.environment_service import _VERSION_COMMANDS

    if item_id == "browser":
        try:
            from frago.browser.backends.extension import cft_binary, cft_root

            binary = cft_binary()
            return [
                f"frago 自带浏览器的根目录：{cft_root()}",
                f"可执行文件：{binary if binary else '（没取到，目录是空的）'}",
                "版本清单在 "
                "https://googlechromelabs.github.io/chrome-for-testing/"
                "last-known-good-versions-with-downloads.json，"
                "取 channels.Stable.downloads.chrome 里本平台那条。",
            ]
        except Exception:
            return ["frago 自带浏览器的位置读不出来。"]

    if item_id == "frago":
        source = frago_install_source()
        return [
            f"frago 命令的位置：{_which('frago') or '（不在 PATH 上）'}",
            f"这份 frago 的安装来源：{source}"
            + ("（本地构建的包，不是从索引装的）" if source == "local" else ""),
        ]

    argv = _VERSION_COMMANDS.get(item_id)
    if not argv:
        return ["这一样没有可执行文件可查。"]
    found = _which(argv[0])
    if not found:
        return [f"`{argv[0]}` 不在 PATH 上，本机没装。"]
    real = os.path.realpath(found)
    lines = [f"`{argv[0]}` 的位置：{found}"]
    if real != found:
        lines.append(f"符号链接指向：{real}")
    lines.append(f"问版本号的命令：{' '.join(argv)}")
    return lines


def _machine_facts() -> list[str]:
    """这台机器上有哪些包管理器。只陈述有没有，装法由 agent 判断。"""
    managers = ["brew", "apt-get", "dnf", "pacman", "zypper", "npm", "uv", "winget"]
    present = [m for m in managers if _which(m)]
    return [
        f"系统：{platform.system()} {platform.machine()}",
        f"本机有的包管理器：{', '.join(present) if present else '（一个都没有）'}",
    ]


def build_brief(item_id: str, current: str | None, latest: str | None) -> str:
    """给一样东西写任务书。

    通篇只有事实和边界，没有一条命令——命令由 agent 按这些事实自己定。
    """
    item = next((i for i in catalog() if i.id == item_id), None)
    name = item.name if item else item_id

    facts = "\n".join(f"- {line}" for line in _binary_facts(item_id) + _machine_facts())

    frago_guard = ""
    if item_id == "frago" and frago_install_source() == "local":
        frago_guard = (
            "\n**这一样现在不能升。** 本机的 frago 是从本地构建的包装上去的，版本号比"
            "线上发布的新；照线上版装回去等于把本地构建覆盖成更旧的东西。"
            f"直接输出 `{RESULT_PREFIX} SKIPPED 本机跑的是本地构建版，升级会覆盖成更旧的线上版`，"
            "什么都不要做。\n"
        )

    return f"""# 把 {name} 升到最新

## 这是什么
{PURPOSE.get(item_id, "frago 运行环境里的一样东西。")}

## 现状
- 本机装的版本：{current or "（没装）"}
- 外面出到的版本：{latest or "（查不到）"}

## 这台机器的事实
{facts}
{frago_guard}
## 你要做的
把它升到最新（没装就装上）。装法自己按上面的事实判断——它现在是从哪儿装的，就从哪儿升。

## 边界
- **只动这一样。** 顺手升级别的东西、清理缓存、改配置，一律不要。
- **不许用需要输入密码的提权。** 这是无人值守跑的，`sudo` 会卡在密码提示上直到超时。
  确实非提权不可，就停下来把结论写成需要真人处理。
- **不要碰 frago 的源码检出目录。** 那是开发用的仓库，与这次升级无关。
- 下载很大（几百 MB）时照做，但在过程里说一句在下什么。

## 怎么算完
装完重新问一次版本号，确认真的变了。**最后一行必须是下面四种之一，前面不要加任何符号：**

{RESULT_PREFIX} OK <升级前的版本> -> <升级后的版本>
{RESULT_PREFIX} SKIPPED <一句话说明为什么不用升>
{RESULT_PREFIX} MANUAL <要用户自己在终端里跑的那一条命令，只写命令本身>
{RESULT_PREFIX} FAILED <一句话说明卡在哪>

MANUAL 用在「你做不了、但人能做」的场合——被本机规则拦下、需要输入密码、要在图形界面里点。
那一行只写命令，界面会原样显示给用户复制，所以不要加解释、不要加提示符、不要加引号。
"""


class UpgradeJob:
    """一批升级的进度。按提交顺序一样一样跑。"""

    def __init__(self, ids: list[str]) -> None:
        self.items: dict[str, dict[str, Any]] = {
            item_id: {"state": "pending", "message": "", "before": None, "after": None}
            for item_id in ids
        }
        self.order = list(ids)
        self.started_at = time.time()
        self.finished_at: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "running": self.finished_at is None,
            "order": self.order,
            "items": self.items,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class EnvironmentUpgradeService:
    """把升级请求排成一队，一样一样交给 agent 去干。"""

    _instance: Optional["EnvironmentUpgradeService"] = None

    def __init__(self) -> None:
        self._job: UpgradeJob | None = None
        self._task: asyncio.Task | None = None

    @classmethod
    def get_instance(cls) -> "EnvironmentUpgradeService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def status(self) -> dict[str, Any]:
        if self._job is None:
            return {"running": False, "order": [], "items": {}, "started_at": None, "finished_at": None}
        return self._job.as_dict()

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self, ids: list[str]) -> dict[str, Any]:
        """开一批升级。已经在跑就原样退回当前进度，不排第二个队。"""
        if self.is_running():
            return {"accepted": False, **self.status()}

        known = {i.id for i in catalog()}
        wanted = [i for i in ids if i in known]
        if not wanted:
            return {"accepted": False, **self.status()}

        self._job = UpgradeJob(wanted)
        self._task = asyncio.create_task(self._run(self._job))
        return {"accepted": True, **self.status()}

    async def _run(self, job: UpgradeJob) -> None:
        env_service = EnvironmentService.get_instance()
        snapshot = await asyncio.to_thread(env_service.snapshot, False)
        versions = {row["id"]: row for row in snapshot["items"]}

        for item_id in job.order:
            row = versions.get(item_id, {})
            before = row.get("current")
            job.items[item_id].update({"state": "running", "before": before})
            try:
                state, message, after = await self._upgrade_one(
                    item_id, before, row.get("latest")
                )
            except Exception as e:
                logger.exception(f"Upgrade of {item_id} blew up")
                state, message, after = "failed", str(e), None
            job.items[item_id].update({"state": state, "message": message, "after": after})

        # 升完把本机那份缓存作废，界面下一次问到的就是新版本号。
        env_service.invalidate_local()
        job.finished_at = time.time()

    async def _upgrade_one(
        self, item_id: str, before: str | None, latest: str | None
    ) -> tuple[str, str, str | None]:
        """派一个 agent 去升这一样，回来判读它最后那一行。"""
        brief = build_brief(item_id, before, latest)

        with tempfile.NamedTemporaryFile(
            "w", suffix=".md", prefix=f"frago-upgrade-{item_id}-", delete=False, encoding="utf-8"
        ) as handle:
            handle.write(brief)
            brief_path = handle.name

        frago = _which("frago")
        if not frago:
            return "failed", "本机 PATH 上找不到 frago 命令，派不出活", None

        try:
            proc = await asyncio.create_subprocess_exec(
                frago,
                "agent",
                "--prompt-file",
                brief_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                stdout, _ = await asyncio.wait_for(
                    proc.communicate(), timeout=ITEM_TIMEOUT_SECONDS
                )
            except TimeoutError:
                proc.kill()
                await proc.wait()
                return "failed", f"超过 {ITEM_TIMEOUT_SECONDS // 60} 分钟没做完，已中止", None
        finally:
            Path(brief_path).unlink(missing_ok=True)

        text = (stdout or b"").decode("utf-8", errors="replace")
        # 退出码 2 是 frago agent 的约定：撞上认证墙或权限门，必须交真人。
        if proc.returncode == 2:
            return "failed", "worker 撞上需要真人处理的门（认证或权限），升级没做", None

        after = await asyncio.to_thread(probe_local, item_id)
        return (*self._read_result(text, before, after), after)

    @staticmethod
    def _read_result(text: str, before: str | None, after: str | None) -> tuple[str, str]:
        """读 worker 最后那一行的结论。

        没写那一行时不当失败：拿升级前后的版本号自己比一次——事情做成了没有，机器上
        的版本号说了算，比 worker 怎么措辞可靠。
        """
        for line in reversed(text.strip().splitlines()):
            stripped = line.strip()
            if not stripped.startswith(RESULT_PREFIX):
                continue
            body = stripped[len(RESULT_PREFIX) :].strip()
            head, _, rest = body.partition(" ")
            head = head.upper()
            if head == "OK":
                return "ok", rest or f"{before} -> {after}"
            if head == "SKIPPED":
                return "skipped", rest
            if head == "MANUAL":
                # 这一档的内容是一条命令，界面原样摆给人复制，所以不加任何修饰。
                return "manual", rest
            return "failed", rest or body

        if after and after != before:
            return "ok", f"{before} -> {after}"
        return "failed", "worker 没有给出结论，版本号也没变"
