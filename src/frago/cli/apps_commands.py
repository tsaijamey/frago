"""``frago apps`` —— 内置交付能力清单与调用入口。

apps 是「输入 → 交付成品」的内置能力集合。与 recipe / skill / def 的
区别：apps 只收随 frago 分发的静态内置能力，不做用户可插拔注册。
引擎是每个 app 自己的实现细节，框架只定义契约：``apps use <app> "<输入>"``
产出成品，默认 stdout，``--output`` 落盘。

首个 app 是 mermaid：输入 mermaid 文本 → SVG。渲染走 ``frago browser
-b cdp`` 无头模式——复用系统 Chromium + 包内已分发的 mermaid.min.js
（viewer 在用同一份），不弹用户浏览器窗口、不引入任何新增体积。
"""

from __future__ import annotations

import html
import importlib.resources
import json
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import click

from .agent_friendly import AgentFriendlyCommand, AgentFriendlyGroup

# 无头渲染专属 tab group。独立于任何用户 group，用完即关。
APPS_GROUP = "frago-apps"

# 浏览器启动/停止的等待上限（秒）。首次起浏览器要 seed profile，给足余量。
BROWSER_START_TIMEOUT = 60


@dataclass
class App:
    """一个交付能力单元。

    render 是「输入文本 → 成品文本」的可调用；registry 直接持有，
    ``apps use`` 拿到即可调，不另设第二入口。
    """

    name: str
    description: str
    input_kind: str
    output_kind: str
    render: Callable[[str], str]


def _browser_command(*args: str) -> list[str]:
    """构造 frago browser 命令（-b cdp 显式选无头后端）。"""
    return ["frago", "browser", "-b", "cdp", *args]


def _run_browser(*args: str) -> subprocess.CompletedProcess:
    """执行一条 frago browser 命令并返回结果。"""
    return subprocess.run(  # noqa: S603
        _browser_command(*args),
        capture_output=True,
        text=True,
        check=False,
        timeout=BROWSER_START_TIMEOUT,
    )


def _browser_running() -> bool:
    """检查 CDP 无头浏览器是否已在跑（9222 端口是否在听）。

    直接探测端口，不依赖 status 命令的日志格式——``-b cdp status``
    输出的是日志行不是 JSON，按字符串解析易碎。
    """
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", 9222)) == 0


def _ensure_browser_up() -> None:
    """保证 -b cdp 无头浏览器在跑（幂等：已在跑就跳过）。

    启动失败时给出可执行的修复指引，不静默。
    """
    if _browser_running():
        return

    start = _run_browser("start", "--headless")
    if start.returncode != 0:
        click.echo("Error: 无头浏览器启动失败", err=True)
        click.echo(start.stdout, err=True)
        click.echo(start.stderr, err=True)
        click.echo("[Fix] frago browser -b cdp start --headless", err=True)
        raise click.ClickException("无法启动无头渲染浏览器")


def _mermaid_asset() -> str:
    """读包内 mermaid.min.js（viewer 与 apps 共用同一份，杜绝第二份真相）。"""
    try:
        # 包内资源用 importlib.resources 定位，不依赖源码路径。
        data = importlib.resources.files(
            "frago.resources.viewer.mermaid"
        ).joinpath("mermaid.min.js").read_bytes()
        return data.decode("utf-8")
    except Exception as e:  # pragma: no cover - 资产缺失属打包错误
        raise click.ClickException(
            f"包内 mermaid.min.js 读取失败：{e}"
        ) from e


def _render_mermaid(mermaid_text: str) -> str:
    """mermaid 文本 → SVG（无头渲染，不打扰用户）。

    流程：内联 mermaid.js + 用户文本拼单个 HTML → 写临时目录 →
    navigate file:// → exec-js 抓 .mermaid svg outerHTML → 清理。
    """
    asset = _mermaid_asset()
    escaped = html.escape(mermaid_text)
    document = (
        "<!DOCTYPE html><html><head><script>"
        f"{asset}"
        "</script></head><body>"
        f'<div class="mermaid">{escaped}</div>'
        "<script>mermaid.initialize({startOnLoad:true});</script>"
        "</body></html>"
    )

    tmpdir = tempfile.mkdtemp(prefix="frago-apps-mermaid-")
    try:
        html_path = Path(tmpdir) / "render.html"
        html_path.write_text(document, encoding="utf-8")

        _ensure_browser_up()

        nav = _run_browser(
            "navigate", html_path.as_uri(), "--group", APPS_GROUP
        )
        if nav.returncode != 0:
            raise click.ClickException(f"导航渲染页面失败：{nav.stderr.strip()}")

        # 等 mermaid 渲染完成（异步初始化），轮询 SVG 出现。
        script = (
            'document.querySelector(".mermaid svg") ? '
            'document.querySelector(".mermaid svg").outerHTML : null'
        )
        svg: str | None = None
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            result = _run_browser(
                "exec-js", "--group", APPS_GROUP, script, "--return-value"
            )
            value = _extract_exec_result(result)
            if value:
                svg = value
                break
            time.sleep(0.5)

        if not svg:
            raise click.ClickException(
                "mermaid 渲染失败：页面未产出 SVG（mermaid 语法错误或渲染异常）"
            )
        return svg
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _extract_exec_result(result: object) -> str | None:
    """从 exec-js 输出中提取 `Execution result: <值>` 后的内容。

    result 是 subprocess.CompletedProcess（测试注入同形态 fake），
    只读 returncode 与 stdout 两个属性。
    """
    if getattr(result, "returncode", None) != 0:
        return None
    stdout: str = getattr(result, "stdout", "") or ""
    for line in stdout.splitlines():
        if "Execution result:" in line:
            _, _, value = line.partition("Execution result: ")
            value = value.strip()
            if value and value != "None":
                return value
    return None


# ── 内置 app 注册表（静态，不可插拔） ────────────────────────────────

_APPS: dict[str, App] = {
    "mermaid": App(
        name="mermaid",
        description="把 mermaid 图表文本渲染成 SVG",
        input_kind="mermaid 文本",
        output_kind="SVG",
        render=_render_mermaid,
    ),
}


def _list_apps() -> list[App]:
    return list(_APPS.values())


@click.group(name="apps", cls=AgentFriendlyGroup)
def apps_group() -> None:
    """Built-in delivery capabilities: input → finished artifact."""


@apps_group.command(name="list", cls=AgentFriendlyCommand)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json"], case_sensitive=False),
    default="table",
    help="Output format",
)
def apps_list(output_format: str) -> None:
    """List all built-in apps."""
    apps = _list_apps()
    if output_format == "json":
        click.echo(json.dumps(
            [
                {
                    "name": a.name,
                    "description": a.description,
                    "input": a.input_kind,
                    "output": a.output_kind,
                }
                for a in apps
            ],
            ensure_ascii=False,
            indent=2,
        ))
        return

    if not apps:
        click.echo("No apps found")
        return
    for a in apps:
        click.echo(f"- {a.name}")
        click.echo(f"  {a.description}")
        click.echo(f"  input: {a.input_kind} → output: {a.output_kind}")
        click.echo()


@apps_group.command(name="use", cls=AgentFriendlyCommand)
@click.argument("name")
@click.argument("input_text")
@click.option(
    "--output",
    "output_path",
    type=click.Path(dir_okay=False),
    help="Write the artifact to a file instead of stdout",
)
def apps_use(name: str, input_text: str, output_path: str | None) -> None:
    """Run a built-in app: ``frago apps use <app> "<input>"``."""
    app = _APPS.get(name)
    if app is None:
        click.echo(
            f"Error: unknown app '{name}'. "
            f"Available: {', '.join(sorted(_APPS))}",
            err=True,
        )
        sys.exit(2)

    artifact = app.render(input_text)

    if output_path:
        Path(output_path).write_text(artifact, encoding="utf-8")
        click.echo(f"Wrote {len(artifact)} bytes to {output_path}")
    else:
        click.echo(artifact)
