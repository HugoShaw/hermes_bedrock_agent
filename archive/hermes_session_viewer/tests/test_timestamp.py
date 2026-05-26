import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from hermes_session_viewer.timestamp import estimate_timestamps


MESSAGES_5 = [{"role": "user", "content": str(i)} for i in range(5)]
START = "2026-01-01T00:00:00"
END = "2026-01-01T00:04:00"  # 240 seconds later


class TestEstimateTimestamps:
    def test_basic_interpolation(self):
        ts, quality = estimate_timestamps(MESSAGES_5, START, END)
        assert len(ts) == 5
        # First timestamp should equal session_start
        assert ts[0] == datetime(2026, 1, 1, 0, 0, 0)
        # Last timestamp should equal last_updated
        assert ts[-1] == datetime(2026, 1, 1, 0, 4, 0)
        # Timestamps should be monotonically increasing
        for a, b in zip(ts, ts[1:]):
            assert b >= a

    def test_all_estimated(self):
        ts, quality = estimate_timestamps(MESSAGES_5, START, END)
        assert quality.exact_count == 0
        assert quality.estimated_count == 5
        assert quality.missing_count == 0
        assert quality.estimation_method == "linear_interpolation"

    def test_equal_intervals(self):
        ts, quality = estimate_timestamps(MESSAGES_5, START, END)
        # 240 seconds / 4 intervals = 60 seconds each
        for a, b in zip(ts, ts[1:]):
            diff = (b - a).total_seconds()
            assert abs(diff - 60.0) < 0.01

    def test_single_message(self):
        msgs = [{"role": "user", "content": "hi"}]
        ts, quality = estimate_timestamps(msgs, START, END)
        assert len(ts) == 1
        assert ts[0] == datetime(2026, 1, 1, 0, 0, 0)

    def test_empty_messages(self):
        ts, quality = estimate_timestamps([], START, END)
        assert ts == []
        assert quality.total_events == 0

    def test_missing_start_falls_back_to_end(self):
        ts, quality = estimate_timestamps(MESSAGES_5, None, END)
        assert all(t == datetime(2026, 1, 1, 0, 4, 0) for t in ts)

    def test_missing_both_timestamps(self):
        ts, quality = estimate_timestamps(MESSAGES_5, None, None)
        assert all(t is None for t in ts)
        assert quality.missing_count == 5
        assert quality.estimation_method == "none"

    def test_same_start_and_end(self):
        ts, quality = estimate_timestamps(MESSAGES_5, START, START)
        assert all(t == datetime(2026, 1, 1, 0, 0, 0) for t in ts)

    def test_quality_notes_present(self):
        _, quality = estimate_timestamps(MESSAGES_5, START, END)
        assert len(quality.notes) > 0
        assert any("估算" in n for n in quality.notes)
