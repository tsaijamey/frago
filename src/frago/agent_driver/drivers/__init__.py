"""每 agent 的 driver 模块；import 即触发各 driver 自注册到 registry。"""

from frago.agent_driver.drivers import agy, claude, codex, opencode  # noqa: F401

__all__ = ["agy", "claude", "codex", "opencode"]
