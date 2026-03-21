"""ThinkingEngine package — pluggable decision paradigms for Primary Agent.

Supports two paradigms:
- "rule" (default): deterministic rules first, LLM fallback
- "llm": every layer uses haiku-level LLM classification

Switch via config.json: primary_agent.thinking.mode = "rule" | "llm"

Backward-compatible: `from frago.server.services.thinking import ThinkingEngine`
continues to work (returns RuleThinkingEngine instance).
"""

import json
import logging
from pathlib import Path

from frago.server.services.thinking.base import BaseThinkingEngine
from frago.server.services.thinking.llm_engine import LLMThinkingEngine
from frago.server.services.thinking.rule_engine import RuleThinkingEngine

logger = logging.getLogger(__name__)

__all__ = [
    "BaseThinkingEngine",
    "LLMThinkingEngine",
    "RuleThinkingEngine",
    "ThinkingEngine",
    "create_thinking_engine",
]


def _load_mode_from_config() -> str:
    """Read thinking mode from ~/.frago/config.json."""
    config_path = Path.home() / ".frago" / "config.json"
    try:
        if config_path.exists():
            data = json.loads(config_path.read_text(encoding="utf-8"))
            mode = data.get("primary_agent", {}).get("thinking", {}).get("mode")
            if mode:
                return str(mode)
    except Exception:
        logger.debug("Failed to read thinking mode from config", exc_info=True)
    return "rule"


def create_thinking_engine(mode: str | None = None) -> BaseThinkingEngine:
    """Factory: create a ThinkingEngine based on paradigm mode.

    Args:
        mode: "rule" or "llm". None reads from config (default "rule").

    Returns:
        A BaseThinkingEngine subclass instance.
    """
    resolved = mode or _load_mode_from_config()

    if resolved == "llm":
        logger.info("ThinkingEngine paradigm: llm")
        return LLMThinkingEngine()

    if resolved != "rule":
        logger.warning("Unknown thinking mode '%s', falling back to 'rule'", resolved)

    return RuleThinkingEngine()


# Backward compatibility: ThinkingEngine is a callable that creates the default engine
def ThinkingEngine(enable_llm: bool = True) -> BaseThinkingEngine:  # noqa: N802
    """Backward-compatible constructor.

    When called as ThinkingEngine(), returns a RuleThinkingEngine.
    Preserves the enable_llm parameter for existing call sites.
    """
    return RuleThinkingEngine(enable_llm=enable_llm)
