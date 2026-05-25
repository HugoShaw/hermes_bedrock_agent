"""
V2 Query Router — Heuristic intent classification and retrieval plan generation.

Classifies user queries into intent types and produces a RetrievalPlan
that specifies which retrieval paths to execute.

No LLM required — uses keyword/pattern matching for intent detection.
"""

from __future__ import annotations

import re
from typing import Any

from hermes_bedrock_agent.v2.schemas.retrieval_schema import (
    QueryIntent,
    RetrievalPlan,
)


# ============================================================
# Language detection patterns
# ============================================================

_CJK_PATTERN = re.compile(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]')
_JAPANESE_SPECIFIC = re.compile(r'[\u3040-\u309f\u30a0-\u30ff]')  # Hiragana/Katakana
_CHINESE_SPECIFIC = re.compile(r'[\u4e00-\u9fff]')


def detect_language(text: str) -> str:
    """Detect dominant language: ja, zh, en, mixed."""
    has_jp = bool(_JAPANESE_SPECIFIC.search(text))
    has_cn = bool(_CHINESE_SPECIFIC.search(text))
    has_en = bool(re.search(r'[a-zA-Z]{3,}', text))

    if has_jp and has_cn:
        return 'mixed'
    if has_jp:
        return 'ja'
    if has_cn:
        return 'zh'
    if has_en:
        return 'en'
    return 'mixed'


# ============================================================
# Intent detection keyword sets
# ============================================================

# Definition / explanation queries
DEFINITION_KEYWORDS_JA = [
    'とは', 'って何', 'とは何', '定義', '意味', '概要', '説明して',
    'ですか', 'について教えて',
]
DEFINITION_KEYWORDS_ZH = [
    '是什么', '定义', '含义', '概念', '解释', '什么意思', '是指',
]
DEFINITION_KEYWORDS_EN = [
    'what is', 'define', 'definition', 'meaning of', 'explain what',
    'what does', 'describe',
]

# Business process queries
PROCESS_KEYWORDS_JA = [
    '業務プロセス', '業務フロー', '業務流れ', 'フロー', 'プロセス',
    'ワークフロー', '手順', '流れ', '承認', '申請',
    '仕訳', '支払', '付款', '対帳',
]
PROCESS_KEYWORDS_ZH = [
    '业务流程', '工作流', '流程', '步骤', '审批', '申请',
    '付款申请', '对账', '仕訳',
]
PROCESS_KEYWORDS_EN = [
    'business process', 'workflow', 'process flow', 'approval',
    'procedure', 'steps',
]

# Relationship / dependency queries
RELATIONSHIP_KEYWORDS_JA = [
    '関連', '関係', '依存', 'つながり', '結びつき',
    'に関連する', 'と関係する',
]
RELATIONSHIP_KEYWORDS_ZH = [
    '关系', '关联', '依赖', '相关', '之间', '联系',
]
RELATIONSHIP_KEYWORDS_EN = [
    'related to', 'relationship', 'connected', 'depends on',
    'dependency', 'associated',
]

# API / code / database queries
TECH_KEYWORDS_JA = [
    'API', 'テーブル', 'カラム', 'SQL', 'クラス', 'メソッド',
    'サービス', 'ファイル', 'コード', 'DB', 'データベース',
    'モジュール', 'コンフィグ', 'ジョブ',
]
TECH_KEYWORDS_ZH = [
    'API', '表', '列', '字段', 'SQL', '类', '方法',
    '服务', '文件', '代码', '数据库', '模块', '配置',
]
TECH_KEYWORDS_EN = [
    'api', 'table', 'column', 'sql', 'class', 'method',
    'service', 'file', 'code', 'database', 'module', 'config',
    'endpoint', 'schema',
]

# Impact analysis queries
IMPACT_KEYWORDS_JA = [
    '影響', '外移', '移行', 'インパクト', '変更',
    '影響範囲', '影響分析',
]
IMPACT_KEYWORDS_ZH = [
    '影响', '外移', '迁移', '改动', '变更',
    '影响范围', '影响分析', '可能影响',
]
IMPACT_KEYWORDS_EN = [
    'impact', 'affect', 'migrate', 'change', 'move to',
    'impact analysis', 'what happens if',
]

# Troubleshooting queries
TROUBLESHOOT_KEYWORDS_JA = [
    'エラー', '障害', '問題', 'トラブル', 'バグ', '修正',
    '解決', 'デバッグ',
]
TROUBLESHOOT_KEYWORDS_ZH = [
    '错误', '故障', '问题', '排错', '修复', '调试', 'bug',
]
TROUBLESHOOT_KEYWORDS_EN = [
    'error', 'bug', 'fix', 'debug', 'troubleshoot', 'issue',
    'problem', 'failure',
]

# Workflow generation queries
WORKFLOW_KEYWORDS_JA = [
    '生成', '作成', 'ワークフロー作成', '設計',
]
WORKFLOW_KEYWORDS_ZH = [
    '生成', '创建', '设计', '自动化',
]
WORKFLOW_KEYWORDS_EN = [
    'generate', 'create workflow', 'design', 'automate',
]

# Graph structure / overview queries
OVERVIEW_KEYWORDS_JA = [
    '一覧', 'ノード', '主要', '含まれ', '全体',
]
OVERVIEW_KEYWORDS_ZH = [
    '包含哪些', '主要节点', '有哪些', '一览', '整体',
    '分别包含', '节点',
]
OVERVIEW_KEYWORDS_EN = [
    'contains', 'main nodes', 'overview', 'list all', 'what are',
]

# Evidence gap queries
EVIDENCE_GAP_KEYWORDS_JA = [
    'evidence', '根拠がない', '補充', '文档不足',
    'evidenceがない', '証拠がない', '根拠不足',
    'evidence coverage', '補足資料が必要',
]
EVIDENCE_GAP_KEYWORDS_ZH = [
    '没有evidence', '补充文档', '缺少', '人工补充',
    '没有证据', '缺少证据', '哪些节点没有',
    '哪些边没有', '需要补充文档', 'evidence覆盖率',
    '证据覆盖率', '缺少evidence',
]
EVIDENCE_GAP_KEYWORDS_EN = [
    'no evidence', 'missing evidence', 'gaps', 'supplement',
    'nodes without evidence', 'edges without evidence',
    'evidence coverage', 'unsupported nodes', 'unsupported edges',
    'need more documentation',
]


def _keyword_score(text: str, keywords: list[str]) -> float:
    """Score how many keywords match in text (case-insensitive)."""
    text_lower = text.lower()
    matched = sum(1 for kw in keywords if kw.lower() in text_lower)
    return matched / max(len(keywords), 1)


class QueryRouter:
    """Heuristic query router for V2 retrieval pipeline."""

    def classify_intent(self, query: str) -> QueryIntent:
        """Classify query intent using keyword matching."""
        lang = detect_language(query)

        scores: dict[str, float] = {}

        # Definition
        scores['definition'] = max(
            _keyword_score(query, DEFINITION_KEYWORDS_JA),
            _keyword_score(query, DEFINITION_KEYWORDS_ZH),
            _keyword_score(query, DEFINITION_KEYWORDS_EN),
        )

        # Business process
        scores['business_process'] = max(
            _keyword_score(query, PROCESS_KEYWORDS_JA),
            _keyword_score(query, PROCESS_KEYWORDS_ZH),
            _keyword_score(query, PROCESS_KEYWORDS_EN),
        )

        # Relationship
        scores['relationship'] = max(
            _keyword_score(query, RELATIONSHIP_KEYWORDS_JA),
            _keyword_score(query, RELATIONSHIP_KEYWORDS_ZH),
            _keyword_score(query, RELATIONSHIP_KEYWORDS_EN),
        )

        # API/code/DB
        scores['api_code_db'] = max(
            _keyword_score(query, TECH_KEYWORDS_JA),
            _keyword_score(query, TECH_KEYWORDS_ZH),
            _keyword_score(query, TECH_KEYWORDS_EN),
        )

        # Impact analysis
        scores['impact_analysis'] = max(
            _keyword_score(query, IMPACT_KEYWORDS_JA),
            _keyword_score(query, IMPACT_KEYWORDS_ZH),
            _keyword_score(query, IMPACT_KEYWORDS_EN),
        )

        # Troubleshooting
        scores['troubleshooting'] = max(
            _keyword_score(query, TROUBLESHOOT_KEYWORDS_JA),
            _keyword_score(query, TROUBLESHOOT_KEYWORDS_ZH),
            _keyword_score(query, TROUBLESHOOT_KEYWORDS_EN),
        )

        # Workflow generation
        scores['workflow_generation'] = max(
            _keyword_score(query, WORKFLOW_KEYWORDS_JA),
            _keyword_score(query, WORKFLOW_KEYWORDS_ZH),
            _keyword_score(query, WORKFLOW_KEYWORDS_EN),
        )

        # Check for overview/structure queries
        overview_score = max(
            _keyword_score(query, OVERVIEW_KEYWORDS_JA),
            _keyword_score(query, OVERVIEW_KEYWORDS_ZH),
            _keyword_score(query, OVERVIEW_KEYWORDS_EN),
        )

        # Check for evidence gap queries
        evidence_gap_score = max(
            _keyword_score(query, EVIDENCE_GAP_KEYWORDS_JA),
            _keyword_score(query, EVIDENCE_GAP_KEYWORDS_ZH),
            _keyword_score(query, EVIDENCE_GAP_KEYWORDS_EN),
        )

        # Boost hybrid for combined relationship + tech terms
        if scores['relationship'] > 0 and scores['api_code_db'] > 0:
            scores['relationship'] *= 1.5

        # Boost impact_analysis for migration + function keywords
        if scores['impact_analysis'] > 0 and (scores['api_code_db'] > 0 or scores['business_process'] > 0):
            scores['impact_analysis'] *= 1.5

        # Overview/evidence gap are special
        if evidence_gap_score > 0.1:
            # Classify as evidence_coverage intent (P0 fix: must not fall into relationship)
            return QueryIntent(
                query=query,
                intent='evidence_coverage',
                language=lang,
                confidence=min(evidence_gap_score * 3.0, 1.0),
                metadata={
                    'scores': {k: round(v, 4) for k, v in sorted(scores.items(), key=lambda x: -x[1])},
                    'overview_score': round(overview_score, 4),
                    'evidence_gap_score': round(evidence_gap_score, 4),
                },
            )

        if overview_score > 0.1 and scores['business_process'] < overview_score:
            # Treat graph overview as hybrid
            scores['relationship'] = max(scores['relationship'], overview_score)

        # Pick the highest scoring intent
        best_intent = max(scores, key=lambda k: scores[k])
        best_score = scores[best_intent]

        # If all scores are 0, fall back to unknown
        if best_score == 0:
            best_intent = 'unknown'
            best_score = 0.0

        # Normalize confidence
        confidence = min(best_score * 2.0, 1.0)  # Scale up since keyword match is sparse

        return QueryIntent(
            query=query,
            intent=best_intent,
            language=lang,
            confidence=confidence,
            metadata={
                'scores': {k: round(v, 4) for k, v in sorted(scores.items(), key=lambda x: -x[1])},
                'overview_score': round(overview_score, 4),
                'evidence_gap_score': round(evidence_gap_score, 4),
            },
        )

    def build_plan(self, intent: QueryIntent) -> RetrievalPlan:
        """Build retrieval plan from classified intent."""
        query = intent.query
        intent_type = intent.intent

        if intent_type == 'definition':
            return RetrievalPlan(
                query=query,
                intent=intent_type,
                primary_path='vector_evidence',
                secondary_paths=['business_graph'],
                need_business_graph=True,
                need_implementation_graph=False,
                need_vector_evidence=True,
                need_graph_expansion=False,
                metadata={'reason': 'Definition query → Vector Evidence first, Business Graph for context'},
            )

        elif intent_type == 'business_process':
            return RetrievalPlan(
                query=query,
                intent=intent_type,
                primary_path='business_graph',
                secondary_paths=['vector_evidence', 'implementation_graph'],
                need_business_graph=True,
                need_implementation_graph=True,
                need_vector_evidence=True,
                need_graph_expansion=True,
                metadata={'reason': 'Business process query → Business Graph first, expand neighbors'},
            )

        elif intent_type == 'relationship':
            return RetrievalPlan(
                query=query,
                intent=intent_type,
                primary_path='hybrid',
                secondary_paths=['business_graph', 'implementation_graph', 'vector_evidence'],
                need_business_graph=True,
                need_implementation_graph=True,
                need_vector_evidence=True,
                need_graph_expansion=True,
                metadata={'reason': 'Relationship query → Hybrid multi-path retrieval'},
            )

        elif intent_type == 'dependency':
            return RetrievalPlan(
                query=query,
                intent=intent_type,
                primary_path='hybrid',
                secondary_paths=['business_graph', 'implementation_graph', 'vector_evidence'],
                need_business_graph=True,
                need_implementation_graph=True,
                need_vector_evidence=True,
                need_graph_expansion=True,
                metadata={'reason': 'Dependency query → Graph traversal + evidence'},
            )

        elif intent_type == 'api_code_db':
            return RetrievalPlan(
                query=query,
                intent=intent_type,
                primary_path='implementation_graph',
                secondary_paths=['vector_evidence'],
                need_business_graph=False,
                need_implementation_graph=True,
                need_vector_evidence=True,
                need_graph_expansion=True,
                metadata={'reason': 'API/Code/DB query → Implementation Graph first'},
            )

        elif intent_type == 'impact_analysis':
            return RetrievalPlan(
                query=query,
                intent=intent_type,
                primary_path='hybrid',
                secondary_paths=['business_graph', 'implementation_graph', 'vector_evidence'],
                need_business_graph=True,
                need_implementation_graph=True,
                need_vector_evidence=True,
                need_graph_expansion=True,
                metadata={'reason': 'Impact analysis → Full hybrid retrieval with expansion'},
            )

        elif intent_type == 'troubleshooting':
            return RetrievalPlan(
                query=query,
                intent=intent_type,
                primary_path='vector_evidence',
                secondary_paths=['implementation_graph'],
                need_business_graph=False,
                need_implementation_graph=True,
                need_vector_evidence=True,
                need_graph_expansion=False,
                metadata={'reason': 'Troubleshooting → Vector Evidence first + Implementation expansion'},
            )

        elif intent_type == 'workflow_generation':
            return RetrievalPlan(
                query=query,
                intent=intent_type,
                primary_path='hybrid',
                secondary_paths=['business_graph', 'implementation_graph', 'vector_evidence'],
                need_business_graph=True,
                need_implementation_graph=True,
                need_vector_evidence=True,
                need_graph_expansion=True,
                metadata={'reason': 'Workflow generation → Business + Implementation + Evidence'},
            )

        elif intent_type == 'evidence_coverage':
            return RetrievalPlan(
                query=query,
                intent=intent_type,
                primary_path='hybrid',
                secondary_paths=[],
                need_business_graph=False,
                need_implementation_graph=False,
                need_vector_evidence=False,
                need_graph_expansion=False,
                metadata={
                    'reason': 'Evidence coverage query → Compute stats from JSONL metadata',
                    'requires_evidence_coverage_stats': True,
                },
            )

        else:  # unknown
            return RetrievalPlan(
                query=query,
                intent=intent_type,
                primary_path='hybrid',
                secondary_paths=['vector_evidence', 'business_graph', 'implementation_graph'],
                need_business_graph=True,
                need_implementation_graph=True,
                need_vector_evidence=True,
                need_graph_expansion=False,
                metadata={'reason': 'Unknown intent → Hybrid fallback'},
            )

    def route(self, query: str) -> RetrievalPlan:
        """Classify intent and build plan in one step."""
        intent = self.classify_intent(query)
        plan = self.build_plan(intent)
        return plan
