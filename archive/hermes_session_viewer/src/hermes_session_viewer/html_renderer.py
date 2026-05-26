from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from hermes_session_viewer.i18n import TRANSLATIONS
from hermes_session_viewer.models import TimestampQuality, TimelinePhase
from hermes_session_viewer.utils import sanitize_html, truncate

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
_CSS = """
:root {
  --bg: #0f1117;
  --bg2: #161b22;
  --bg3: #1c2333;
  --bg4: #21262d;
  --border: #30363d;
  --text: #e6edf3;
  --text2: #8b949e;
  --accent: #58a6ff;
  --accent2: #3fb950;
  --warn: #d29922;
  --err: #f85149;
  --purple: #a371f7;
  --cyan: #39c5cf;
  --phase-task: #1f6feb;
  --phase-plan: #a371f7;
  --phase-scan: #3fb950;
  --phase-parse: #58a6ff;
  --phase-code: #ffa657;
  --phase-entity: #39c5cf;
  --phase-rel: #d29922;
  --phase-quality: #e3b341;
  --phase-artifact: #79c0ff;
  --phase-error: #f85149;
  --phase-summary: #56d364;
  --phase-other: #8b949e;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
  font-size: 14px;
  line-height: 1.6;
  min-height: 100vh;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

/* ── Header ── */
.header {
  background: linear-gradient(135deg, #0d1117 0%, #161b22 100%);
  border-bottom: 1px solid var(--border);
  padding: 24px 32px;
  position: sticky;
  top: 0;
  z-index: 100;
}
.header-top { display: flex; align-items: center; justify-content: space-between; }
.header h1 { font-size: 20px; color: var(--text); font-weight: 600; }
.header h1 span { color: var(--accent); }
.header-meta { display: flex; flex-wrap: wrap; gap: 16px; margin-top: 8px; }
.meta-badge {
  background: var(--bg3);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 4px 10px;
  font-size: 12px;
  color: var(--text2);
}
.meta-badge strong { color: var(--text); }

/* ── Language switcher ── */
.lang-switcher {
  display: flex;
  gap: 4px;
  background: var(--bg3);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 3px;
}
.lang-btn {
  background: transparent;
  border: none;
  border-radius: 4px;
  color: var(--text2);
  cursor: pointer;
  font-size: 12px;
  font-weight: 500;
  padding: 4px 10px;
  transition: all 0.15s;
}
.lang-btn:hover { color: var(--text); background: var(--bg4); }
.lang-btn.active { background: var(--accent); color: #fff; }

/* ── Timestamp quality ── */
.ts-quality-bar {
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 20px;
  margin: 16px 0;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.ts-quality-bar .label { color: var(--text2); font-size: 12px; }
.ts-pill {
  border-radius: 12px;
  padding: 2px 10px;
  font-size: 11px;
  font-weight: 600;
}
.ts-estimated { background: #2d1f00; color: var(--warn); border: 1px solid #6e4c00; }
.ts-exact-pill { background: #0d2f1a; color: var(--accent2); border: 1px solid #238636; }
.ts-missing-pill { background: #3a1414; color: var(--err); border: 1px solid #da3633; }
.ts-note { color: var(--text2); font-size: 11px; font-style: italic; }

/* ── Main layout ── */
.container { max-width: 1200px; margin: 0 auto; padding: 24px 32px; }

/* ── Stats ── */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
  margin-bottom: 24px;
}
.stat-card {
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 16px;
  text-align: center;
}
.stat-card .num { font-size: 28px; font-weight: 700; color: var(--accent); }
.stat-card .lbl { color: var(--text2); font-size: 12px; margin-top: 4px; }

/* ── Timeline controls ── */
.timeline-controls {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
  flex-wrap: wrap;
  align-items: center;
}
.btn {
  background: var(--bg3);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text);
  cursor: pointer;
  font-size: 12px;
  padding: 6px 14px;
  transition: background 0.15s;
}
.btn:hover { background: var(--bg4); border-color: var(--accent); }
.search-input {
  background: var(--bg3);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text);
  font-size: 13px;
  padding: 6px 12px;
  width: 240px;
  outline: none;
}
.search-input:focus { border-color: var(--accent); }
.timeline-info { color: var(--text2); font-size: 12px; margin-left: auto; }

/* ── L1 Phase blocks ── */
.phase-block {
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: 10px;
  margin-bottom: 12px;
  overflow: hidden;
  transition: border-color 0.15s;
}
.phase-block:hover { border-color: #484f58; }

details > summary { list-style: none; cursor: pointer; }
details > summary::-webkit-details-marker { display: none; }

.phase-summary {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 18px;
  user-select: none;
  background: var(--bg2);
}
.phase-summary:hover { background: var(--bg3); }

.phase-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}
.phase-expand-icon {
  color: var(--text2);
  font-size: 11px;
  margin-left: auto;
  transition: transform 0.2s;
}
details[open] .phase-expand-icon { transform: rotate(90deg); }

.phase-name {
  font-weight: 600;
  font-size: 14px;
  min-width: 100px;
}
.phase-time { color: var(--text2); font-size: 12px; }
.phase-count {
  background: var(--bg4);
  border-radius: 10px;
  color: var(--text2);
  font-size: 11px;
  padding: 1px 8px;
}
.status-dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}
.status-success { background: var(--accent2); }
.status-error { background: var(--err); }
.status-warning { background: var(--warn); }
.status-unknown { background: var(--text2); }

/* ── L2 Event list ── */
.events-list { padding: 0 14px 14px; }

.event-item {
  background: var(--bg3);
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 8px;
  overflow: hidden;
}
.event-item:hover { border-color: #484f58; }

.event-summary {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 14px;
  cursor: pointer;
  user-select: none;
}
.event-summary:hover { background: var(--bg4); }

.event-type-badge {
  border-radius: 4px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.3px;
  padding: 2px 7px;
  flex-shrink: 0;
  margin-top: 2px;
}
.badge-tool_call, .badge-command_exec { background: #1a2e4a; color: #79c0ff; }
.badge-tool_result { background: #162312; color: #7ee787; }
.badge-user_request { background: #2a1f5a; color: #d2a8ff; }
.badge-agent_plan { background: #1e2433; color: #a371f7; }
.badge-agent_message { background: #1e2433; color: #8b949e; }
.badge-file_read { background: #1a2e1a; color: #56d364; }
.badge-file_write { background: #2e2a1a; color: #e3b341; }
.badge-error, .badge-retry { background: #3a1414; color: #f85149; }
.badge-final_answer { background: #122e1a; color: #3fb950; }
.badge-quality_check { background: #2e2a00; color: var(--warn); }
.badge-artifact_generated { background: #102244; color: var(--accent); }
.badge-unknown { background: var(--bg4); color: var(--text2); }

.event-summary-text {
  flex: 1;
  font-size: 13px;
  line-height: 1.5;
}
.event-tool-tag {
  color: var(--cyan);
  font-size: 11px;
  font-family: 'Consolas', 'Courier New', monospace;
  background: #0d2233;
  border-radius: 3px;
  padding: 1px 6px;
  margin-left: 6px;
  flex-shrink: 0;
}
.event-ts { color: var(--text2); font-size: 11px; flex-shrink: 0; margin-top: 3px; }

/* ── L3 Raw JSON ── */
.raw-details-wrapper {
  padding: 0 14px 10px;
}
.raw-details-toggle {
  background: none;
  border: none;
  color: var(--text2);
  cursor: pointer;
  font-size: 11px;
  padding: 4px 0;
  display: flex;
  align-items: center;
  gap: 4px;
}
.raw-details-toggle:hover { color: var(--accent); }

.raw-json-block {
  background: #0d1117;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-family: 'Consolas', 'Courier New', monospace;
  font-size: 11px;
  line-height: 1.5;
  max-height: 400px;
  overflow: auto;
  padding: 12px 14px;
  white-space: pre;
  color: #e6edf3;
  margin-top: 6px;
}
.raw-json-block .jk { color: #79c0ff; }
.raw-json-block .jv-str { color: #a5d6ff; }
.raw-json-block .jv-num { color: #ffa657; }
.raw-json-block .jv-bool { color: #ff7b72; }
.raw-json-block .jv-null { color: #8b949e; }

/* ── Phase colour map ── */
.phase-task_reception .phase-dot { background: var(--phase-task); }
.phase-plan_formulation .phase-dot { background: var(--phase-plan); }
.phase-file_scanning .phase-dot { background: var(--phase-scan); }
.phase-doc_parsing .phase-dot { background: var(--phase-parse); }
.phase-code_analysis .phase-dot { background: var(--phase-code); }
.phase-entity_extraction .phase-dot { background: var(--phase-entity); }
.phase-relation_generation .phase-dot { background: var(--phase-rel); }
.phase-quality_check .phase-dot { background: var(--phase-quality); }
.phase-artifact_generation .phase-dot { background: var(--phase-artifact); }
.phase-error_handling .phase-dot { background: var(--phase-error); }
.phase-final_summary .phase-dot { background: var(--phase-summary); }
.phase-other .phase-dot { background: var(--phase-other); }

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: var(--bg); }
::-webkit-scrollbar-thumb { background: #30363d; border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: #484f58; }

/* ── Highlight ── */
.hl { background: #2d2a00; color: #e3b341; border-radius: 2px; padding: 0 2px; }

/* ── Footer ── */
.footer {
  border-top: 1px solid var(--border);
  color: var(--text2);
  font-size: 12px;
  margin-top: 48px;
  padding: 20px 32px;
  text-align: center;
}

/* ── Responsive ── */
@media (max-width: 640px) {
  .container { padding: 12px 16px; }
  .header { padding: 16px; }
  .stats-grid { grid-template-columns: repeat(2, 1fr); }
  .search-input { width: 160px; }
}
"""


# ---------------------------------------------------------------------------
# Helper renderers
# ---------------------------------------------------------------------------

def _fmt_time(dt: Optional[datetime]) -> str:
    if dt is None:
        return "—"
    return dt.strftime("%H:%M:%S")


def _fmt_datetime(dt: Optional[datetime]) -> str:
    if dt is None:
        return "—"
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _render_event(event: Any) -> str:
    etype = event.event_type
    tool = sanitize_html(event.tool_name or "")
    ts = _fmt_time(event.timestamp)

    # Get summaries for all languages
    summaries = event.details.get("summaries", {})
    summary_zh = sanitize_html(summaries.get("zh", event.natural_language_summary or event.title))
    summary_en = sanitize_html(summaries.get("en", event.natural_language_summary or event.title))
    summary_ja = sanitize_html(summaries.get("ja", event.natural_language_summary or event.title))

    tool_tag = f'<span class="event-tool-tag">{tool}</span>' if tool else ""
    ts_span = f'<span class="event-ts">{ts}</span>' if ts != "—" else ""

    # L3: raw event JSON (lazy loaded)
    raw_json_escaped = sanitize_html(json.dumps(event.raw_event, ensure_ascii=False))

    # Status dot
    status_class = f"status-{event.status}" if event.status in ("success", "error", "warning") else "status-unknown"

    return f"""
<div class="event-item">
  <details>
    <summary class="event-summary">
      <span class="event-type-badge badge-{etype}" data-i18n="badge_{etype}"></span>
      <span class="event-summary-text" data-summary-zh="{summary_zh}" data-summary-en="{summary_en}" data-summary-ja="{summary_ja}">{summary_ja}</span>
      {tool_tag}
      {ts_span}
      <span class="status-dot {status_class}"></span>
    </summary>
    <div class="raw-details-wrapper">
      <button class="raw-toggle-btn raw-details-toggle" data-raw="{raw_json_escaped}" data-i18n-show="show_raw_json" data-i18n-hide="hide_raw_json">▶ <span data-i18n="show_raw_json"></span></button>
    </div>
  </details>
</div>"""


def _render_phase(phase: Any, phase_num: int) -> str:
    ptype = phase.phase_type
    start = _fmt_time(phase.start_time)
    end = _fmt_time(phase.end_time)
    time_range = f"{start} – {end}" if start != "—" else ""
    count = phase.event_count
    status_class = f"status-{phase.status}" if phase.status in ("success", "error", "warning") else "status-unknown"

    events_html = "\n".join(_render_event(e) for e in phase.events)

    return f"""
<div class="phase-block phase-{ptype}">
  <details>
    <summary class="phase-summary">
      <span class="phase-dot"></span>
      <span class="phase-name" data-i18n="phase_{ptype}"></span>
      <span class="phase-time">{time_range}</span>
      <span class="phase-count" data-count="{count}"></span>
      <span class="status-dot {status_class}"></span>
      <span class="phase-expand-icon">▶</span>
    </summary>
    <div class="events-list">
{events_html}
    </div>
  </details>
</div>"""


def _render_ts_quality(ts_quality: TimestampQuality) -> str:
    # Determine which pill to show
    if ts_quality.estimation_method == "exact_from_db":
        pill_class = "ts-exact-pill"
        pill_i18n = "ts_all_exact"
    elif ts_quality.missing_count > 0:
        pill_class = "ts-missing-pill"
        pill_i18n = "ts_has_missing"
    else:
        pill_class = "ts-estimated"
        pill_i18n = "ts_all_estimated"

    return f"""
<div class="ts-quality-bar">
  <span class="label" data-i18n="ts_quality_label"></span>
  <span class="ts-pill {pill_class}" data-i18n="{pill_i18n}"></span>
  <span class="label"><span data-i18n="ts_method"></span>：<strong>{sanitize_html(ts_quality.estimation_method)}</strong></span>
  <span class="label"><span data-i18n="ts_exact"></span>：<strong>{ts_quality.exact_count}</strong></span>
  <span class="label"><span data-i18n="ts_estimated"></span>：<strong>{ts_quality.estimated_count}</strong></span>
  <span class="label"><span data-i18n="ts_missing"></span>：<strong>{ts_quality.missing_count}</strong></span>
</div>"""


def render_html(
    meta: Dict[str, Any],
    phases: List[TimelinePhase],
    ts_quality: TimestampQuality,
    session_id: str,
) -> str:
    """Render a complete single-file HTML viewer with multi-language support."""

    session_start = meta.get("session_start", "—")
    last_updated = meta.get("last_updated", "—")
    model = sanitize_html(meta.get("model", "unknown"))
    platform = sanitize_html(meta.get("platform", "unknown"))
    msg_count = meta.get("message_count", 0)
    tools_count = meta.get("tools_count", 0)
    sys_prompt_len = meta.get("system_prompt_length", 0)

    total_events = sum(p.event_count for p in phases)
    total_phases = len(phases)
    error_count = sum(1 for p in phases if p.status == "error")

    # Stats cards - labels will be set by JS
    stats_html = f"""
<div class="stats-grid">
  <div class="stat-card"><div class="num">{msg_count}</div><div class="lbl" data-i18n="stat_raw_messages"></div></div>
  <div class="stat-card"><div class="num">{total_events}</div><div class="lbl" data-i18n="stat_parsed_events"></div></div>
  <div class="stat-card"><div class="num">{total_phases}</div><div class="lbl" data-i18n="stat_phases"></div></div>
  <div class="stat-card"><div class="num">{tools_count}</div><div class="lbl" data-i18n="stat_tools"></div></div>
  <div class="stat-card"><div class="num" style="color:{'var(--err)' if error_count else 'var(--accent2)'}">{error_count}</div><div class="lbl" data-i18n="stat_errors"></div></div>
  <div class="stat-card"><div class="num">{sys_prompt_len:,}</div><div class="lbl" data-i18n="stat_sys_prompt"></div></div>
</div>"""

    phases_html = "\n".join(_render_phase(p, i) for i, p in enumerate(phases))
    ts_html = _render_ts_quality(ts_quality)

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Embed i18n translations as JSON
    i18n_json = json.dumps(TRANSLATIONS, ensure_ascii=False)

    # JavaScript for language switching and all interactivity
    js_code = f"""
// ── i18n data ──
const I18N = {i18n_json};
const SESSION_ID = "{sanitize_html(session_id)}";
const GENERATED_AT = "{sanitize_html(generated_at)}";

let currentLang = localStorage.getItem('hermes_viewer_lang') || 'ja';

// ── Apply language ──
function applyLang(lang) {{
  currentLang = lang;
  localStorage.setItem('hermes_viewer_lang', lang);
  const t = I18N[lang] || I18N['ja'];

  // Update all data-i18n elements
  document.querySelectorAll('[data-i18n]').forEach(el => {{
    const key = el.getAttribute('data-i18n');
    if (t[key] !== undefined) {{
      el.textContent = t[key];
    }}
  }});

  // Update event summaries
  document.querySelectorAll('.event-summary-text').forEach(el => {{
    const summary = el.getAttribute('data-summary-' + lang);
    if (summary) {{
      el.textContent = summary;
      el.dataset.orig = summary;
    }}
  }});

  // Update phase counts
  document.querySelectorAll('.phase-count').forEach(el => {{
    const n = el.getAttribute('data-count');
    el.textContent = t['phase_count_format'].replace('{{n}}', n);
  }});

  // Update search placeholder
  const searchBox = document.getElementById('search-box');
  if (searchBox) searchBox.placeholder = t['search_placeholder'];

  // Update buttons
  document.getElementById('btn-expand-all').textContent = t['expand_all'];
  document.getElementById('btn-collapse-all').textContent = t['collapse_all'];

  // Update raw JSON toggle buttons text
  document.querySelectorAll('.raw-toggle-btn').forEach(btn => {{
    const block = btn.parentElement.querySelector('.raw-json-block');
    const isVisible = block && block.style.display !== 'none';
    const spanEl = btn.querySelector('[data-i18n]');
    if (spanEl) {{
      spanEl.textContent = isVisible ? t['hide_raw_json'] : t['show_raw_json'];
    }}
  }});

  // Update footer
  const footer = document.getElementById('footer-text');
  if (footer) {{
    footer.innerHTML = t['footer'].replace('{{ts}}', GENERATED_AT).replace('{{sid}}', SESSION_ID);
  }}

  // Update timeline info
  const total = document.querySelectorAll('.event-item').length;
  document.getElementById('timeline-info').textContent = t['timeline_total'].replace('{{n}}', total);

  // Update meta badges
  document.querySelectorAll('[data-meta-key]').forEach(el => {{
    const key = el.getAttribute('data-meta-key');
    if (t[key]) {{
      el.querySelector('.meta-label').textContent = t[key];
    }}
  }});

  // Update lang buttons active state
  document.querySelectorAll('.lang-btn').forEach(btn => {{
    btn.classList.toggle('active', btn.dataset.lang === lang);
  }});
}}

// ── JSON syntax highlighter ──
function highlightJson(json) {{
  return json
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(
      /("(\\\\u[a-zA-Z0-9]{{4}}|\\\\[^u]|[^\\\\\\"])*"(\\s*:)?|\\b(true|false|null)\\b|-?\\d+(?:\\.\\d*)?(?:[eE][+\\-]?\\d+)?)/g,
      function(match) {{
        let cls = 'jv-num';
        if (/^"/.test(match)) {{
          cls = /:$/.test(match) ? 'jk' : 'jv-str';
        }} else if (/true|false/.test(match)) {{
          cls = 'jv-bool';
        }} else if (/null/.test(match)) {{
          cls = 'jv-null';
        }}
        return '<span class="' + cls + '">' + match + '</span>';
      }}
    );
}}

// ── Lazy-render raw JSON blocks ──
function initRawToggle(btn) {{
  btn.addEventListener('click', function() {{
    const wrapper = btn.parentElement;
    let block = wrapper.querySelector('.raw-json-block');
    const t = I18N[currentLang] || I18N['ja'];
    if (!block) {{
      const raw = JSON.parse(btn.dataset.raw);
      const pretty = JSON.stringify(raw, null, 2);
      block = document.createElement('div');
      block.className = 'raw-json-block';
      block.innerHTML = highlightJson(pretty);
      wrapper.appendChild(block);
    }}
    const visible = block.style.display !== 'none';
    block.style.display = visible ? 'none' : 'block';
    const spanEl = btn.querySelector('[data-i18n]');
    if (spanEl) {{
      spanEl.setAttribute('data-i18n', visible ? 'show_raw_json' : 'hide_raw_json');
      spanEl.textContent = visible ? t['show_raw_json'] : t['hide_raw_json'];
    }}
    btn.firstChild.textContent = visible ? '▶ ' : '▼ ';
  }});
}}

// ── Expand / collapse all ──
function expandAll() {{
  document.querySelectorAll('details').forEach(d => d.open = true);
}}
function collapseAll() {{
  document.querySelectorAll('details').forEach(d => d.open = false);
}}

// ── Search / filter ──
let searchTimeout = null;
function onSearch(e) {{
  clearTimeout(searchTimeout);
  searchTimeout = setTimeout(() => doSearch(e.target.value.toLowerCase()), 120);
}}

function doSearch(q) {{
  const phases = document.querySelectorAll('.phase-block');
  const t = I18N[currentLang] || I18N['ja'];
  let matchedPhases = 0, totalEvents = 0, matchedEvents = 0;

  phases.forEach(phase => {{
    const items = phase.querySelectorAll('.event-item');
    let phaseMatch = 0;
    items.forEach(item => {{
      totalEvents++;
      const text = item.textContent.toLowerCase();
      const match = !q || text.includes(q);
      item.style.display = match ? '' : 'none';
      if (match) {{ phaseMatch++; matchedEvents++; }}
      // Highlight
      if (q && match) {{
        const summaryEl = item.querySelector('.event-summary-text');
        if (summaryEl) {{
          const orig = summaryEl.dataset.orig || summaryEl.textContent;
          summaryEl.dataset.orig = orig;
          const re = new RegExp(q.replace(/[.*+?^${{}}()|[\\]\\\\]/g, '\\\\$&'), 'gi');
          summaryEl.innerHTML = orig.replace(re, m => '<span class="hl">' + m + '</span>');
        }}
      }} else {{
        const summaryEl = item.querySelector('.event-summary-text');
        if (summaryEl && summaryEl.dataset.orig) {{
          summaryEl.textContent = summaryEl.dataset.orig;
        }}
      }}
    }});
    const hasVisible = phaseMatch > 0;
    phase.style.display = hasVisible ? '' : 'none';
    if (hasVisible) {{ matchedPhases++; if (q) phase.querySelector('details').open = true; }}
  }});

  document.getElementById('timeline-info').textContent =
    q ? t['timeline_search'].replace('{{q}}', q).replace('{{n}}', matchedEvents).replace('{{p}}', matchedPhases)
      : t['timeline_total'].replace('{{n}}', totalEvents);
}}

// ── Init ──
document.addEventListener('DOMContentLoaded', function() {{
  document.querySelectorAll('.raw-toggle-btn').forEach(initRawToggle);
  document.getElementById('btn-expand-all').addEventListener('click', expandAll);
  document.getElementById('btn-collapse-all').addEventListener('click', collapseAll);
  document.getElementById('search-box').addEventListener('input', onSearch);

  // Language switcher
  document.querySelectorAll('.lang-btn').forEach(btn => {{
    btn.addEventListener('click', () => applyLang(btn.dataset.lang));
  }});

  // Apply saved/default language
  applyLang(currentLang);
}});
"""

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Hermes Session Viewer — {sanitize_html(session_id)}</title>
<style>
{_CSS}
</style>
</head>
<body>

<div class="header">
  <div class="header-top">
    <h1>🔭 Hermes Session Viewer &nbsp;·&nbsp; <span>{sanitize_html(session_id)}</span></h1>
    <div class="lang-switcher">
      <button class="lang-btn" data-lang="ja">日本語</button>
      <button class="lang-btn" data-lang="zh">中文</button>
      <button class="lang-btn" data-lang="en">English</button>
    </div>
  </div>
  <div class="header-meta">
    <span class="meta-badge" data-meta-key="meta_model"><span class="meta-label" data-i18n="meta_model"></span>: <strong>{model}</strong></span>
    <span class="meta-badge" data-meta-key="meta_platform"><span class="meta-label" data-i18n="meta_platform"></span>: <strong>{platform}</strong></span>
    <span class="meta-badge" data-meta-key="meta_start"><span class="meta-label" data-i18n="meta_start"></span>: <strong>{sanitize_html(session_start)}</strong></span>
    <span class="meta-badge" data-meta-key="meta_end"><span class="meta-label" data-i18n="meta_end"></span>: <strong>{sanitize_html(last_updated)}</strong></span>
  </div>
</div>

<div class="container">

{ts_html}

{stats_html}

<div class="timeline-controls">
  <button class="btn" id="btn-expand-all"></button>
  <button class="btn" id="btn-collapse-all"></button>
  <input class="search-input" id="search-box" type="text" spellcheck="false">
  <span class="timeline-info" id="timeline-info"></span>
</div>

<div id="timeline">
{phases_html}
</div>

</div>

<div class="footer">
  <span id="footer-text"></span>
</div>

<script>
{js_code}
</script>
</body>
</html>"""
