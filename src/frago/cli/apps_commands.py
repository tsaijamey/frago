"""``frago apps`` —— 内置交付能力清单与调用入口。

apps 是「输入 → 交付成品」的内置能力集合。与 recipe / skill / def 的
区别：apps 只收随 frago 分发的静态内置能力，不做用户可插拔注册。
引擎是每个 app 自己的实现细节，框架只定义契约：``apps use <app> "<输入>"``
产出成品，默认 stdout，``--output`` 落盘。

首个 app 是 mermaid：输入 mermaid 文本 → SVG。渲染走 ``frago browser``
默认的扩展桥——在 agent 浏览器的后台标签里画，画完关组；引擎用包内已分发的
mermaid.min.js（viewer 在用同一份），不引入任何新增体积。
不走 ``-b cdp``：那条只属于 agent_os，9222 上住着舞台演员，
自己起无头实例会跟它抢端口、或把渲染页开进演员的虚拟标签条。
样式读包内 frago-theme.js，与 WebUI、``frago view`` 画出来的图是同一套；
导出的 SVG 多半要贴进白底的文档和幻灯片，所以用浅色那一版。
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

# 渲染专属 tab group。独立于任何用户 group，用完即关。
APPS_GROUP = "frago-apps"

# 单条 frago browser 命令的等待上限（秒）。start 要拉浏览器、等桥握手，给足余量。
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
    """构造 frago browser 命令（默认扩展桥后端，不显式选后端）。"""
    return ["frago", "browser", *args]


def _run_browser(*args: str) -> subprocess.CompletedProcess:
    """执行一条 frago browser 命令并返回结果。"""
    return subprocess.run(  # noqa: S603
        _browser_command(*args),
        capture_output=True,
        text=True,
        check=False,
        timeout=BROWSER_START_TIMEOUT,
    )


def _bridge_connected() -> bool:
    """扩展桥是否已连上：``status`` 退出码为 0 且 JSON 里 ``ok`` 为真。"""
    status = _run_browser("status")
    if status.returncode != 0:
        return False
    try:
        return bool(json.loads(status.stdout).get("ok"))
    except (json.JSONDecodeError, AttributeError):
        return False


def _ensure_browser_up() -> None:
    """保证扩展桥在线（幂等：已连上就跳过）。

    没连上唯一的动作是 ``frago browser start``（可能弹出浏览器窗口，属预期）；
    启动失败时给出可执行的修复指引，不静默。
    """
    if _bridge_connected():
        return

    start = _run_browser("start")
    if start.returncode != 0:
        click.echo("Error: 扩展桥启动失败", err=True)
        click.echo(start.stdout, err=True)
        click.echo(start.stderr, err=True)
        click.echo("[Fix] frago browser start", err=True)
        raise click.ClickException("无法连上渲染用的浏览器扩展桥")


def _mermaid_asset(name: str = "mermaid.min.js") -> str:
    """读包内 mermaid 目录下的脚本（viewer 与 apps 共用同一份，杜绝第二份真相）。

    ``mermaid.min.js`` 是引擎，``frago-theme.js`` 是三处画图共用的样式。
    """
    try:
        # 包内资源用 importlib.resources 定位，不依赖源码路径。
        data = importlib.resources.files(
            "frago.resources.viewer.mermaid"
        ).joinpath(name).read_bytes()
        return data.decode("utf-8")
    except Exception as e:  # pragma: no cover - 资产缺失属打包错误
        raise click.ClickException(
            f"包内 {name} 读取失败：{e}"
        ) from e


def _render_mermaid(mermaid_text: str) -> str:
    """mermaid 文本 → SVG（扩展桥后台标签渲染，画完关组）。

    流程：内联 mermaid.js + 样式脚本 + 用户文本拼单个 HTML → 写临时目录 →
    navigate file:// → exec-js 抓 .mermaid svg outerHTML → 关组、清理。

    页面画完（含样式后处理）才在 body 上打 ``data-done``，画不出来打
    ``data-error``；轮询只认这两个标记，不会抓到后处理之前的半成品。
    """
    engine = _mermaid_asset()
    theme = _mermaid_asset("frago-theme.js")
    escaped = html.escape(mermaid_text)
    document = (
        '<!DOCTYPE html><html><head><meta charset="utf-8"><script>'
        f"{engine}"
        "</script><script>"
        f"{theme}"
        "</script></head><body>"
        f'<div class="mermaid">{escaped}</div>'
        "<script>"
        "mermaid.initialize(fragoMermaid.config('light'));"
        "mermaid.run({querySelector: '.mermaid'}).then(function () {"
        "fragoMermaid.postProcess(document.querySelector('.mermaid svg'));"
        "document.body.dataset.done = '1';"
        "}, function (e) {"
        "document.body.dataset.error = String((e && e.message) || e);"
        "});"
        "</script>"
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

        # 等 mermaid 渲染完成（异步），轮询页面上的完成/出错标记。
        script = (
            'document.body.dataset.error ? "ERROR:" + document.body.dataset.error : '
            '(document.body.dataset.done ? '
            'document.querySelector(".mermaid svg").outerHTML : null)'
        )
        svg: str | None = None
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            result = _run_browser(
                "exec-js", "--group", APPS_GROUP, script, "--return-value"
            )
            value = _extract_exec_result(result)
            if value and value.startswith("ERROR:"):
                raise click.ClickException(
                    f"mermaid 渲染失败：{value.removeprefix('ERROR:').strip()}"
                )
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
        _run_browser("group-close", APPS_GROUP)
        shutil.rmtree(tmpdir, ignore_errors=True)


def _extract_exec_result(result: object) -> str | None:
    """从 exec-js 的 JSON 输出（``{"value": ...}``）中取出返回值。

    result 是 subprocess.CompletedProcess（测试注入同形态 fake），
    只读 returncode 与 stdout 两个属性。值为空或 null 时返回 None。
    """
    if getattr(result, "returncode", None) != 0:
        return None
    stdout: str = getattr(result, "stdout", "") or ""
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("value")
    if value is None or value == "":
        return None
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


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
