"""Timing utilities — decorators and context managers for performance tracking.

Usage:
    from hermes_bedrock_agent.utils.timing import timed, Timer

    @timed
    def my_function():
        ...

    with Timer("embedding batch") as t:
        ...
    print(f"Took {t.elapsed_ms:.1f}ms")
"""

from __future__ import annotations

import functools
import time
from typing import Any, Callable, Optional

from hermes_bedrock_agent.configs.logging import get_logger

logger = get_logger(__name__)


class Timer:
    """Context manager for timing code blocks.

    Attributes:
        label: Human-readable label for the operation.
        elapsed_s: Elapsed time in seconds (after exit).
        elapsed_ms: Elapsed time in milliseconds (after exit).
    """

    def __init__(self, label: str = "operation") -> None:
        self.label = label
        self.elapsed_s: float = 0.0
        self.elapsed_ms: float = 0.0
        self._start: float = 0.0

    def __enter__(self) -> "Timer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.elapsed_s = time.perf_counter() - self._start
        self.elapsed_ms = self.elapsed_s * 1000.0

    def __repr__(self) -> str:
        return f"Timer({self.label!r}, elapsed_ms={self.elapsed_ms:.1f})"


def timed(
    func: Optional[Callable] = None,
    *,
    label: Optional[str] = None,
    log_level: str = "debug",
) -> Callable:
    """Decorator to log execution time of a function.

    Args:
        func: Function to decorate (auto-applied if used without args).
        label: Custom label (defaults to function name).
        log_level: Log level for timing output (debug, info, warning).

    Usage:
        @timed
        def process_chunk(...): ...

        @timed(label="neptune-load", log_level="info")
        def load_to_neptune(...): ...
    """

    def decorator(fn: Callable) -> Callable:
        fn_label = label or fn.__qualname__

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            try:
                result = fn(*args, **kwargs)
                elapsed_ms = (time.perf_counter() - start) * 1000.0
                log_fn = getattr(logger, log_level, logger.debug)
                log_fn(f"{fn_label} completed in {elapsed_ms:.1f}ms")
                return result
            except Exception:
                elapsed_ms = (time.perf_counter() - start) * 1000.0
                logger.warning(f"{fn_label} failed after {elapsed_ms:.1f}ms")
                raise

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            try:
                result = await fn(*args, **kwargs)
                elapsed_ms = (time.perf_counter() - start) * 1000.0
                log_fn = getattr(logger, log_level, logger.debug)
                log_fn(f"{fn_label} completed in {elapsed_ms:.1f}ms")
                return result
            except Exception:
                elapsed_ms = (time.perf_counter() - start) * 1000.0
                logger.warning(f"{fn_label} failed after {elapsed_ms:.1f}ms")
                raise

        import asyncio

        if asyncio.iscoroutinefunction(fn):
            return async_wrapper
        return wrapper

    if func is not None:
        return decorator(func)
    return decorator
