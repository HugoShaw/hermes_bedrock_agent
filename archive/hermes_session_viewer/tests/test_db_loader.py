"""Tests for db_loader module."""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from hermes_session_viewer.db_loader import (
    find_session_in_db,
    list_sessions_in_db,
    load_session_from_db,
)
from hermes_session_viewer.loader import SessionLoadError


@pytest.fixture
def sample_db(tmp_path):
    """Create a temporary SQLite DB mimicking Hermes state.db."""
    db_path = tmp_path / "state.db"
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Create minimal schema
    cursor.execute("""
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            user_id TEXT,
            model TEXT,
            model_config TEXT,
            system_prompt TEXT,
            parent_session_id TEXT,
            started_at REAL NOT NULL,
            ended_at REAL,
            end_reason TEXT,
            message_count INTEGER DEFAULT 0,
            tool_call_count INTEGER DEFAULT 0,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            cache_read_tokens INTEGER DEFAULT 0,
            cache_write_tokens INTEGER DEFAULT 0,
            reasoning_tokens INTEGER DEFAULT 0,
            billing_provider TEXT,
            billing_base_url TEXT,
            billing_mode TEXT,
            estimated_cost_usd REAL,
            actual_cost_usd REAL,
            cost_status TEXT,
            cost_source TEXT,
            pricing_version TEXT,
            title TEXT,
            api_call_count INTEGER DEFAULT 0,
            handoff_state TEXT,
            handoff_platform TEXT,
            handoff_error TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT,
            tool_call_id TEXT,
            tool_calls TEXT,
            tool_name TEXT,
            timestamp REAL NOT NULL,
            token_count INTEGER,
            finish_reason TEXT,
            reasoning TEXT,
            reasoning_content TEXT,
            reasoning_details TEXT,
            codex_reasoning_items TEXT,
            codex_message_items TEXT
        )
    """)

    # Insert test data
    cursor.execute("""
        INSERT INTO sessions (id, source, model, system_prompt, started_at, ended_at,
                             message_count, tool_call_count, input_tokens, output_tokens,
                             estimated_cost_usd, title)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        "test_session_001", "cli", "claude-opus-4",
        "You are a helpful assistant.",
        1700000000.0, 1700000060.0,
        3, 1, 1000, 500, 0.05, "Test Session"
    ))

    # Insert messages
    cursor.execute("""
        INSERT INTO messages (session_id, role, content, timestamp)
        VALUES (?, ?, ?, ?)
    """, ("test_session_001", "user", "Hello, please help me.", 1700000010.0))

    cursor.execute("""
        INSERT INTO messages (session_id, role, content, tool_calls, timestamp, finish_reason)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        "test_session_001", "assistant", "",
        '[{"id": "call_1", "type": "function", "function": {"name": "terminal", "arguments": "{\\"command\\": \\"ls -la\\"}"}}]',
        1700000020.0, "tool_calls"
    ))

    cursor.execute("""
        INSERT INTO messages (session_id, role, content, tool_call_id, timestamp)
        VALUES (?, ?, ?, ?, ?)
    """, ("test_session_001", "tool", '{"output": "file1.txt\\nfile2.py", "exit_code": 0}', "call_1", 1700000030.0))

    conn.commit()
    conn.close()
    return str(db_path)


class TestFindSessionInDb:
    def test_existing_session(self, sample_db):
        assert find_session_in_db("test_session_001", db_path=sample_db) is True

    def test_missing_session(self, sample_db):
        assert find_session_in_db("nonexistent", db_path=sample_db) is False

    def test_missing_db_file(self):
        assert find_session_in_db("test", db_path="/tmp/no_such_file.db") is False


class TestListSessionsInDb:
    def test_list_returns_sessions(self, sample_db):
        sessions = list_sessions_in_db(db_path=sample_db)
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "test_session_001"
        assert sessions[0]["model"] == "claude-opus-4"
        assert sessions[0]["title"] == "Test Session"
        assert sessions[0]["message_count"] == 3

    def test_list_missing_db(self):
        sessions = list_sessions_in_db(db_path="/tmp/no_such_file.db")
        assert sessions == []


class TestLoadSessionFromDb:
    def test_load_success(self, sample_db):
        data = load_session_from_db("test_session_001", db_path=sample_db)
        assert data["session_id"] == "test_session_001"
        assert data["model"] == "claude-opus-4"
        assert data["message_count"] == 3
        assert data["_source"] == "state_db"
        assert len(data["messages"]) == 3

    def test_messages_have_timestamps(self, sample_db):
        data = load_session_from_db("test_session_001", db_path=sample_db)
        msgs = data["messages"]
        assert msgs[0]["timestamp"] == 1700000010.0
        assert msgs[1]["timestamp"] == 1700000020.0
        assert msgs[2]["timestamp"] == 1700000030.0

    def test_messages_have_roles(self, sample_db):
        data = load_session_from_db("test_session_001", db_path=sample_db)
        msgs = data["messages"]
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"
        assert msgs[2]["role"] == "tool"

    def test_tool_calls_parsed(self, sample_db):
        data = load_session_from_db("test_session_001", db_path=sample_db)
        msgs = data["messages"]
        assert "tool_calls" in msgs[1]
        assert msgs[1]["tool_calls"][0]["function"]["name"] == "terminal"

    def test_db_metadata_present(self, sample_db):
        data = load_session_from_db("test_session_001", db_path=sample_db)
        meta = data["_db_metadata"]
        assert meta["title"] == "Test Session"
        assert meta["tool_call_count"] == 1
        assert meta["input_tokens"] == 1000
        assert meta["estimated_cost_usd"] == 0.05

    def test_missing_session_raises(self, sample_db):
        with pytest.raises(SessionLoadError, match="未找到"):
            load_session_from_db("nonexistent", db_path=sample_db)

    def test_missing_db_raises(self):
        with pytest.raises(SessionLoadError, match="不存在"):
            load_session_from_db("test", db_path="/tmp/no_such_file.db")


class TestExactTimestampsIntegration:
    """Test that DB-loaded messages produce exact timestamps through the pipeline."""

    def test_exact_timestamps_from_db_messages(self, sample_db):
        from hermes_session_viewer.timestamp import estimate_timestamps

        data = load_session_from_db("test_session_001", db_path=sample_db)
        timestamps, quality = estimate_timestamps(
            data["messages"],
            data["session_start"],
            data["last_updated"],
        )
        # All timestamps should be exact (from DB epoch fields)
        assert quality.estimation_method == "exact_from_db"
        assert quality.exact_count == 3
        assert quality.estimated_count == 0
        assert quality.missing_count == 0
        # Verify actual datetime values
        assert timestamps[0].timestamp() == 1700000010.0
        assert timestamps[1].timestamp() == 1700000020.0
        assert timestamps[2].timestamp() == 1700000030.0
