"""
Logging setup and stage-timing utilities for the semantic map workflow.

All public symbols use only the Python standard library.
"""

from __future__ import annotations

import logging
import sys
import time
from contextlib import contextmanager
from typing import Any, Generator, Optional


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------

_LOG_FORMAT = "%(asctime)s [%(levelname)-8s] %(name)s - %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


# ---------------------------------------------------------------------------
# setup_logging
# ---------------------------------------------------------------------------

def setup_logging(
    level: int | str = logging.INFO,
    log_file: Optional[str] = None,
    *,
    logger_name: str = "semantic_map",
    propagate: bool = False,
) -> logging.Logger:
    """
    Configure and return a named logger.

    Args:
        level:       Log level (``logging.DEBUG``, ``"INFO"``, etc.).
        log_file:    Optional path to a log file.  If provided a
                     ``FileHandler`` is added in addition to the stream handler.
        logger_name: Name of the root logger to configure (default
                     ``"semantic_map"``).
        propagate:   Whether the logger propagates to the root logger
                     (default ``False``).

    Returns:
        The configured :class:`logging.Logger`.
    """
    if isinstance(level, str):
        level = logging.getLevelName(level.upper())

    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    logger.propagate = propagate

    # Avoid adding duplicate handlers on repeated calls
    if logger.handlers:
        return logger

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    # Console handler (stderr)
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setLevel(level)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    # Optional file handler
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


# ---------------------------------------------------------------------------
# get_logger
# ---------------------------------------------------------------------------

def get_logger(name: str) -> logging.Logger:
    """
    Return a child logger under the ``"semantic_map"`` namespace.

    If ``name`` already starts with ``"semantic_map"`` it is used as-is,
    otherwise ``"semantic_map.{name}"`` is returned.

    Callers should invoke :func:`setup_logging` once at startup to ensure
    handlers are attached to the root logger.
    """
    if name.startswith("semantic_map"):
        return logging.getLogger(name)
    return logging.getLogger(f"semantic_map.{name}")


# ---------------------------------------------------------------------------
# StageTimer context manager
# ---------------------------------------------------------------------------

class StageTimer:
    """
    Context manager that measures elapsed wall-clock time for a named stage
    and logs the result on exit.

    Usage::

        with StageTimer(logger, "Stage 3 – entity extraction"):
            do_work()
    """

    def __init__(
        self,
        logger: logging.Logger,
        stage_name: str,
        *,
        log_level: int = logging.INFO,
    ) -> None:
        self._logger = logger
        self._stage_name = stage_name
        self._log_level = log_level
        self._start: float = 0.0

    def __enter__(self) -> "StageTimer":
        self._start = time.perf_counter()
        self._logger.log(
            self._log_level,
            ">>> START  %s",
            self._stage_name,
        )
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        elapsed = time.perf_counter() - self._start
        if exc_type is None:
            self._logger.log(
                self._log_level,
                "<<< FINISH %s  [%.2fs]",
                self._stage_name,
                elapsed,
            )
        else:
            self._logger.error(
                "<<< ERROR  %s  [%.2fs]  %s: %s",
                self._stage_name,
                elapsed,
                exc_type.__name__,
                exc_val,
            )
        # Do not suppress exceptions
        return None

    @property
    def elapsed(self) -> float:
        """Elapsed seconds since the context was entered (0 if not started)."""
        if self._start == 0.0:
            return 0.0
        return time.perf_counter() - self._start


# ---------------------------------------------------------------------------
# Stage lifecycle helpers
# ---------------------------------------------------------------------------

def log_stage_start(
    logger: logging.Logger,
    stage_num: int | str,
    stage_name: str,
) -> None:
    """
    Log a standardized start banner for a pipeline stage.

    Args:
        logger:     Logger to write to.
        stage_num:  Numeric (or string) stage identifier, e.g. ``3``.
        stage_name: Human-readable stage name.
    """
    logger.info(
        "=" * 60,
    )
    logger.info(
        "STAGE %s START  |  %s",
        stage_num,
        stage_name,
    )
    logger.info(
        "=" * 60,
    )


def log_stage_end(
    logger: logging.Logger,
    stage_num: int | str,
    stage_name: str,
    counts_dict: dict[str, Any],
) -> None:
    """
    Log a standardized completion summary for a pipeline stage.

    Args:
        logger:      Logger to write to.
        stage_num:   Numeric (or string) stage identifier.
        stage_name:  Human-readable stage name.
        counts_dict: Arbitrary key-value pairs to include in the summary
                     (e.g. ``{"nodes": 42, "edges": 100}``).
    """
    summary_parts = "  ".join(
        f"{k}={v}" for k, v in counts_dict.items()
    )
    logger.info(
        "-" * 60,
    )
    logger.info(
        "STAGE %s END    |  %s",
        stage_num,
        stage_name,
    )
    if summary_parts:
        logger.info("  Summary: %s", summary_parts)
    logger.info(
        "-" * 60,
    )
