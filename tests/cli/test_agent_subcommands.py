"""frago agent start/send/peek/ls/stop 子命令单测：happy path 用 fake runner/tmp
sidecar，不拉真实 tmux；5 类负反馈逐一断言；外加 `frago agent` 裸调用向后兼容硬验证。"""

from __future__ import annotations

import json
import subprocess

import pytest
from click.testing import CliRunner

from frago.cli import drive_command
from frago.cli.agent_command import agent
from frago.cli.drive_command import DriveEntry

# 与当前 claude recipe 对齐：就绪/完成信号是空载输入框 `❯ `（行尾无内容），忙碌标记
# 含 `esc to interrupt`。read_answer 从可见 pane 抽答案，故 idle 屏在输入框上方带上一
# 轮答案 bullet `⏺ DRIVE_OK`（与 claude 真实 idle 屏一致）。
_PROMPT = "⏺ DRIVE_OK\n  ❯ \n"
_WORKING = "  working... esc to interrupt\n"
_FULL = "DRIVE_OK\n  ❯ \n"


class FakeTmux:
    """脚本化 tmux 替身：可控 alive 集合与 pane 就绪窗口。"""

    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.alive: set[str] = set()
        # None = 所有 visible capture 都回就绪屏；int N = 仅前 N 次回就绪屏。
        self.prompt_until: int | None = None
        # 优先级最高的 visible capture 脚本：非空时逐帧弹出（用于模拟残留文本等
        # 特定首帧），弹完回落到 prompt_until 逻辑。
        self.pane_script: list[str] = []
        self._vis_calls = 0

    def __call__(self, argv: list[str]) -> str:
        self.commands.append(argv)
        verb = argv[1] if len(argv) > 1 else ""
        if verb == "new-session":
            self.alive.add(argv[argv.index("-s") + 1])
            return ""
        if verb == "has-session":
            name = argv[argv.index("-t") + 1]
            if name not in self.alive:
                raise subprocess.CalledProcessError(1, argv)
            return ""
        if verb == "kill-session":
            self.alive.discard(argv[argv.index("-t") + 1])
            return ""
        if verb == "capture-pane":
            if "-S" in argv:
                return _FULL
            if self.pane_script:
                return self.pane_script.pop(0)
            self._vis_calls += 1
            if self.prompt_until is None or self._vis_calls <= self.prompt_until:
                return _PROMPT
            return _WORKING
        return ""  # send-keys / send-text


@pytest.fixture
def fake(monkeypatch, tmp_path):
    runner = FakeTmux()
    monkeypatch.setenv("FRAGO_DRIVE_DIR", str(tmp_path))
    monkeypatch.setattr(drive_command, "make_runner", lambda: runner)
    return runner


def _seed_entry(name: str, fake: FakeTmux, *, alive: bool = True) -> None:
    tmux_name = f"frago-agent-{name}"
    drive_command._write_entry(
        DriveEntry(name=name, agent_type="claude", tmux_name=tmux_name, pid=1234, cwd="/tmp")
    )
    if alive:
        fake.alive.add(tmux_name)


# ── happy paths ───────────────────────────────────────────────────────────


def test_start_happy(fake):
    res = CliRunner().invoke(agent, ["start", "claude", "--name", "smoke"])
    assert res.exit_code == 0, res.output
    assert res.output.strip() == "smoke"
    sidecar = json.loads((drive_command._sidecar_path("smoke")).read_text())
    assert sidecar["agent_type"] == "claude"
    assert sidecar["tmux_name"] == "frago-agent-smoke"
    assert "frago-agent-smoke" in fake.alive


def test_start_auto_suffix_when_name_taken(fake):
    _seed_entry("claude", fake)
    res = CliRunner().invoke(agent, ["start", "claude"])
    assert res.exit_code == 0, res.output
    assert res.output.strip() == "claude-2"


def test_send_happy(fake):
    _seed_entry("smoke", fake)
    res = CliRunner().invoke(agent, ["send", "smoke", "Reply with DRIVE_OK"])
    assert res.exit_code == 0, res.output
    assert "DRIVE_OK" in res.output


def test_peek_happy(fake):
    _seed_entry("smoke", fake)
    res = CliRunner().invoke(agent, ["peek", "smoke"])
    assert res.exit_code == 0, res.output
    assert "❯" in res.output


def test_ls_happy(fake):
    _seed_entry("a", fake)
    _seed_entry("b", fake, alive=False)
    res = CliRunner().invoke(agent, ["ls"])
    assert res.exit_code == 0, res.output
    assert "a\tclaude\t1234\talive" in res.output
    assert "b\tclaude\t1234\tdead" in res.output


@pytest.mark.usefixtures("fake")
def test_ls_empty():
    res = CliRunner().invoke(agent, ["ls"])
    assert res.exit_code == 0
    assert "no active drive sessions" in res.output


def test_stop_happy(fake):
    _seed_entry("smoke", fake)
    res = CliRunner().invoke(agent, ["stop", "smoke"])
    assert res.exit_code == 0, res.output
    assert not drive_command._sidecar_path("smoke").exists()
    assert "frago-agent-smoke" not in fake.alive


# ── 负反馈 1：send/peek/stop 到不存在的 name → 报错 + 活会话清单 ─────────────


def test_send_unknown_name_lists_active(fake):
    _seed_entry("alive-one", fake)
    res = CliRunner().invoke(agent, ["send", "ghost", "hi"])
    assert res.exit_code == 1
    assert "no drive session named 'ghost'" in res.output
    assert "alive-one" in res.output


@pytest.mark.usefixtures("fake")
def test_peek_unknown_name_lists_active():
    res = CliRunner().invoke(agent, ["peek", "ghost"])
    assert res.exit_code == 1
    assert "no drive session named 'ghost'" in res.output


@pytest.mark.usefixtures("fake")
def test_stop_unknown_name_lists_active():
    res = CliRunner().invoke(agent, ["stop", "ghost"])
    assert res.exit_code == 1
    assert "no drive session named 'ghost'" in res.output


# ── 负反馈 2：会话尚未 ready 就 send → 提示启动中 + 末屏 ─────────────────────


def test_send_not_ready_shows_starting(fake):
    fake.prompt_until = 0  # 首个 visible capture 就回 working 屏 → 未就绪
    _seed_entry("smoke", fake)
    res = CliRunner().invoke(agent, ["send", "smoke", "hi"])
    assert res.exit_code == 1
    assert "still starting up" in res.output
    assert "working" in res.output
    # 忙碌屏 = 真在启动/干活，不触发残留自愈，不发清行键（claude 是 C-u）。
    assert not any(c[-1] == "C-u" for c in fake.commands)


# ── 残留自愈：会话空闲但输入框滞留文本 → 清行键清空后继续 send ──────────────


def test_send_clears_residual_input_then_sends(fake):
    _seed_entry("smoke", fake)
    # ready 检查首帧：提示符在、无忙碌标记，但输入框有残留文本（Enter 被吞的滞留态）。
    # 自愈协议（claude 懒重绘 TUI）：C-u 清行 → 探针字符 x 强制重绘 → 输入框只剩
    # ``❯\xa0x``（nbsp 是 claude 输入框渲染特征）即确认缓冲区已清 → BSpace 删探针。
    fake.pane_script = [
        "⏺ old answer\n  ❯ leftover unsubmitted text\n",  # ready 检查首帧（滞留态）
        "⏺ old answer\n  ❯\xa0x\n",  # C-u + 探针后：探针独占输入框
    ]
    res = CliRunner().invoke(agent, ["send", "smoke", "hi"])
    assert res.exit_code == 0, res.output
    assert "DRIVE_OK" in res.output
    assert ["tmux", "send-keys", "-t", "frago-agent-smoke", "C-u"] in fake.commands
    assert ["tmux", "send-keys", "-t", "frago-agent-smoke", "BSpace"] in fake.commands


# ── 负反馈 3：等不到 done_signal 超时 → timeout + 末屏 + 接管提示 ────────────


def test_send_timeout_dumps_pane_and_tip(fake):
    fake.prompt_until = 2  # ready-check + pre_snapshot 就绪，之后轮询不再就绪
    _seed_entry("smoke", fake)
    res = CliRunner().invoke(agent, ["send", "smoke", "hi", "--timeout", "0.05"])
    assert res.exit_code == 1
    assert "timed out" in res.output
    assert "tmux attach -t frago-agent-smoke" in res.output


# ── 负反馈 4：agent_type 无 recipe → 列出已注册 agent_type ───────────────────


@pytest.mark.usefixtures("fake")
def test_start_unknown_agent_type_lists_known():
    res = CliRunner().invoke(agent, ["start", "nope-agent"])
    assert res.exit_code == 1
    assert "no driver registered" in res.output
    assert "claude" in res.output


# ── 负反馈 5：start 时 tmux 缺失 → 提示安装 tmux ────────────────────────────


def test_start_tmux_missing_prompts_install(monkeypatch, tmp_path):
    monkeypatch.setenv("FRAGO_DRIVE_DIR", str(tmp_path))

    def boom(_argv):
        raise FileNotFoundError("tmux")

    monkeypatch.setattr(drive_command, "make_runner", lambda: boom)
    res = CliRunner().invoke(agent, ["start", "claude", "--name", "x"])
    assert res.exit_code == 1
    assert "tmux not found" in res.output


# ── 向后兼容：frago agent 裸调用（原单命令行为）必须零破坏 ──────────────────


def test_help_lists_bare_usage_and_subcommands():
    res = CliRunner().invoke(agent, ["--help"])
    assert res.exit_code == 0, res.output
    # 原裸 prompt 用法
    assert "Bare-prompt usage" in res.output
    # 新子命令
    for verb in ("start", "send", "peek", "ls", "stop"):
        assert verb in res.output


def test_bare_prompt_routes_to_legacy_run():
    # 第一个 token 是 prompt（非子命令）→ 走隐藏默认命令；--dry-run 不真正执行。
    res = CliRunner().invoke(
        agent, ["hello", "world", "--dry-run"]
    )
    assert res.exit_code == 0, res.output
    assert "Dry Run" in res.output


def test_options_first_routes_to_legacy_run():
    # PA 路径形态：选项在前、无位置 prompt（prompt 经其它途径）。这里用 dry-run 验证路由。
    res = CliRunner().invoke(
        agent, ["--dry-run", "--quiet", "do", "something"]
    )
    assert res.exit_code == 0, res.output
    assert "Dry Run" in res.output


def test_bare_empty_errors_like_before():
    # 无参 → 默认命令报 "provide prompt"，与原单命令一致。
    res = CliRunner().invoke(agent, [])
    assert res.exit_code == 1
    assert "provide prompt" in res.output.lower()
