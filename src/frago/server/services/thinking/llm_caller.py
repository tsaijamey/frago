"""Shared LLM classification utility — Claude CLI one-shot calls via haiku model."""

import json
import logging
import os
import subprocess

logger = logging.getLogger(__name__)


def llm_classify(prompt: str, timeout: int = 30) -> str | None:
    """One-shot Claude CLI call for lightweight classification.

    Uses haiku model with JSON output. Returns the raw result text,
    or None on any failure (timeout, CLI not found, parse error).
    """
    try:
        from frago.compat import find_claude_cli, get_windows_subprocess_kwargs
    except ImportError:
        from frago.compat import get_windows_subprocess_kwargs
        find_claude_cli = None

    # Find claude CLI
    claude_path = None
    if find_claude_cli:
        claude_path = find_claude_cli()
    if not claude_path:
        import shutil
        claude_path = shutil.which("claude")
    if not claude_path:
        logger.debug("LLM classify: claude CLI not found")
        return None

    cmd = [claude_path, "-p", "-", "--model", "haiku", "--output-format", "json"]

    env = os.environ.copy()
    env.pop("CLAUDECODE", None)

    try:
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=env,
            **get_windows_subprocess_kwargs(),
        )
        stdout, stderr = process.communicate(input=prompt, timeout=timeout)

        if process.returncode != 0:
            logger.debug("LLM classify failed (rc=%d): %s", process.returncode, stderr[:200] if stderr else "")
            return None

        result = json.loads(stdout)
        if result.get("type") == "result":
            return result.get("result", "").strip()
        return stdout.strip()

    except subprocess.TimeoutExpired:
        logger.warning("LLM classify timed out (%ds)", timeout)
        import contextlib
        with contextlib.suppress(Exception):
            process.kill()
        return None
    except (json.JSONDecodeError, OSError) as e:
        logger.debug("LLM classify error: %s", e)
        return None
