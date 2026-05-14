from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from hermes_session_viewer.models import StandardEvent
from hermes_session_viewer.utils import safe_json_parse, truncate

# ---------------------------------------------------------------------------
# Tool description map per language
# ---------------------------------------------------------------------------
_TOOL_DESCRIPTIONS: Dict[str, Dict[str, str]] = {
    "zh": {
        "skill_view": "加载技能",
        "skill_manage": "管理技能",
        "memory": "写入记忆",
        "session_search": "搜索历史会话",
        "kanban_show": "查看任务看板",
        "kanban_complete": "完成看板任务",
        "kanban_block": "阻塞看板任务",
        "kanban_create": "创建看板任务",
        "kanban_comment": "评论看板任务",
        "kanban_heartbeat": "更新任务心跳",
        "execute_code": "执行代码",
        "bash": "执行 Shell 命令",
        "terminal": "执行终端命令",
        "python": "运行 Python 脚本",
        "shell": "执行 Shell 命令",
        "run_command": "运行命令",
        "read_file": "读取文件",
        "write_file": "写入文件",
        "file_read": "读取文件",
        "file_write": "写入文件",
        "save_file": "保存文件",
        "create_file": "创建文件",
        "web_search": "执行网络搜索",
        "web_fetch": "获取网页内容",
        "browser": "操作浏览器",
        "clarify": "向用户提问",
        "delegate_task": "委派子任务",
        "cronjob": "管理定时任务",
        "s3_list": "列出 S3 对象",
        "s3_get": "下载 S3 文件",
        "s3_put": "上传文件到 S3",
        "s3_read": "读取 S3 文件",
        "patch": "修改文件",
        "search_files": "搜索文件",
        "vision_analyze": "分析图片",
    },
    "en": {
        "skill_view": "loaded skill",
        "skill_manage": "managed skill",
        "memory": "wrote to memory",
        "session_search": "searched session history",
        "kanban_show": "viewed kanban task",
        "kanban_complete": "completed kanban task",
        "kanban_block": "blocked kanban task",
        "kanban_create": "created kanban task",
        "kanban_comment": "commented on kanban task",
        "kanban_heartbeat": "updated task heartbeat",
        "execute_code": "executed code",
        "bash": "ran shell command",
        "terminal": "ran terminal command",
        "python": "ran Python script",
        "shell": "ran shell command",
        "run_command": "ran command",
        "read_file": "read file",
        "write_file": "wrote file",
        "file_read": "read file",
        "file_write": "wrote file",
        "save_file": "saved file",
        "create_file": "created file",
        "web_search": "searched the web",
        "web_fetch": "fetched web page",
        "browser": "operated browser",
        "clarify": "asked user a question",
        "delegate_task": "delegated subtask",
        "cronjob": "managed cron job",
        "s3_list": "listed S3 objects",
        "s3_get": "downloaded S3 file",
        "s3_put": "uploaded to S3",
        "s3_read": "read S3 file",
        "patch": "patched file",
        "search_files": "searched files",
        "vision_analyze": "analyzed image",
    },
    "ja": {
        "skill_view": "スキルを読み込み",
        "skill_manage": "スキルを管理",
        "memory": "メモリに書き込み",
        "session_search": "セッション履歴を検索",
        "kanban_show": "カンバンタスクを確認",
        "kanban_complete": "カンバンタスクを完了",
        "kanban_block": "カンバンタスクをブロック",
        "kanban_create": "カンバンタスクを作成",
        "kanban_comment": "カンバンタスクにコメント",
        "kanban_heartbeat": "タスクハートビートを更新",
        "execute_code": "コードを実行",
        "bash": "シェルコマンドを実行",
        "terminal": "ターミナルコマンドを実行",
        "python": "Pythonスクリプトを実行",
        "shell": "シェルコマンドを実行",
        "run_command": "コマンドを実行",
        "read_file": "ファイルを読み込み",
        "write_file": "ファイルを書き込み",
        "file_read": "ファイルを読み込み",
        "file_write": "ファイルを書き込み",
        "save_file": "ファイルを保存",
        "create_file": "ファイルを作成",
        "web_search": "ウェブ検索を実行",
        "web_fetch": "ウェブページを取得",
        "browser": "ブラウザを操作",
        "clarify": "ユーザーに質問",
        "delegate_task": "サブタスクを委任",
        "cronjob": "cronジョブを管理",
        "s3_list": "S3オブジェクトを一覧",
        "s3_get": "S3ファイルをダウンロード",
        "s3_put": "S3にアップロード",
        "s3_read": "S3ファイルを読み込み",
        "patch": "ファイルを修正",
        "search_files": "ファイルを検索",
        "vision_analyze": "画像を分析",
    },
}


def _ts_label(event: StandardEvent) -> str:
    if event.timestamp:
        return event.timestamp.strftime("%Y-%m-%d %H:%M:%S")
    return ""


# ---------------------------------------------------------------------------
# Per-language summary generators
# ---------------------------------------------------------------------------

def _gen_tool_call_zh(event: StandardEvent) -> str:
    tool = event.tool_name or "未知工具"
    verb = _TOOL_DESCRIPTIONS["zh"].get(tool, f"调用 {tool} 工具")
    ts = _ts_label(event)
    args = event.details.get("arguments", {})

    if tool == "skill_view":
        name = args.get("name", "") if isinstance(args, dict) else ""
        return f"[{ts}] Agent {verb}，加载 {name} 技能以了解相关工作流程。"
    if tool == "skill_manage":
        action = args.get("action", "") if isinstance(args, dict) else ""
        name = args.get("name", "") if isinstance(args, dict) else ""
        return f"[{ts}] Agent {verb}（操作: {action}），技能名: {name}。"
    if tool == "memory":
        action = args.get("action", "write") if isinstance(args, dict) else "write"
        return f"[{ts}] Agent {verb}，持久化记忆（操作: {action}）。"
    if tool == "kanban_show":
        return f"[{ts}] Agent {verb}，获取当前任务详情和上下文。"
    if tool == "kanban_complete":
        summary = args.get("summary", "") if isinstance(args, dict) else ""
        return f"[{ts}] Agent 完成看板任务，汇报结果：{truncate(summary, 80)}"
    if tool == "kanban_block":
        reason = args.get("reason", "") if isinstance(args, dict) else ""
        return f"[{ts}] Agent 阻塞任务，原因：{truncate(reason, 80)}"
    if tool in ("execute_code", "bash", "terminal", "python", "shell"):
        code = args.get("code") or args.get("command") or args.get("cmd") or ""
        if isinstance(code, str):
            first_line = code.strip().split("\n")[0]
            return f"[{ts}] Agent {verb}：{truncate(first_line, 100)}"
        return f"[{ts}] Agent {verb}。"
    if tool in ("read_file", "file_read"):
        path = args.get("path") or args.get("file") or ""
        return f"[{ts}] Agent 读取文件：{path}"
    if tool in ("write_file", "file_write", "save_file", "create_file"):
        path = args.get("path") or args.get("file") or ""
        return f"[{ts}] Agent 写入文件：{path}"
    if tool == "web_search":
        query = args.get("query", "") if isinstance(args, dict) else ""
        return f"[{ts}] Agent 搜索网络：{truncate(query, 80)}"
    if tool == "clarify":
        question = args.get("question", "") if isinstance(args, dict) else ""
        return f"[{ts}] Agent 向用户提问：{truncate(question, 80)}"
    if tool == "delegate_task":
        goal = args.get("goal", "") if isinstance(args, dict) else ""
        return f"[{ts}] Agent 委派子任务：{truncate(goal, 80)}"
    if tool == "session_search":
        query = args.get("query", "") if isinstance(args, dict) else ""
        return f"[{ts}] Agent 搜索历史会话，查询：{truncate(query, 80)}"
    args_preview = truncate(json.dumps(args, ensure_ascii=False), 80) if args else ""
    return f"[{ts}] Agent {verb}，参数: {args_preview}"


def _gen_tool_call_en(event: StandardEvent) -> str:
    tool = event.tool_name or "unknown_tool"
    verb = _TOOL_DESCRIPTIONS["en"].get(tool, f"called {tool}")
    ts = _ts_label(event)
    args = event.details.get("arguments", {})

    if tool == "skill_view":
        name = args.get("name", "") if isinstance(args, dict) else ""
        return f"[{ts}] Agent {verb} '{name}' to understand the relevant workflow."
    if tool == "skill_manage":
        action = args.get("action", "") if isinstance(args, dict) else ""
        name = args.get("name", "") if isinstance(args, dict) else ""
        return f"[{ts}] Agent {verb} (action: {action}), skill: {name}."
    if tool == "memory":
        action = args.get("action", "write") if isinstance(args, dict) else "write"
        return f"[{ts}] Agent {verb} to persist information (action: {action})."
    if tool == "kanban_show":
        return f"[{ts}] Agent {verb} to get current task details and context."
    if tool == "kanban_complete":
        summary = args.get("summary", "") if isinstance(args, dict) else ""
        return f"[{ts}] Agent completed task with summary: {truncate(summary, 80)}"
    if tool == "kanban_block":
        reason = args.get("reason", "") if isinstance(args, dict) else ""
        return f"[{ts}] Agent blocked task, reason: {truncate(reason, 80)}"
    if tool in ("execute_code", "bash", "terminal", "python", "shell"):
        code = args.get("code") or args.get("command") or args.get("cmd") or ""
        if isinstance(code, str):
            first_line = code.strip().split("\n")[0]
            return f"[{ts}] Agent {verb}: {truncate(first_line, 100)}"
        return f"[{ts}] Agent {verb}."
    if tool in ("read_file", "file_read"):
        path = args.get("path") or args.get("file") or ""
        return f"[{ts}] Agent read file: {path}"
    if tool in ("write_file", "file_write", "save_file", "create_file"):
        path = args.get("path") or args.get("file") or ""
        return f"[{ts}] Agent wrote file: {path}"
    if tool == "web_search":
        query = args.get("query", "") if isinstance(args, dict) else ""
        return f"[{ts}] Agent searched the web: {truncate(query, 80)}"
    if tool == "clarify":
        question = args.get("question", "") if isinstance(args, dict) else ""
        return f"[{ts}] Agent asked user: {truncate(question, 80)}"
    if tool == "delegate_task":
        goal = args.get("goal", "") if isinstance(args, dict) else ""
        return f"[{ts}] Agent delegated subtask: {truncate(goal, 80)}"
    if tool == "session_search":
        query = args.get("query", "") if isinstance(args, dict) else ""
        return f"[{ts}] Agent searched session history: {truncate(query, 80)}"
    args_preview = truncate(json.dumps(args, ensure_ascii=False), 80) if args else ""
    return f"[{ts}] Agent {verb}, args: {args_preview}"


def _gen_tool_call_ja(event: StandardEvent) -> str:
    tool = event.tool_name or "不明ツール"
    verb = _TOOL_DESCRIPTIONS["ja"].get(tool, f"{tool} を呼び出し")
    ts = _ts_label(event)
    args = event.details.get("arguments", {})

    if tool == "skill_view":
        name = args.get("name", "") if isinstance(args, dict) else ""
        return f"[{ts}] Agent がスキル '{name}' を読み込み、関連ワークフローを確認しました。"
    if tool == "skill_manage":
        action = args.get("action", "") if isinstance(args, dict) else ""
        name = args.get("name", "") if isinstance(args, dict) else ""
        return f"[{ts}] Agent がスキルを管理（操作: {action}）、スキル名: {name}。"
    if tool == "memory":
        action = args.get("action", "write") if isinstance(args, dict) else "write"
        return f"[{ts}] Agent がメモリに書き込み、情報を永続化（操作: {action}）。"
    if tool == "kanban_show":
        return f"[{ts}] Agent がカンバンタスクを確認し、コンテキストを取得しました。"
    if tool == "kanban_complete":
        summary = args.get("summary", "") if isinstance(args, dict) else ""
        return f"[{ts}] Agent がタスクを完了、結果: {truncate(summary, 80)}"
    if tool == "kanban_block":
        reason = args.get("reason", "") if isinstance(args, dict) else ""
        return f"[{ts}] Agent がタスクをブロック、理由: {truncate(reason, 80)}"
    if tool in ("execute_code", "bash", "terminal", "python", "shell"):
        code = args.get("code") or args.get("command") or args.get("cmd") or ""
        if isinstance(code, str):
            first_line = code.strip().split("\n")[0]
            return f"[{ts}] Agent が{verb}：{truncate(first_line, 100)}"
        return f"[{ts}] Agent が{verb}。"
    if tool in ("read_file", "file_read"):
        path = args.get("path") or args.get("file") or ""
        return f"[{ts}] Agent がファイルを読み込み：{path}"
    if tool in ("write_file", "file_write", "save_file", "create_file"):
        path = args.get("path") or args.get("file") or ""
        return f"[{ts}] Agent がファイルを書き込み：{path}"
    if tool == "web_search":
        query = args.get("query", "") if isinstance(args, dict) else ""
        return f"[{ts}] Agent がウェブ検索を実行：{truncate(query, 80)}"
    if tool == "clarify":
        question = args.get("question", "") if isinstance(args, dict) else ""
        return f"[{ts}] Agent がユーザーに質問：{truncate(question, 80)}"
    if tool == "delegate_task":
        goal = args.get("goal", "") if isinstance(args, dict) else ""
        return f"[{ts}] Agent がサブタスクを委任：{truncate(goal, 80)}"
    if tool == "session_search":
        query = args.get("query", "") if isinstance(args, dict) else ""
        return f"[{ts}] Agent がセッション履歴を検索：{truncate(query, 80)}"
    args_preview = truncate(json.dumps(args, ensure_ascii=False), 80) if args else ""
    return f"[{ts}] Agent が{verb}、引数: {args_preview}"


def _gen_tool_result_zh(event: StandardEvent) -> str:
    tool = event.tool_name or "未知工具"
    ts = _ts_label(event)
    preview = event.details.get("content_preview", "")
    status = "成功" if event.status == "success" else "失败/错误"
    if tool == "skill_view":
        m = re.search(r'\((\d+[\d,]*)\s*chars?\)', preview)
        size = f"（{m.group(1)} 字符）" if m else ""
        name_m = re.match(r'name=(\S+)', preview.strip())
        name = name_m.group(1) if name_m else ""
        return f"[{ts}] 技能 {name} 加载完成{size}，内容已注入上下文。"
    if tool in ("execute_code", "bash", "terminal", "python"):
        first = truncate(preview, 120)
        return f"[{ts}] 代码执行{status}，输出：{first}"
    if tool in ("read_file", "file_read"):
        return f"[{ts}] 文件读取{status}，内容预览：{truncate(preview, 100)}"
    if tool in ("write_file", "file_write", "save_file"):
        return f"[{ts}] 文件写入{status}。"
    if tool == "kanban_show":
        return f"[{ts}] 任务信息加载完成，Agent 已获取工作上下文。"
    if tool == "kanban_complete":
        return f"[{ts}] 任务完成确认{status}。"
    if tool == "memory":
        return f"[{ts}] 记忆操作{status}。"
    first = truncate(preview, 120)
    return f"[{ts}] {tool} 工具返回结果（{status}）：{first}"


def _gen_tool_result_en(event: StandardEvent) -> str:
    tool = event.tool_name or "unknown_tool"
    ts = _ts_label(event)
    preview = event.details.get("content_preview", "")
    status = "success" if event.status == "success" else "failed"
    if tool == "skill_view":
        m = re.search(r'\((\d+[\d,]*)\s*chars?\)', preview)
        size = f" ({m.group(1)} chars)" if m else ""
        name_m = re.match(r'name=(\S+)', preview.strip())
        name = name_m.group(1) if name_m else ""
        return f"[{ts}] Skill '{name}' loaded{size}, content injected into context."
    if tool in ("execute_code", "bash", "terminal", "python"):
        first = truncate(preview, 120)
        return f"[{ts}] Code execution {status}, output: {first}"
    if tool in ("read_file", "file_read"):
        return f"[{ts}] File read {status}, preview: {truncate(preview, 100)}"
    if tool in ("write_file", "file_write", "save_file"):
        return f"[{ts}] File write {status}."
    if tool == "kanban_show":
        return f"[{ts}] Task info loaded, Agent obtained working context."
    if tool == "kanban_complete":
        return f"[{ts}] Task completion confirmed ({status})."
    if tool == "memory":
        return f"[{ts}] Memory operation {status}."
    first = truncate(preview, 120)
    return f"[{ts}] {tool} returned result ({status}): {first}"


def _gen_tool_result_ja(event: StandardEvent) -> str:
    tool = event.tool_name or "不明ツール"
    ts = _ts_label(event)
    preview = event.details.get("content_preview", "")
    status = "成功" if event.status == "success" else "失敗"
    if tool == "skill_view":
        m = re.search(r'\((\d+[\d,]*)\s*chars?\)', preview)
        size = f"（{m.group(1)} 文字）" if m else ""
        name_m = re.match(r'name=(\S+)', preview.strip())
        name = name_m.group(1) if name_m else ""
        return f"[{ts}] スキル '{name}' の読み込み完了{size}、コンテキストに注入済み。"
    if tool in ("execute_code", "bash", "terminal", "python"):
        first = truncate(preview, 120)
        return f"[{ts}] コード実行{status}、出力：{first}"
    if tool in ("read_file", "file_read"):
        return f"[{ts}] ファイル読み込み{status}、プレビュー：{truncate(preview, 100)}"
    if tool in ("write_file", "file_write", "save_file"):
        return f"[{ts}] ファイル書き込み{status}。"
    if tool == "kanban_show":
        return f"[{ts}] タスク情報の読み込み完了、Agent がコンテキストを取得。"
    if tool == "kanban_complete":
        return f"[{ts}] タスク完了確認（{status}）。"
    if tool == "memory":
        return f"[{ts}] メモリ操作{status}。"
    first = truncate(preview, 120)
    return f"[{ts}] {tool} が結果を返却（{status}）：{first}"


def _gen_user_request(event: StandardEvent, lang: str) -> str:
    ts = _ts_label(event)
    preview = event.details.get("content_preview", "")
    first_line = preview.strip().split("\n")[0]
    if lang == "zh":
        return f"[{ts}] 用户发送请求：{truncate(first_line, 120)}"
    elif lang == "ja":
        return f"[{ts}] ユーザーがリクエストを送信：{truncate(first_line, 120)}"
    else:
        return f"[{ts}] User sent request: {truncate(first_line, 120)}"


def _gen_agent_plan(event: StandardEvent, lang: str) -> str:
    ts = _ts_label(event)
    preview = event.details.get("content_preview", "")
    first_line = preview.strip().split("\n")[0]
    if lang == "zh":
        return f"[{ts}] Agent 思考/规划：{truncate(first_line, 120)}"
    elif lang == "ja":
        return f"[{ts}] Agent が思考/計画中：{truncate(first_line, 120)}"
    else:
        return f"[{ts}] Agent thinking/planning: {truncate(first_line, 120)}"


def _gen_agent_message(event: StandardEvent, lang: str) -> str:
    ts = _ts_label(event)
    preview = event.details.get("content_preview", "")
    if lang == "zh":
        return f"[{ts}] 系统消息（上下文压缩）：{truncate(preview, 80)}"
    elif lang == "ja":
        return f"[{ts}] システムメッセージ（コンテキスト圧縮）：{truncate(preview, 80)}"
    else:
        return f"[{ts}] System message (context compaction): {truncate(preview, 80)}"


def _gen_final_answer(event: StandardEvent, lang: str) -> str:
    ts = _ts_label(event)
    preview = event.details.get("content_preview", "")
    first = preview.strip().split("\n")[0]
    if lang == "zh":
        return f"[{ts}] Agent 返回最终结果：{truncate(first, 120)}"
    elif lang == "ja":
        return f"[{ts}] Agent が最終結果を返却：{truncate(first, 120)}"
    else:
        return f"[{ts}] Agent returned final answer: {truncate(first, 120)}"


def _gen_error(event: StandardEvent, lang: str) -> str:
    ts = _ts_label(event)
    preview = event.details.get("content_preview", "") or event.details.get("error", "")
    if lang == "zh":
        return f"[{ts}] 发生错误：{truncate(preview, 120)}"
    elif lang == "ja":
        return f"[{ts}] エラー発生：{truncate(preview, 120)}"
    else:
        return f"[{ts}] Error occurred: {truncate(preview, 120)}"


def _gen_command_exec(event: StandardEvent, lang: str) -> str:
    ts = _ts_label(event)
    cmd = event.command or event.details.get("content_preview", "")
    if lang == "zh":
        return f"[{ts}] Agent 执行命令：{truncate(str(cmd), 120)}"
    elif lang == "ja":
        return f"[{ts}] Agent がコマンドを実行：{truncate(str(cmd), 120)}"
    else:
        return f"[{ts}] Agent executed command: {truncate(str(cmd), 120)}"


def _gen_file_read(event: StandardEvent, lang: str) -> str:
    ts = _ts_label(event)
    files = event.input_files
    if files:
        paths = ', '.join(files[:3])
        if lang == "zh":
            return f"[{ts}] Agent 读取文件：{paths}"
        elif lang == "ja":
            return f"[{ts}] Agent がファイルを読み込み：{paths}"
        else:
            return f"[{ts}] Agent read file: {paths}"
    args = event.details.get("arguments", {})
    path = args.get("path") or args.get("file") or "" if isinstance(args, dict) else ""
    if lang == "zh":
        return f"[{ts}] Agent 读取文件：{path or '（路径未知）'}"
    elif lang == "ja":
        return f"[{ts}] Agent がファイルを読み込み：{path or '（パス不明）'}"
    else:
        return f"[{ts}] Agent read file: {path or '(unknown path)'}"


def _gen_file_write(event: StandardEvent, lang: str) -> str:
    ts = _ts_label(event)
    files = event.output_files
    if files:
        paths = ', '.join(files[:3])
        if lang == "zh":
            return f"[{ts}] Agent 写入文件：{paths}"
        elif lang == "ja":
            return f"[{ts}] Agent がファイルを書き込み：{paths}"
        else:
            return f"[{ts}] Agent wrote file: {paths}"
    if lang == "zh":
        return f"[{ts}] Agent 写入文件。"
    elif lang == "ja":
        return f"[{ts}] Agent がファイルを書き込み。"
    else:
        return f"[{ts}] Agent wrote file."


def _gen_unknown(event: StandardEvent, lang: str) -> str:
    ts = _ts_label(event)
    preview = event.details.get("content_preview", "")
    if lang == "zh":
        return f"[{ts}] {event.title}：{truncate(preview, 100)}"
    elif lang == "ja":
        return f"[{ts}] {event.title}：{truncate(preview, 100)}"
    else:
        return f"[{ts}] {event.title}: {truncate(preview, 100)}"


def _generate_summary_for_lang(event: StandardEvent, lang: str) -> str:
    """Generate natural language summary for a single event in a specific language."""
    etype = event.event_type

    if etype == "tool_call" or etype == "command_exec" or etype == "file_read" or etype == "file_write":
        # tool_call with sub-types
        if etype == "command_exec":
            return _gen_command_exec(event, lang)
        elif etype == "file_read":
            return _gen_file_read(event, lang)
        elif etype == "file_write":
            return _gen_file_write(event, lang)
        else:
            # generic tool_call
            if lang == "zh":
                return _gen_tool_call_zh(event)
            elif lang == "ja":
                return _gen_tool_call_ja(event)
            else:
                return _gen_tool_call_en(event)

    if etype == "tool_result":
        if lang == "zh":
            return _gen_tool_result_zh(event)
        elif lang == "ja":
            return _gen_tool_result_ja(event)
        else:
            return _gen_tool_result_en(event)

    if etype == "user_request":
        return _gen_user_request(event, lang)
    if etype == "agent_plan":
        return _gen_agent_plan(event, lang)
    if etype == "agent_message":
        return _gen_agent_message(event, lang)
    if etype == "final_answer":
        return _gen_final_answer(event, lang)
    if etype in ("error", "retry"):
        return _gen_error(event, lang)

    return _gen_unknown(event, lang)


def generate_summaries(events: List[StandardEvent]) -> List[StandardEvent]:
    """
    Fill natural_language_summary (default=ja) and 
    details['summaries'] = {'zh': ..., 'en': ..., 'ja': ...} for each event.
    """
    for event in events:
        try:
            summaries = {}
            for lang in ("zh", "en", "ja"):
                summaries[lang] = _generate_summary_for_lang(event, lang)
            event.details["summaries"] = summaries
            # Default display summary is Japanese
            event.natural_language_summary = summaries["ja"]
        except Exception as exc:
            event.natural_language_summary = f"{event.title}（summary generation failed: {exc}）"
            event.details["summaries"] = {
                "zh": event.natural_language_summary,
                "en": event.natural_language_summary,
                "ja": event.natural_language_summary,
            }
    return events
