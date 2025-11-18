"""
CDP重试机制

实现指数退避重试策略，用于处理CDP连接和命令执行失败。
"""

import time
import random
from typing import Callable, Any, Optional, Tuple, Type

from .logger import get_logger
from .exceptions import RetryExhaustedError, ProxyConnectionError, ConnectionError


class RetryPolicy:
    """重试策略类"""

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
        初始化重试策略

        Args:
            max_retries: 最大重试次数
            base_delay: 基础延迟时间（秒）
            max_delay: 最大延迟时间（秒）
            exponential_base: 指数退避基数
            jitter: 是否添加随机抖动
            retryable_exceptions: 可重试的异常类型元组，None表示所有异常都可重试
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
        执行带重试的函数

        Args:
            func: 要执行的函数
            *args: 函数参数
            **kwargs: 函数关键字参数

        Returns:
            Any: 函数执行结果

        Raises:
            RetryExhaustedError: 重试耗尽
            Exception: 最后一次重试的异常（不可重试的异常会立即抛出）
        """
        last_exception = None

        for attempt in range(self.max_retries + 1):
            try:
                if attempt > 0:
                    self.logger.info(f"Retry attempt {attempt}/{self.max_retries}")

                return func(*args, **kwargs)

            except Exception as e:
                last_exception = e

                # 检查异常是否可重试
                if self.retryable_exceptions is not None:
                    if not isinstance(e, self.retryable_exceptions):
                        self.logger.error(f"Non-retryable exception: {type(e).__name__}: {e}")
                        raise

                # 如果是最后一次尝试，不再重试
                if attempt == self.max_retries:
                    break

                # 针对代理连接错误提供特殊提示
                if isinstance(e, ProxyConnectionError):
                    self.logger.warning(
                        f"Proxy connection failed (attempt {attempt + 1}/{self.max_retries + 1}): {e}. "
                        f"Consider checking proxy configuration or using --no-proxy flag."
                    )

                # 计算延迟时间
                delay = self._calculate_delay(attempt)
                self.logger.warning(
                    f"Operation failed (attempt {attempt + 1}/{self.max_retries + 1}): {e}. "
                    f"Retrying in {delay:.2f}s..."
                )

                # 等待延迟时间
                time.sleep(delay)

        # 所有重试都失败
        raise RetryExhaustedError(
            f"Operation failed after {self.max_retries + 1} attempts. "
            f"Last exception: {last_exception}"
        ) from last_exception
    
    def _calculate_delay(self, attempt: int) -> float:
        """
        计算重试延迟时间
        
        Args:
            attempt: 当前重试次数
            
        Returns:
            float: 延迟时间（秒）
        """
        # 指数退避
        delay = self.base_delay * (self.exponential_base ** attempt)
        
        # 限制最大延迟
        delay = min(delay, self.max_delay)
        
        # 添加随机抖动
        if self.jitter:
            delay = random.uniform(0, delay)
        
        return delay


class RetryableOperation:
    """可重试操作类"""
    
    def __init__(self, policy: Optional[RetryPolicy] = None):
        """
        初始化可重试操作
        
        Args:
            policy: 重试策略，如果为None则使用默认策略
        """
        self.policy = policy or RetryPolicy()
    
    def __call__(self, func: Callable) -> Callable:
        """
        装饰器实现
        
        Args:
            func: 要装饰的函数
            
        Returns:
            Callable: 装饰后的函数
        """
        def wrapper(*args, **kwargs):
            return self.policy.execute(func, *args, **kwargs)
        
        return wrapper


# 常用重试策略实例
default_retry_policy = RetryPolicy()
aggressive_retry_policy = RetryPolicy(max_retries=5, base_delay=0.5)
conservative_retry_policy = RetryPolicy(max_retries=2, base_delay=2.0)

# 代理连接专用重试策略
# 针对代理连接失败，使用更激进的重试策略（更多重试次数，更短的延迟）
proxy_connection_retry_policy = RetryPolicy(
    max_retries=5,
    base_delay=0.5,
    max_delay=10.0,
    exponential_base=1.5,
    jitter=True,
    retryable_exceptions=(ProxyConnectionError, ConnectionError)
)

# 连接重试策略（用于一般连接问题）
connection_retry_policy = RetryPolicy(
    max_retries=3,
    base_delay=1.0,
    max_delay=15.0,
    retryable_exceptions=(ConnectionError, ProxyConnectionError)
)


# 便捷装饰器
def retryable(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retryable_exceptions: Optional[Tuple[Type[Exception], ...]] = None
) -> Callable:
    """
    重试装饰器

    Args:
        max_retries: 最大重试次数
        base_delay: 基础延迟时间（秒）
        max_delay: 最大延迟时间（秒）
        exponential_base: 指数退避基数
        jitter: 是否添加随机抖动
        retryable_exceptions: 可重试的异常类型元组，None表示所有异常都可重试

    Returns:
        Callable: 装饰器函数
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