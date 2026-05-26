from __future__ import annotations

import re
from typing import List

from hermes_session_viewer.models import StandardEvent


# Phase heuristics: ordered from most specific to least
# Each entry: (phase_type, match_fn)
# match_fn(event) -> bool

def _tool_is(event: StandardEvent, *names: str) -> bool:
    return (event.tool_name or "").lower() in {n.lower() for n in names}


def _content_has(event: StandardEvent, *keywords: str) -> bool:
    text = (event.title + " " + event.details.get("content_preview", "")).lower()
    return any(kw.lower() in text for kw in keywords)


def _tool_contains(event: StandardEvent, *patterns: str) -> bool:
    name = (event.tool_name or "").lower()
    return any(p.lower() in name for p in patterns)


_PHASE_RULES = [
    # task_reception: first user message or skill loading
    ("task_reception", lambda e: e.event_type == "user_request"),
    ("task_reception", lambda e: _tool_is(e, "skill_view", "memory", "kanban_show")),

    # plan_formulation: agent thinking/planning text
    ("plan_formulation", lambda e: e.event_type == "agent_plan"),
    ("plan_formulation", lambda e: e.event_type == "final_answer"),

    # error_handling: errors and retries
    ("error_handling", lambda e: e.status == "error"),
    ("error_handling", lambda e: e.event_type in ("error", "retry")),
    ("error_handling", lambda e: _content_has(e, "retry", "重试", "traceback", "exception", "error", "failed")),

    # quality_check: kanban_block and clarify signal human review/blocking
    ("quality_check", lambda e: e.event_type == "quality_check"),
    ("quality_check", lambda e: _tool_is(e, "kanban_block", "clarify")),
    ("quality_check", lambda e: _content_has(e, "验证", "质量", "检查", "校验", "validate", "verify", "quality")),

    # artifact_generation: final output writing / task completion
    ("artifact_generation", lambda e: e.event_type == "artifact_generated"),
    ("artifact_generation", lambda e: _tool_is(e, "kanban_complete") and e.status != "error"),
    ("artifact_generation", lambda e: e.event_type == "file_write" and _content_has(e, ".json", ".html", ".csv", ".gremlin", "neptune", "graph")),

    # final_summary
    ("final_summary", lambda e: e.event_type == "final_answer"),

    # file_scanning: ls, find, glob operations
    ("file_scanning", lambda e: _tool_contains(e, "list", "scan", "find", "glob", "ls", "walk")),
    ("file_scanning", lambda e: _content_has(e, "扫描", "列举", "目录", "文件列表", "ls ", "find ", "glob", "scan")),
    ("file_scanning", lambda e: _tool_is(e, "s3_list", "list_files", "list_dir")),

    # doc_parsing: document parsing
    ("doc_parsing", lambda e: _tool_contains(e, "doc", "parse", "extract", "read")),
    ("doc_parsing", lambda e: _content_has(e, "解析", "docx", "xlsx", "xls", "pdf", "parse", "word", "excel")),
    ("doc_parsing", lambda e: _tool_is(e, "execute_code") and _content_has(e, "docx", "xlsx", "xls", "openpyxl", "python-docx")),

    # code_analysis: source code analysis
    ("code_analysis", lambda e: _content_has(e, "源码", "source code", "代码分析", "class ", "function ", "import ", "sql", "ddl", "schema")),
    ("code_analysis", lambda e: _tool_is(e, "execute_code") and _content_has(e, ".py", ".java", ".js", ".ts", ".sql", ".sh")),

    # relation_generation: relationship/edge generation — before entity_extraction
    # because "edge/relation" is more specific than "node"
    ("relation_generation", lambda e: _content_has(e, "relation", "edge", "边", "连接") and not _content_has(e, "实体", "entity")),
    ("relation_generation", lambda e: _content_has(e, "关系") and not _content_has(e, "实体")),
    ("relation_generation", lambda e: _tool_is(e, "execute_code") and _content_has(e, "edge", "relation", "gremlin")),

    # entity_extraction: LLM entity extraction
    ("entity_extraction", lambda e: _content_has(e, "实体", "entity", "node", "节点", "提取", "extract")),
    ("entity_extraction", lambda e: _tool_is(e, "execute_code") and _content_has(e, "entity", "node", "gremlin")),

    # artifact_generation catch-all for generic output keywords
    ("artifact_generation", lambda e: _content_has(e, "生成", "导出", "输出", "artifact", "output", "export", "generate")),
]


def classify_phase(event: StandardEvent) -> str:
    """Return the L1 phase type for an event."""
    for phase_type, rule_fn in _PHASE_RULES:
        try:
            if rule_fn(event):
                return phase_type
        except Exception:
            continue
    return "other"


def classify_events(events: List[StandardEvent]) -> List[StandardEvent]:
    """
    Classify all events and store phase in event.details['phase'].
    Uses positional context: once a phase starts, nearby similar events
    are grouped together.
    """
    # First pass: assign phase to each event
    raw_phases = [classify_phase(e) for e in events]

    # Second pass: smooth phase transitions using a small window
    # (avoid single-event phase islands between the same phase)
    smoothed = list(raw_phases)
    window = 3
    for i in range(1, len(smoothed) - 1):
        if smoothed[i] == "other":
            # Check if neighbours agree on a phase
            left = smoothed[max(0, i - window) : i]
            right = smoothed[i + 1 : min(len(smoothed), i + window + 1)]
            neighbour_phases = left + right
            non_other = [p for p in neighbour_phases if p != "other"]
            if non_other:
                # Use most common neighbour phase
                from collections import Counter
                most_common = Counter(non_other).most_common(1)[0][0]
                smoothed[i] = most_common

    # Attach phase to event details
    for event, phase in zip(events, smoothed):
        event.details["phase"] = phase

    return events
