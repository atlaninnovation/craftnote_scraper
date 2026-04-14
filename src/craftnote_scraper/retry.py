import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final

logger = logging.getLogger(__name__)

DEFAULT_MAX_RETRIES: Final[int] = 3
DEFAULT_BASE_DELAY_SECONDS: Final[float] = 1.0
DEFAULT_MAX_DELAY_SECONDS: Final[float] = 60.0
DEFAULT_JITTER_FACTOR: Final[float] = 0.1


@dataclass(frozen=True)
class RetryConfig:
    max_retries: int = DEFAULT_MAX_RETRIES
    base_delay_seconds: float = DEFAULT_BASE_DELAY_SECONDS
    max_delay_seconds: float = DEFAULT_MAX_DELAY_SECONDS
    jitter_factor: float = DEFAULT_JITTER_FACTOR


def calculate_delay(attempt: int, config: RetryConfig) -> float:
    """Calculate delay with exponential backoff and jitter."""
    exponential_delay = config.base_delay_seconds * (2 ** (attempt - 1))
    capped_delay = min(exponential_delay, config.max_delay_seconds)
    jitter = capped_delay * config.jitter_factor * random.random()  # noqa: S311
    return capped_delay + jitter


async def retry_async[T](
    func: Callable[[], Awaitable[T]],
    retryable_exceptions: tuple[type[Exception], ...],
    config: RetryConfig | None = None,
    operation_name: str = "operation",
) -> T:
    """
    Retry an async function with exponential backoff.

    Args:
        func: Async function to retry.
        retryable_exceptions: Tuple of exception types that should trigger a retry.
        config: Retry configuration. Uses defaults if not provided.
        operation_name: Name for logging purposes.

    Returns:
        Result of the function call.

    Raises:
        The last exception if all retries are exhausted.
    """
    cfg = config or RetryConfig()
    last_exception: Exception | None = None

    for attempt in range(1, cfg.max_retries + 2):
        try:
            return await func()
        except retryable_exceptions as e:
            last_exception = e
            if attempt > cfg.max_retries:
                logger.error(
                    "All %d retries exhausted for %s: %s",
                    cfg.max_retries,
                    operation_name,
                    e,
                )
                raise

            delay = calculate_delay(attempt, cfg)
            logger.warning(
                "Retry %d/%d for %s after %.1fs: %s",
                attempt,
                cfg.max_retries,
                operation_name,
                delay,
                e,
            )
            await asyncio.sleep(delay)

    if last_exception:
        raise last_exception
    raise RuntimeError("Unexpected state in retry loop")
