"""
CDP retry mechanism

Implements exponential backoff retry strategy for handling CDP connection and command execution failures.
"""

import time
import random
from typing import Callable, Any, Optional, Tuple, Type

from .logger import get_logger
from .exceptions import RetryExhaustedError, ProxyConnectionError, ConnectionError


class RetryPolicy:
    """Retry policy class"""

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
        retryable_exceptions: Optional[Tuple[Type[Exception], ...]] = None
    ):
        """
        Initialize retry policy

        Args:
            max_retries: Maximum retry attempts
            base_delay: Base delay time (seconds)
            max_delay: Maximum delay time (seconds)
            exponential_base: Exponential backoff base
            jitter: Whether to add random jitter
            retryable_exceptions: Tuple of retryable exception types, None means all exceptions are retryable
        """
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.retryable_exceptions = retryable_exceptions
        self.logger = get_logger()
    
    def execute(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with retry

        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Any: Function execution result

        Raises:
            RetryExhaustedError: Retry exhausted
            Exception: Last retry exception (non-retryable exceptions will be raised immediately)
        """
        last_exception = None

        for attempt in range(self.max_retries + 1):
            try:
                if attempt > 0:
                    self.logger.info(f"Retry attempt {attempt}/{self.max_retries}")

                return func(*args, **kwargs)

            except Exception as e:
                last_exception = e

                # Check if exception is retryable
                if self.retryable_exceptions is not None:
                    if not isinstance(e, self.retryable_exceptions):
                        self.logger.error(f"Non-retryable exception: {type(e).__name__}: {e}")
                        raise

                # If this is the last attempt, don't retry
                if attempt == self.max_retries:
                    break

                # Provide special hint for proxy connection errors
                if isinstance(e, ProxyConnectionError):
                    self.logger.warning(
                        f"Proxy connection failed (attempt {attempt + 1}/{self.max_retries + 1}): {e}. "
                        f"Consider checking proxy configuration or using --no-proxy flag."
                    )

                # Calculate delay time
                delay = self._calculate_delay(attempt)
                self.logger.warning(
                    f"Operation failed (attempt {attempt + 1}/{self.max_retries + 1}): {e}. "
                    f"Retrying in {delay:.2f}s..."
                )

                # Wait for delay time
                time.sleep(delay)

        # All retries failed
        raise RetryExhaustedError(
            f"Operation failed after {self.max_retries + 1} attempts. "
            f"Last exception: {last_exception}"
        ) from last_exception

    def _calculate_delay(self, attempt: int) -> float:
        """
        Calculate retry delay time

        Args:
            attempt: Current retry count

        Returns:
            float: Delay time (seconds)
        """
        # Exponential backoff
        delay = self.base_delay * (self.exponential_base ** attempt)

        # Limit maximum delay
        delay = min(delay, self.max_delay)

        # Add random jitter
        if self.jitter:
            delay = random.uniform(0, delay)

        return delay


class RetryableOperation:
    """Retryable operation class"""

    def __init__(self, policy: Optional[RetryPolicy] = None):
        """
        Initialize retryable operation

        Args:
            policy: Retry policy, uses default policy if None
        """
        self.policy = policy or RetryPolicy()

    def __call__(self, func: Callable) -> Callable:
        """
        Decorator implementation

        Args:
            func: Function to decorate

        Returns:
            Callable: Decorated function
        """
        def wrapper(*args, **kwargs):
            return self.policy.execute(func, *args, **kwargs)

        return wrapper


# Common retry policy instances
default_retry_policy = RetryPolicy()
aggressive_retry_policy = RetryPolicy(max_retries=5, base_delay=0.5)
conservative_retry_policy = RetryPolicy(max_retries=2, base_delay=2.0)

# Proxy connection specific retry policy
# For proxy connection failures, use more aggressive retry strategy (more retries, shorter delays)
proxy_connection_retry_policy = RetryPolicy(
    max_retries=5,
    base_delay=0.5,
    max_delay=10.0,
    exponential_base=1.5,
    jitter=True,
    retryable_exceptions=(ProxyConnectionError, ConnectionError)
)

# Connection retry policy (for general connection issues)
connection_retry_policy = RetryPolicy(
    max_retries=3,
    base_delay=1.0,
    max_delay=15.0,
    retryable_exceptions=(ConnectionError, ProxyConnectionError)
)


# Convenience decorator
def retryable(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retryable_exceptions: Optional[Tuple[Type[Exception], ...]] = None
) -> Callable:
    """
    Retry decorator

    Args:
        max_retries: Maximum retry attempts
        base_delay: Base delay time (seconds)
        max_delay: Maximum delay time (seconds)
        exponential_base: Exponential backoff base
        jitter: Whether to add random jitter
        retryable_exceptions: Tuple of retryable exception types, None means all exceptions are retryable

    Returns:
        Callable: Decorator function
    """
    policy = RetryPolicy(
        max_retries=max_retries,
        base_delay=base_delay,
        max_delay=max_delay,
        exponential_base=exponential_base,
        jitter=jitter,
        retryable_exceptions=retryable_exceptions
    )

    return RetryableOperation(policy)