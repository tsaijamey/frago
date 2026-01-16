"""
Session Title Manager

Manages AI-generated session titles using Claude Code CLI with haiku model.
Titles are stored in ~/.frago/sessions.json, separate from session metadata.
"""

import asyncio
import hashlib
import json
import logging
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from frago.compat import find_claude_cli, get_windows_subprocess_kwargs
from frago.session.models import AgentType

logger = logging.getLogger(__name__)

# Sessions JSON file path
SESSIONS_JSON_PATH = Path.home() / ".frago" / "sessions.json"

# Schema version for future migrations
SCHEMA_VERSION = "1.0"


class TitleManager:
    """Manages AI-generated session titles."""

    def __init__(self):
        self._cache: Optional[Dict[str, Any]] = None

    def _load_sessions_json(self) -> Dict[str, Any]:
        """Load sessions.json, create if not exists."""
        if self._cache is not None:
            return self._cache

        if SESSIONS_JSON_PATH.exists():
            try:
                with open(SESSIONS_JSON_PATH, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
                # Validate schema
                if not isinstance(self._cache, dict):
                    self._cache = self._create_default()
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load sessions.json: {e}")
                self._cache = self._create_default()
        else:
            self._cache = self._create_default()

        return self._cache

    def _create_default(self) -> Dict[str, Any]:
        """Create default sessions.json structure."""
        return {
            "schema_version": SCHEMA_VERSION,
            "titles": {},
            "excluded_sessions": []
        }

    def _save_sessions_json(self) -> None:
        """Save sessions.json to disk."""
        if self._cache is None:
            return

        SESSIONS_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(SESSIONS_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(self._cache, f, ensure_ascii=False, indent=2)

    def get_title(
        self,
        session_id: str,
        fallback_name: Optional[str] = None
    ) -> Optional[str]:
        """Get title for session.

        Returns cached title or fallback.
        Does NOT trigger generation - use generate_title_if_needed for that.

        Args:
            session_id: Session ID
            fallback_name: Fallback name if no AI title exists

        Returns:
            AI-generated title, fallback, or None
        """
        data = self._load_sessions_json()
        titles = data.get("titles", {})

        if session_id in titles:
            return titles[session_id].get("title")

        return fallback_name

    def has_title(self, session_id: str) -> bool:
        """Check if session has an AI-generated title."""
        data = self._load_sessions_json()
        return session_id in data.get("titles", {})

    def generate_title_if_needed(
        self,
        session_id: str,
        agent_type: AgentType = AgentType.CLAUDE,
        force: bool = False
    ) -> tuple[Optional[str], Optional[str]]:
        """Generate title for session if not already generated.

        Uses haiku model via Claude Code CLI.

        Args:
            session_id: Session ID
            agent_type: Agent type
            force: Force regenerate even if exists

        Returns:
            Tuple of (title, error_message). On success, error is None.
        """
        data = self._load_sessions_json()

        # Check if already generated
        if not force and session_id in data.get("titles", {}):
            return data["titles"][session_id].get("title"), None

        # Get session content
        content = self._get_session_content(session_id, agent_type)
        if not content or len(content.strip()) < 50:
            logger.debug(f"Insufficient content for title generation: {session_id}")
            return None, "Insufficient content for title generation"

        # Calculate content hash
        content_hash = self._hash_content(content[:5000])

        # Check if content unchanged (skip regeneration)
        if session_id in data.get("titles", {}):
            existing = data["titles"][session_id]
            if existing.get("content_hash") == content_hash and not force:
                return existing.get("title"), None

        # Generate title using Claude CLI with haiku
        title, error = self._call_haiku_for_title(content[:5000])

        if title:
            data.setdefault("titles", {})[session_id] = {
                "title": title[:100],  # Max 100 chars
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "model": "haiku",
                "content_hash": content_hash
            }
            self._save_sessions_json()
            logger.info(f"Generated title for session {session_id[:8]}: {title[:50]}")

        return title, error

    async def generate_title_if_needed_async(
        self,
        session_id: str,
        agent_type: AgentType = AgentType.CLAUDE,
        force: bool = False
    ) -> tuple[Optional[str], Optional[str]]:
        """Async version of generate_title_if_needed.

        Runs the blocking subprocess call in a thread pool executor.
        Use this in async contexts (e.g., FastAPI routes) to avoid blocking.

        Args:
            session_id: Session ID
            agent_type: Agent type
            force: Force regenerate even if exists

        Returns:
            Tuple of (title, error_message). On success, error is None.
        """
        data = self._load_sessions_json()

        # Check if already generated (fast sync check)
        if not force and session_id in data.get("titles", {}):
            return data["titles"][session_id].get("title"), None

        # Get session content (fast sync operation)
        content = self._get_session_content(session_id, agent_type)
        if not content or len(content.strip()) < 50:
            logger.debug(f"Insufficient content for title generation: {session_id}")
            return None, "Insufficient content for title generation"

        # Calculate content hash
        content_hash = self._hash_content(content[:5000])

        # Check if content unchanged (skip regeneration)
        if session_id in data.get("titles", {}):
            existing = data["titles"][session_id]
            if existing.get("content_hash") == content_hash and not force:
                return existing.get("title"), None

        # Run blocking subprocess call in executor
        loop = asyncio.get_event_loop()
        title, error = await loop.run_in_executor(
            None,
            self._call_haiku_for_title,
            content[:5000]
        )

        if title:
            # Reload data in case it changed during async operation
            data = self._load_sessions_json()
            data.setdefault("titles", {})[session_id] = {
                "title": title[:100],
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "model": "haiku",
                "content_hash": content_hash
            }
            self._save_sessions_json()
            logger.info(f"Generated title for session {session_id[:8]}: {title[:50]}")

        return title, error

    def _get_session_content(
        self,
        session_id: str,
        agent_type: AgentType
    ) -> Optional[str]:
        """Extract first 5000 chars of session content."""
        try:
            from frago.session.storage import read_steps

            steps = read_steps(session_id, agent_type)
            if not steps:
                return None

            # Collect content from steps
            content_parts = []
            total_chars = 0
            max_chars = 5000

            for step in steps:
                text = step.content_summary or ""
                if total_chars + len(text) > max_chars:
                    remaining = max_chars - total_chars
                    content_parts.append(text[:remaining])
                    break
                content_parts.append(text)
                total_chars += len(text)

            return "\n".join(content_parts)
        except Exception as e:
            logger.warning(f"Failed to get session content: {e}")
            return None

    def _hash_content(self, content: str) -> str:
        """Generate hash of content for change detection."""
        return hashlib.sha256(content.encode()).hexdigest()[:12]

    def _call_haiku_for_title(self, content: str) -> tuple[Optional[str], Optional[str]]:
        """Call Claude CLI with haiku model to generate title.

        Args:
            content: Session content (first 5000 chars)

        Returns:
            Tuple of (title, error_message). On success, error is None.
            On failure, title is None and error contains a descriptive message.
        """
        # Find claude CLI executable
        claude_path = find_claude_cli()
        if not claude_path:
            error_msg = (
                "Claude CLI not found. Please ensure claude is installed and in PATH. "
                "On Windows, check that npm global bin directory is in PATH."
            )
            logger.warning(f"Title generation error: {error_msg}")
            return None, error_msg

        # Get user's language preference for AI output
        from frago.server.services.config_service import ConfigService

        language = ConfigService.get_user_language()
        lang_instruction = (
            "Generate the title in Chinese (中文)."
            if language == "zh"
            else "Generate the title in English."
        )

        prompt = f'''Based on the following conversation excerpt, generate a concise title (max 60 characters) that captures the main topic or task being discussed. {lang_instruction} Return ONLY the title text, no quotes, no explanation.

Conversation:
{content}

Title:'''

        try:
            cmd = [
                claude_path, "-p", "-",
                "--model", "haiku",
                "--output-format", "json",
            ]

            popen_kwargs: dict = {
                "stdin": subprocess.PIPE,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "text": True,
                "encoding": "utf-8",
                **get_windows_subprocess_kwargs(),
            }

            process = subprocess.Popen(
                cmd,
                **popen_kwargs,
            )

            stdout, stderr = process.communicate(
                input=prompt,
                timeout=60
            )

            if process.returncode == 0:
                try:
                    result = json.loads(stdout)

                    # Extract and exclude the temporary session
                    temp_session_id = result.get("session_id")
                    if temp_session_id:
                        self.add_excluded_session(temp_session_id)

                    # Extract title from result
                    if result.get("type") == "result":
                        title = result.get("result", "").strip()
                        # Clean up title (remove quotes if present)
                        title = title.strip('"\'')
                        return (title[:100], None) if title else (None, "Empty title returned")
                except json.JSONDecodeError:
                    # Try to extract from raw text
                    title = stdout.strip()[:100] if stdout.strip() else None
                    return (title, None) if title else (None, "Failed to parse response")

            error_msg = f"Claude CLI returned error: {stderr[:200] if stderr else 'unknown error'}"
            logger.warning(f"Title generation failed: {error_msg}")
            return None, error_msg

        except subprocess.TimeoutExpired:
            logger.warning("Title generation timed out")
            process.kill()
            return None, "Title generation timed out (60s)"
        except FileNotFoundError as e:
            error_msg = f"Claude CLI not found at '{claude_path}': {e}"
            logger.warning(f"Title generation error: {error_msg}")
            return None, error_msg
        except Exception as e:
            error_msg = f"Title generation error: {e}"
            logger.warning(error_msg)
            return None, error_msg

    def is_excluded_session(self, session_id: str) -> bool:
        """Check if session is in excluded list (e.g., title generation sessions)."""
        data = self._load_sessions_json()
        return session_id in data.get("excluded_sessions", [])

    def add_excluded_session(self, session_id: str) -> None:
        """Add session to excluded list."""
        data = self._load_sessions_json()
        excluded = data.setdefault("excluded_sessions", [])
        if session_id not in excluded:
            excluded.append(session_id)
            self._save_sessions_json()
            logger.debug(f"Added excluded session: {session_id[:8]}")

    def remove_excluded_session(self, session_id: str) -> None:
        """Remove session from excluded list."""
        data = self._load_sessions_json()
        excluded = data.get("excluded_sessions", [])
        if session_id in excluded:
            excluded.remove(session_id)
            self._save_sessions_json()

    def invalidate_cache(self) -> None:
        """Clear in-memory cache to force reload from disk."""
        self._cache = None


# Global singleton instance
_title_manager: Optional[TitleManager] = None


def get_title_manager() -> TitleManager:
    """Get singleton TitleManager instance."""
    global _title_manager
    if _title_manager is None:
        _title_manager = TitleManager()
    return _title_manager
