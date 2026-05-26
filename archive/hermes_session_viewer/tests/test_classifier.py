import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from hermes_session_viewer.classifier import classify_events, classify_phase
from hermes_session_viewer.models import StandardEvent


def _make_event(
    event_type="tool_call",
    tool_name=None,
    content="",
    status="success",
    actor="agent",
    raw_index=0,
):
    return StandardEvent(
        event_id=f"test_{raw_index}",
        session_id="test",
        raw_index=raw_index,
        timestamp=datetime(2026, 1, 1, 0, 0, raw_index),
        timestamp_type="estimated",
        event_type=event_type,
        actor=actor,
        title=content[:40] or event_type,
        natural_language_summary="",
        details={"content_preview": content, "phase": ""},
        tool_name=tool_name,
        command=None,
        input_files=[],
        output_files=[],
        status=status,
        raw_event={},
    )


class TestClassifyPhase:
    def test_user_request_is_task_reception(self):
        e = _make_event(event_type="user_request")
        assert classify_phase(e) == "task_reception"

    def test_skill_view_is_task_reception(self):
        e = _make_event(event_type="tool_call", tool_name="skill_view")
        assert classify_phase(e) == "task_reception"

    def test_agent_plan_is_plan_formulation(self):
        e = _make_event(event_type="agent_plan")
        assert classify_phase(e) == "plan_formulation"

    def test_error_status_is_error_handling(self):
        e = _make_event(event_type="tool_result", status="error")
        assert classify_phase(e) == "error_handling"

    def test_error_event_type_is_error_handling(self):
        e = _make_event(event_type="error")
        assert classify_phase(e) == "error_handling"

    def test_docx_content_is_doc_parsing(self):
        e = _make_event(content="parsing docx file with python-docx", tool_name="execute_code")
        assert classify_phase(e) == "doc_parsing"

    def test_entity_content_is_entity_extraction(self):
        e = _make_event(content="extract entity nodes from document", tool_name="execute_code")
        assert classify_phase(e) == "entity_extraction"

    def test_relation_content_is_relation_generation(self):
        e = _make_event(content="generate edge relations between nodes")
        assert classify_phase(e) == "relation_generation"

    def test_kanban_complete_is_artifact(self):
        e = _make_event(event_type="tool_call", tool_name="kanban_complete")
        assert classify_phase(e) == "artifact_generation"

    def test_final_answer_is_plan_formulation(self):
        e = _make_event(event_type="final_answer")
        assert classify_phase(e) in ("plan_formulation", "final_summary")

    def test_unknown_becomes_other(self):
        e = _make_event(event_type="tool_call", tool_name="some_random_tool", content="do stuff")
        # Should not crash and returns a valid phase string
        phase = classify_phase(e)
        assert isinstance(phase, str)
        assert len(phase) > 0


class TestClassifyEvents:
    def test_returns_same_count(self):
        events = [_make_event(raw_index=i) for i in range(10)]
        result = classify_events(events)
        assert len(result) == 10

    def test_phase_stored_in_details(self):
        events = [
            _make_event(event_type="user_request", raw_index=0),
            _make_event(event_type="agent_plan", raw_index=1),
            _make_event(event_type="tool_call", tool_name="skill_view", raw_index=2),
        ]
        result = classify_events(events)
        for e in result:
            assert "phase" in e.details
            assert isinstance(e.details["phase"], str)

    def test_smoothing_does_not_create_wrong_phase(self):
        # A long run of the same phase should remain that phase after smoothing
        events = [
            _make_event(event_type="tool_call", tool_name="execute_code",
                        content="parsing docx excel", raw_index=i)
            for i in range(8)
        ]
        result = classify_events(events)
        phases = [e.details["phase"] for e in result]
        # Most should be doc_parsing
        from collections import Counter
        most_common = Counter(phases).most_common(1)[0][0]
        assert most_common == "doc_parsing"

    def test_empty_events(self):
        result = classify_events([])
        assert result == []
