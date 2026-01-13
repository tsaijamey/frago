"""GitHub API rate limit manager."""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Mapping, Optional

logger = logging.getLogger(__name__)


@dataclass
class RateLimitState:
    """GitHub rate limit state."""

    limit: int = 60  # Default unauthenticated limit
    remaining: int = 60
    reset_timestamp: float = 0.0
    last_updated: float = field(default_factory=time.monotonic)


class GitHubRateLimitManager:
    """Manages GitHub API rate limit state and adaptive behavior.

    Thread-safe singleton that tracks rate limit headers from GitHub API
    responses and provides recommendations for request timing.
    """

    _instance: Optional["GitHubRateLimitManager"] = None
    _lock = threading.Lock()

    # Thresholds for adaptive behavior
    SOFT_LIMIT_THRESHOLD = 0.2  # 20% remaining triggers slowdown
    HARD_LIMIT_THRESHOLD = 0.05  # 5% remaining triggers pause

    def __init__(self) -> None:
        self._state = RateLimitState()
        self._backoff_multiplier: float = 1.0
        self._consecutive_errors: int = 0
        self._state_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "GitHubRateLimitManager":
        """Get singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (for testing)."""
        with cls._lock:
            cls._instance = None

    def update_from_headers(self, headers: Mapping[str, str]) -> None:
        """Update state from GitHub response headers.

        Args:
            headers: Response headers dict (case-insensitive mapping)
        """
        with self._state_lock:
            try:
                # GitHub headers are case-insensitive
                limit_str = headers.get("X-RateLimit-Limit") or headers.get(
                    "x-ratelimit-limit"
                )
                remaining_str = headers.get("X-RateLimit-Remaining") or headers.get(
                    "x-ratelimit-remaining"
                )
                reset_str = headers.get("X-RateLimit-Reset") or headers.get(
                    "x-ratelimit-reset"
                )

                if limit_str:
                    self._state.limit = int(limit_str)
                if remaining_str:
                    self._state.remaining = int(remaining_str)
                if reset_str:
                    self._state.reset_timestamp = float(reset_str)

                self._state.last_updated = time.monotonic()

                # Reset backoff on successful response
                self._consecutive_errors = 0
                self._backoff_multiplier = 1.0

                logger.debug(
                    f"GitHub rate limit: {self._state.remaining}/{self._state.limit}, "
                    f"resets at {time.ctime(self._state.reset_timestamp)}"
                )
            except (ValueError, TypeError) as e:
                logger.warning(f"Failed to parse rate limit headers: {e}")

    def record_error(self, is_rate_limit: bool = False) -> None:
        """Record an error for backoff calculation.

        Args:
            is_rate_limit: True if error was a rate limit (403)
        """
        with self._state_lock:
            self._consecutive_errors += 1
            if is_rate_limit:
                # Aggressive backoff for rate limit errors
                self._backoff_multiplier = min(self._backoff_multiplier * 2, 64.0)
            else:
                # Moderate backoff for other errors
                self._backoff_multiplier = min(self._backoff_multiplier * 1.5, 16.0)

    def get_recommended_delay(self) -> float:
        """Get recommended delay before next request.

        Returns:
            Delay in seconds
        """
        with self._state_lock:
            remaining_ratio = self._state.remaining / max(self._state.limit, 1)

            # Hard limit: pause until reset
            if remaining_ratio <= self.HARD_LIMIT_THRESHOLD:
                wait_time = max(0, self._state.reset_timestamp - time.time())
                if wait_time > 0:
                    logger.warning(
                        f"GitHub rate limit critical ({self._state.remaining} remaining), "
                        f"waiting {wait_time:.0f}s until reset"
                    )
                return wait_time

            # Soft limit: increase interval
            if remaining_ratio <= self.SOFT_LIMIT_THRESHOLD:
                return 5.0 * self._backoff_multiplier

            # Normal: minimal delay with backoff
            return 0.1 * self._backoff_multiplier

    def should_skip_refresh(self) -> bool:
        """Determine if refresh should be skipped due to rate limits.

        Returns:
            True if rate limit is critically low
        """
        with self._state_lock:
            remaining_ratio = self._state.remaining / max(self._state.limit, 1)
            return remaining_ratio <= self.HARD_LIMIT_THRESHOLD

    def get_adaptive_interval(self, base_interval: float) -> float:
        """Get adaptive refresh interval based on rate limit state.

        Args:
            base_interval: Normal refresh interval in seconds

        Returns:
            Adjusted interval in seconds
        """
        with self._state_lock:
            remaining_ratio = self._state.remaining / max(self._state.limit, 1)

            if remaining_ratio <= self.HARD_LIMIT_THRESHOLD:
                # Critical: extend to max(reset_time, 10 minutes)
                wait_time = max(0, self._state.reset_timestamp - time.time())
                return max(wait_time, 600)
            elif remaining_ratio <= self.SOFT_LIMIT_THRESHOLD:
                # Low: double interval
                return base_interval * 2

            return base_interval

    def get_status(self) -> dict:
        """Get current rate limit status for debugging.

        Returns:
            Dict with rate limit state info
        """
        with self._state_lock:
            return {
                "limit": self._state.limit,
                "remaining": self._state.remaining,
                "reset_timestamp": self._state.reset_timestamp,
                "reset_time": time.ctime(self._state.reset_timestamp),
                "backoff_multiplier": self._backoff_multiplier,
                "consecutive_errors": self._consecutive_errors,
            }
