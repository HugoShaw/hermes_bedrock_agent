from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="hermes-session-viewer",
        description="将 Hermes Agent 会话转换为交互式 HTML 可视化页面（支持从 state.db 或 JSON 文件加载）",
    )

    # Input source (mutually preferred: --session-id tries DB first, --session-file is JSON-only)
    parser.add_argument(
        "--session-id",
        default=None,
        metavar="ID",
        help="会话 ID — 优先从 ~/.hermes/state.db 查询，未找到则回退到 JSON 文件",
    )
    parser.add_argument(
        "--session-file",
        default=None,
        metavar="PATH",
        help="Hermes Agent 会话 JSON 文件路径（当 --session-id 未指定或 DB 中未找到时使用）",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        metavar="PATH",
        help="state.db 路径（默认: ~/.hermes/state.db）",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        metavar="DIR",
        help="输出目录（HTML 及 JSON 报告的存放位置）",
    )
    parser.add_argument(
        "--list-sessions",
        action="store_true",
        default=False,
        help="列出 state.db 中最近的会话（不生成可视化）",
    )
    parser.add_argument(
        "--list-limit",
        type=int,
        default=20,
        metavar="N",
        help="--list-sessions 时显示的最大条数（默认: 20）",
    )

    args = parser.parse_args()

    # Late imports to keep startup fast
    try:
        from hermes_session_viewer.loader import SessionLoadError, extract_session_metadata, load_session
        from hermes_session_viewer.db_loader import (
            DEFAULT_STATE_DB,
            find_session_in_db,
            list_sessions_in_db,
            load_session_from_db,
        )
        from hermes_session_viewer.timestamp import estimate_timestamps
        from hermes_session_viewer.parser import parse_messages
        from hermes_session_viewer.classifier import classify_events
        from hermes_session_viewer.aggregator import aggregate_phases
        from hermes_session_viewer.natural_language import generate_summaries
        from hermes_session_viewer.html_renderer import render_html
    except ImportError as e:
        print(f"导入模块失败: {e}", file=sys.stderr)
        sys.exit(1)

    # ── List sessions mode ──
    if args.list_sessions:
        db_path = args.db_path or str(DEFAULT_STATE_DB)
        sessions = list_sessions_in_db(db_path=db_path, limit=args.list_limit)
        if not sessions:
            print(f"未在 {db_path} 中找到任何会话。")
            sys.exit(0)
        print(f"{'ID':<28} {'Messages':>5} {'Tools':>5} {'Model':<40} Title")
        print("─" * 120)
        for s in sessions:
            sid = s["session_id"] or ""
            mc = s.get("message_count") or 0
            tc = s.get("tool_call_count") or 0
            model = (s.get("model") or "")[:40]
            title = (s.get("title") or "")[:50]
            print(f"{sid:<28} {mc:>5} {tc:>5} {model:<40} {title}")
        sys.exit(0)

    # ── Validate inputs ──
    if not args.session_id and not args.session_file:
        parser.error("请指定 --session-id 或 --session-file（至少提供一个）")

    # ── Load session data ──
    data = None
    source_label = ""
    db_path = args.db_path

    if args.session_id:
        # Try DB first
        print(f"尝试从 state.db 加载 session_id={args.session_id} ...")
        if find_session_in_db(args.session_id, db_path=db_path):
            try:
                data = load_session_from_db(args.session_id, db_path=db_path)
                source_label = "state.db"
                print(f"  ✓ 从数据库加载成功，消息数: {data['message_count']}")
            except SessionLoadError as e:
                print(f"  ✗ 数据库加载失败: {e}")
        else:
            print(f"  ✗ 数据库中未找到该会话")

    if data is None and args.session_file:
        # Fallback to JSON file
        print(f"回退到 JSON 文件: {args.session_file}")
        try:
            data = load_session(args.session_file)
            source_label = "JSON file"
            print(f"  ✓ JSON 文件加载成功")
        except SessionLoadError as e:
            print(f"错误: {e}", file=sys.stderr)
            sys.exit(1)

    if data is None:
        print("错误: 无法加载会话数据。请确认 session_id 正确或提供 --session-file。", file=sys.stderr)
        sys.exit(1)

    # ── Extract metadata ──
    meta = extract_session_metadata(data)
    session_id = args.session_id or meta["session_id"]
    # Enrich meta with DB-specific fields if available
    db_meta = data.get("_db_metadata", {})
    if db_meta:
        meta["title"] = db_meta.get("title") or meta.get("title", "")
        meta["tool_call_count"] = db_meta.get("tool_call_count", 0)
        meta["input_tokens"] = db_meta.get("input_tokens", 0)
        meta["output_tokens"] = db_meta.get("output_tokens", 0)
        meta["estimated_cost_usd"] = db_meta.get("estimated_cost_usd")
        meta["api_call_count"] = db_meta.get("api_call_count", 0)
    meta["data_source"] = source_label
    print(f"会话 ID: {session_id}  消息数: {meta['message_count']}  来源: {source_label}")

    # ── Timestamps ──
    messages = data.get("messages", [])
    timestamps, ts_quality = estimate_timestamps(
        messages,
        meta["session_start"],
        meta["last_updated"],
    )

    # Determine timestamp_type for parser
    ts_type = "exact" if ts_quality.estimation_method == "exact_from_db" else "estimated"

    # ── Parse ──
    print("解析消息...")
    events = parse_messages(messages, timestamps, session_id, timestamp_type=ts_type)
    print(f"  解析得到 {len(events)} 个事件（时间戳: {ts_quality.estimation_method}）")

    # ── Classify ──
    print("分类事件阶段...")
    events = classify_events(events)

    # ── Natural language summaries (zh/en/ja) ──
    print("生成多语言摘要 (zh/en/ja)...")
    events = generate_summaries(events)

    # ── Aggregate ──
    print("聚合时间轴阶段...")
    phases = aggregate_phases(events, session_id)
    print(f"  聚合为 {len(phases)} 个阶段")

    # ── Write outputs ──
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # parsed_events.json
    events_path = out_dir / "parsed_events.json"
    events_path.write_text(
        json.dumps([e.to_dict() for e in events], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  已写入: {events_path}")

    # timeline.json
    timeline_path = out_dir / "timeline.json"
    timeline_path.write_text(
        json.dumps([p.to_dict() for p in phases], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  已写入: {timeline_path}")

    # timestamp_quality.json
    ts_quality_path = out_dir / "timestamp_quality.json"
    ts_quality_path.write_text(
        json.dumps(ts_quality.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  已写入: {ts_quality_path}")

    # HTML viewer
    print("渲染 HTML 页面...")
    html_path = out_dir / f"session_{session_id}_viewer.html"
    html_content = render_html(meta, phases, ts_quality, session_id)
    html_path.write_text(html_content, encoding="utf-8")
    print(f"  已写入: {html_path}")

    print(f"\n完成！打开以下文件查看交互式时间轴：")
    print(f"  {html_path.resolve()}")
