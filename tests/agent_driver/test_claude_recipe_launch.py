"""Phase 1 单测：claude recipe 的 launch_command 拼入 --dangerously-skip-permissions。

tmux 后端注入 prompt 时若卡在权限弹窗，就绪信号永不出现，故启动命令默认免权限确认。
"""

from __future__ import annotations

# 触发 recipe 注册
import frago.agent_driver.recipes.claude  # noqa: F401
from frago.agent_driver import load_recipe
from frago.agent_driver.recipe import LaunchCtx


def test_launch_command_includes_skip_permissions() -> None:
    recipe = load_recipe("claude")
    cmd = recipe.launch_command(LaunchCtx(cwd="/tmp", session_id="s1"))
    assert "--dangerously-skip-permissions" in cmd
    assert cmd.startswith("claude")
