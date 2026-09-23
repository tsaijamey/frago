"""参数大了走标准输入，不走命令行。

Linux 对单个命令行参数卡 131072 字节，超了进程起不来；配方的参数是整段 JSON 塞进
一个参数里，``json.dumps`` 还把每个中文字写成六个字节。vibe teaming 的中继因此一侧
推送连续两个多小时起不来。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from frago.recipes import runner as runner_mod
from frago.recipes.runner import ARGV_PARAMS_LIMIT, PARAMS_FROM_STDIN, RecipeRunner

RUNTIME = Path(runner_mod.__file__).parent / "runtime"

ECHO_RECIPE = '''
from frago_recipe import Recipe, action

class Echo(Recipe):
    name = "echo"

    @action
    def mode_echo(self) -> dict:
        return {"size": len(self.params.get("blob") or "")}

Echo.main()
'''


def _run_echo(tmp_path: Path, argv: list[str], stdin: str | None) -> dict:
    script = tmp_path / "recipe.py"
    script.write_text(ECHO_RECIPE, encoding="utf-8")
    done = subprocess.run(
        [sys.executable, str(script), *argv],
        input=stdin, capture_output=True, text=True, timeout=60,
        env={"PYTHONPATH": str(RUNTIME), "PATH": "/usr/bin:/bin"},
    )
    assert done.returncode == 0, done.stderr
    for line in reversed(done.stdout.strip().splitlines()):
        try:
            got = json.loads(line)
        except json.JSONDecodeError:
            continue
        body = got.get("result", got)
        if isinstance(body, dict) and "data" in body:
            return body["data"]
    raise AssertionError(f"没读到结果：{done.stdout!r}")


def test_基类认得命令行上那个减号从标准输入读参数(tmp_path: Path):
    blob = "中" * 50_000  # json.dumps 之后约 300KB，放命令行在 Linux 上起不来
    got = _run_echo(tmp_path, [PARAMS_FROM_STDIN], json.dumps({"mode": "echo", "blob": blob}))
    assert got == {"size": 50_000}


def test_小参数照旧走命令行(tmp_path: Path):
    got = _run_echo(tmp_path, [json.dumps({"mode": "echo", "blob": "abc"})], None)
    assert got == {"size": 3}


def _cmd_and_stdin(tmp_path: Path, params: dict) -> tuple[list[str], str | None]:
    runner = RecipeRunner(registry=MagicMock(), project_root=tmp_path)
    seen: dict = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"], seen["input"] = cmd, kwargs.get("input")
        return subprocess.CompletedProcess(cmd, 0, stdout='{"ok": true}', stderr="")

    with patch.object(runner, "_confine", side_effect=lambda cmd, *a, **k: cmd), \
            patch("frago.recipes.runner.subprocess.run", side_effect=fake_run), \
            patch("frago.recipes.runner._unwrap", return_value={}):
        runner._run_python("echo", tmp_path / "recipe.py", params, {}, False)
    return seen["cmd"], seen["input"]


def test_运行器把大参数改走标准输入(tmp_path: Path):
    params = {"blob": "中" * (ARGV_PARAMS_LIMIT // 6 + 10)}
    cmd, stdin = _cmd_and_stdin(tmp_path, params)
    assert cmd[-1] == PARAMS_FROM_STDIN
    assert json.loads(stdin) == params


def test_运行器的小参数仍在命令行上(tmp_path: Path):
    cmd, stdin = _cmd_and_stdin(tmp_path, {"blob": "abc"})
    assert json.loads(cmd[-1]) == {"blob": "abc"}
    assert stdin is None
