from __future__ import annotations

from typing import List

from hermes_session_viewer.models import PHASE_LABELS, StandardEvent, TimelinePhase


def aggregate_phases(events: List[StandardEvent], session_id: str) -> List[TimelinePhase]:
    """
    Group events into TimelinePhase objects.

    Events are grouped into contiguous runs of the same phase. A new phase
    segment is started when the phase label changes.
    """
    if not events:
        return []

    phases: List[TimelinePhase] = []
    current_phase: str = events[0].details.get("phase", "other")
    current_events: List[StandardEvent] = []
    phase_counter: dict = {}

    def _flush(phase_type: str, evts: List[StandardEvent]) -> None:
        if not evts:
            return
        phase_counter[phase_type] = phase_counter.get(phase_type, 0) + 1
        phase_id = f"{session_id}_{phase_type}_{phase_counter[phase_type]:02d}"

        start_time = next((e.timestamp for e in evts if e.timestamp), None)
        end_time = next((e.timestamp for e in reversed(evts) if e.timestamp), None)

        # Determine overall status
        statuses = [e.status for e in evts]
        if "error" in statuses:
            overall_status = "error"
        elif "warning" in statuses:
            overall_status = "warning"
        elif all(s == "success" for s in statuses):
            overall_status = "success"
        else:
            overall_status = "unknown"

        phases.append(TimelinePhase(
            phase_id=phase_id,
            phase_type=phase_type,
            phase_label=PHASE_LABELS.get(phase_type, phase_type),
            start_time=start_time,
            end_time=end_time,
            event_count=len(evts),
            events=list(evts),
            status=overall_status,
        ))

    for event in events:
        ep = event.details.get("phase", "other")
        if ep != current_phase:
            _flush(current_phase, current_events)
            current_phase = ep
            current_events = [event]
        else:
            current_events.append(event)

    _flush(current_phase, current_events)
    return phases
