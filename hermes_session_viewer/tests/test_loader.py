import json
import tempfile
import os
import pytest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from hermes_session_viewer.loader import (
    SessionLoadError,
    extract_session_metadata,
    load_session,
)


def _write_json(data, suffix=".json"):
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=suffix, delete=False, encoding="utf-8"
    )
    json.dump(data, f, ensure_ascii=False)
    f.close()
    return f.name


VALID_SESSION = {
    "session_id": "test_001",
    "model": "claude-test",
    "platform": "cli",
    "session_start": "2026-01-01T00:00:00",
    "last_updated": "2026-01-01T00:10:00",
    "message_count": 2,
    "tools": [{"type": "function", "function": {"name": "bash"}}],
    "messages": [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there", "tool_calls": []},
    ],
}


class TestLoadSession:
    def test_load_valid(self):
        path = _write_json(VALID_SESSION)
        try:
            data = load_session(path)
            assert data["session_id"] == "test_001"
            assert len(data["messages"]) == 2
        finally:
            os.unlink(path)

    def test_missing_file(self):
        with pytest.raises(SessionLoadError, match="不存在"):
            load_session("/nonexistent/path/file.json")

    def test_invalid_json(self):
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        )
        f.write("{ not valid json }")
        f.close()
        try:
            with pytest.raises(SessionLoadError, match="JSON"):
                load_session(f.name)
        finally:
            os.unlink(f.name)

    def test_missing_required_key_session_id(self):
        bad = dict(VALID_SESSION)
        del bad["session_id"]
        path = _write_json(bad)
        try:
            with pytest.raises(SessionLoadError, match="缺少"):
                load_session(path)
        finally:
            os.unlink(path)

    def test_missing_messages_key(self):
        bad = {"session_id": "x"}
        path = _write_json(bad)
        try:
            with pytest.raises(SessionLoadError, match="缺少"):
                load_session(path)
        finally:
            os.unlink(path)

    def test_messages_not_list(self):
        bad = dict(VALID_SESSION)
        bad["messages"] = "not a list"
        path = _write_json(bad)
        try:
            with pytest.raises(SessionLoadError, match="数组"):
                load_session(path)
        finally:
            os.unlink(path)

    def test_not_a_dict(self):
        path = _write_json([1, 2, 3])
        try:
            with pytest.raises(SessionLoadError, match="对象"):
                load_session(path)
        finally:
            os.unlink(path)


class TestExtractMetadata:
    def test_full_metadata(self):
        path = _write_json(VALID_SESSION)
        try:
            data = load_session(path)
            meta = extract_session_metadata(data)
            assert meta["session_id"] == "test_001"
            assert meta["model"] == "claude-test"
            assert meta["tools_count"] == 1
            assert meta["message_count"] == 2
        finally:
            os.unlink(path)

    def test_missing_optional_fields(self):
        minimal = {"session_id": "x", "messages": []}
        meta = extract_session_metadata(minimal)
        assert meta["session_id"] == "x"
        assert meta["model"] == "unknown"
        assert meta["tools_count"] == 0
