from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from hermes_session_viewer.models import TimestampQuality


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _epoch_to_datetime(epoch: Optional[float]) -> Optional[datetime]:
    """Convert Unix epoch float to datetime."""
    if epoch is None:
        return None
    try:
        return datetime.fromtimestamp(epoch)
    except (ValueError, OSError, OverflowError):
        return None


def extract_exact_timestamps(
    messages: List[Dict[str, Any]],
) -> Tuple[List[Optional[datetime]], TimestampQuality]:
    """
    Extract exact per-message timestamps from messages loaded from state.db.

    Each message dict is expected to have a 'timestamp' field (Unix epoch float).
    Returns (list_of_datetimes, quality_report).
    """
    n = len(messages)
    timestamps: List[Optional[datetime]] = []
    exact_count = 0
    missing_count = 0

    for msg in messages:
        ts_val = msg.get("timestamp")
        dt = None
        if isinstance(ts_val, (int, float)) and ts_val > 0:
            dt = _epoch_to_datetime(ts_val)
        if dt is not None:
            exact_count += 1
        else:
            missing_count += 1
        timestamps.append(dt)

    # Determine session bounds from the data
    valid_ts = [t for t in timestamps if t is not None]
    session_start = min(valid_ts).isoformat() if valid_ts else None
    session_end = max(valid_ts).isoformat() if valid_ts else None

    notes = [
        f"从 state.db 获取精确时间戳，共 {exact_count}/{n} 条消息有精确时间戳",
    ]
    if missing_count > 0:
        notes.append(f"⚠ {missing_count} 条消息缺少时间戳")

    quality = TimestampQuality(
        total_events=n,
        exact_count=exact_count,
        estimated_count=0,
        missing_count=missing_count,
        estimation_method="exact_from_db",
        session_start=session_start,
        session_end=session_end,
        notes=notes,
    )

    return timestamps, quality


def estimate_timestamps(
    messages: List[Dict[str, Any]],
    session_start: Optional[str],
    last_updated: Optional[str],
) -> Tuple[List[Optional[datetime]], TimestampQuality]:
    """
    Estimate per-message timestamps via linear interpolation.

    Since Hermes session JSON files only carry session_start and last_updated,
    we distribute message timestamps evenly across that window. All timestamps
    are marked 'estimated'.
    
    If messages already have a 'timestamp' field (e.g. loaded from state.db),
    those are used as exact timestamps and only gaps are estimated.
    """
    n = len(messages)

    # ── Check if messages already carry per-message timestamps (from DB) ──
    has_exact = sum(
        1 for m in messages
        if isinstance(m.get("timestamp"), (int, float)) and m["timestamp"] > 0
    )
    if has_exact > 0 and has_exact >= n * 0.5:
        # Most messages have exact timestamps — use the exact path
        return extract_exact_timestamps(messages)

    # ── Fallback: linear interpolation from session_start / last_updated ──
    t_start = _parse_iso(session_start)
    t_end = _parse_iso(last_updated)

    timestamps: List[Optional[datetime]] = []

    if t_start is None and t_end is None:
        timestamps = [None] * n
        quality = TimestampQuality(
            total_events=n,
            exact_count=0,
            estimated_count=0,
            missing_count=n,
            estimation_method="none",
            session_start=session_start,
            session_end=last_updated,
            notes=["session_start 和 last_updated 均缺失，无法估算时间戳"],
        )
        return timestamps, quality

    if t_start is None:
        t_start = t_end
    if t_end is None:
        t_end = t_start

    if n == 0:
        quality = TimestampQuality(
            total_events=0,
            exact_count=0,
            estimated_count=0,
            missing_count=0,
            estimation_method="linear_interpolation",
            session_start=session_start,
            session_end=last_updated,
            notes=["消息列表为空"],
        )
        return [], quality

    total_seconds = (t_end - t_start).total_seconds()

    if n == 1:
        timestamps = [t_start]
    else:
        interval = total_seconds / (n - 1) if total_seconds > 0 else 0
        timestamps = [
            t_start + timedelta(seconds=interval * i) for i in range(n)
        ]

    notes = [
        "所有时间戳均为估算值（基于 session_start 至 last_updated 的线性插值）",
        f"会话持续时间: {total_seconds:.1f} 秒",
        f"平均每条消息间隔: {total_seconds / max(n - 1, 1):.2f} 秒",
    ]

    quality = TimestampQuality(
        total_events=n,
        exact_count=0,
        estimated_count=n,
        missing_count=0,
        estimation_method="linear_interpolation",
        session_start=session_start,
        session_end=last_updated,
        notes=notes,
    )

    return timestamps, quality
