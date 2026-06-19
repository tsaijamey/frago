"""每 agent 的 recipe 模块；import 即触发各 recipe 自注册到 registry。"""

from frago.agent_driver.recipes import claude, codex, opencode  # noqa: F401

__all__ = ["claude", "codex", "opencode"]
