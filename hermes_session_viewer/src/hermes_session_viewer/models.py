from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class TimestampQuality:
    total_events: int
    exact_count: int
    estimated_count: int
    missing_count: int
    estimation_method: str
    session_start: Optional[str]
    session_end: Optional[str]
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_events": self.total_events,
            "exact_count": self.exact_count,
            "estimated_count": self.estimated_count,
            "missing_count": self.missing_count,
            "estimation_method": self.estimation_method,
            "session_start": self.session_start,
            "session_end": self.session_end,
            "notes": self.notes,
        }


@dataclass
class StandardEvent:
    event_id: str
    session_id: str
    raw_index: int
    timestamp: Optional[datetime]
    timestamp_type: str  # exact / estimated / missing
    event_type: str      # user_request / agent_plan / agent_message / tool_call /
                         # tool_result / command_exec / file_read / file_write /
                         # error / retry / quality_check / artifact_generated /
                         # final_answer / unknown
    actor: str           # user / agent / tool / system / unknown
    title: str
    natural_language_summary: str
    details: Dict[str, Any]
    tool_name: Optional[str]
    command: Optional[str]
    input_files: List[str]
    output_files: List[str]
    status: str          # success / warning / error / unknown
    raw_event: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "session_id": self.session_id,
            "raw_index": self.raw_index,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "timestamp_type": self.timestamp_type,
            "event_type": self.event_type,
            "actor": self.actor,
            "title": self.title,
            "natural_language_summary": self.natural_language_summary,
            "details": self.details,
            "tool_name": self.tool_name,
            "command": self.command,
            "input_files": self.input_files,
            "output_files": self.output_files,
            "status": self.status,
            "raw_event": self.raw_event,
        }


# L1 phase labels — keyed by lang then phase_type
PHASE_LABELS_I18N: Dict[str, Dict[str, str]] = {
    "zh": {
        "task_reception": "任务接收",
        "plan_formulation": "计划制定",
        "file_scanning": "文件扫描",
        "doc_parsing": "文档解析",
        "code_analysis": "代码分析",
        "entity_extraction": "实体提取",
        "relation_generation": "关系生成",
        "quality_check": "质量检查",
        "artifact_generation": "产出物生成",
        "error_handling": "错误处理",
        "final_summary": "最终总结",
        "other": "其他操作",
    },
    "en": {
        "task_reception": "Task Reception",
        "plan_formulation": "Plan Formulation",
        "file_scanning": "File Scanning",
        "doc_parsing": "Document Parsing",
        "code_analysis": "Code Analysis",
        "entity_extraction": "Entity Extraction",
        "relation_generation": "Relation Generation",
        "quality_check": "Quality Check",
        "artifact_generation": "Artifact Generation",
        "error_handling": "Error Handling",
        "final_summary": "Final Summary",
        "other": "Other",
    },
    "ja": {
        "task_reception": "タスク受信",
        "plan_formulation": "計画策定",
        "file_scanning": "ファイルスキャン",
        "doc_parsing": "ドキュメント解析",
        "code_analysis": "コード分析",
        "entity_extraction": "エンティティ抽出",
        "relation_generation": "リレーション生成",
        "quality_check": "品質チェック",
        "artifact_generation": "成果物生成",
        "error_handling": "エラー処理",
        "final_summary": "最終サマリー",
        "other": "その他",
    },
}

# Default (Chinese) phase labels for backwards compatibility
PHASE_LABELS = PHASE_LABELS_I18N["zh"]


@dataclass
class TimelinePhase:
    phase_id: str
    phase_type: str
    phase_label: str
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    event_count: int
    events: List[StandardEvent]
    status: str  # success / warning / error / unknown

    def to_dict(self) -> Dict[str, Any]:
        return {
            "phase_id": self.phase_id,
            "phase_type": self.phase_type,
            "phase_label": self.phase_label,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "event_count": self.event_count,
            "status": self.status,
            "events": [e.to_dict() for e in self.events],
        }
