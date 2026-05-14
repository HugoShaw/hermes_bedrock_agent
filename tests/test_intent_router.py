"""Tests for retrieval/intent_router.py — question classification."""

from __future__ import annotations

import unittest

from hermes_bedrock_agent.retrieval.intent_router import (
    IntentType,
    RetrievalStrategy,
    classify_intent,
)


class TestClassifyIntentDefinition(unittest.TestCase):
    """Test definition intent detection."""

    def test_japanese_what_is(self):
        result = classify_intent("仕訳基礎とは何ですか")
        self.assertEqual(result.intent, IntentType.DEFINITION)
        self.assertEqual(result.strategy, RetrievalStrategy.HYBRID)

    def test_chinese_what_is(self):
        result = classify_intent("什么是对帐单系统")
        self.assertEqual(result.intent, IntentType.DEFINITION)

    def test_english_what_is(self):
        result = classify_intent("What is the AP module?")
        self.assertEqual(result.intent, IntentType.DEFINITION)

    def test_explain(self):
        result = classify_intent("システム管理の概要を説明して")
        self.assertEqual(result.intent, IntentType.DEFINITION)


class TestClassifyIntentProcedure(unittest.TestCase):
    """Test procedure intent detection."""

    def test_japanese_procedure(self):
        result = classify_intent("付款申請の手順を教えてください")
        self.assertEqual(result.intent, IntentType.PROCEDURE)
        self.assertEqual(result.strategy, RetrievalStrategy.HYBRID)

    def test_chinese_how_to(self):
        result = classify_intent("怎么做数据迁移的步骤")
        self.assertEqual(result.intent, IntentType.PROCEDURE)

    def test_english_how_to(self):
        result = classify_intent("How to configure the batch processing flow?")
        self.assertEqual(result.intent, IntentType.PROCEDURE)

    def test_flow(self):
        result = classify_intent("承認フローはどうなっていますか")
        self.assertEqual(result.intent, IntentType.PROCEDURE)


class TestClassifyIntentImpactAnalysis(unittest.TestCase):
    """Test impact analysis intent detection."""

    def test_japanese_impact(self):
        result = classify_intent("テーブルAを変更した場合の影響は？")
        self.assertEqual(result.intent, IntentType.IMPACT_ANALYSIS)
        self.assertEqual(result.strategy, RetrievalStrategy.GRAPH)

    def test_english_impact(self):
        result = classify_intent("What is the impact if we change the API?")
        self.assertEqual(result.intent, IntentType.IMPACT_ANALYSIS)

    def test_chinese_impact(self):
        result = classify_intent("修改这个表会有什么影响")
        self.assertEqual(result.intent, IntentType.IMPACT_ANALYSIS)


class TestClassifyIntentDependency(unittest.TestCase):
    """Test dependency intent detection."""

    def test_japanese_dependency(self):
        result = classify_intent("モジュールAはどのサービスを呼び出していますか")
        self.assertEqual(result.intent, IntentType.DEPENDENCY)
        self.assertEqual(result.strategy, RetrievalStrategy.GRAPH)

    def test_english_depends(self):
        result = classify_intent("What does ServiceB depend on?")
        self.assertEqual(result.intent, IntentType.DEPENDENCY)

    def test_chinese_calls(self):
        result = classify_intent("这个模块调用了哪些接口")
        self.assertEqual(result.intent, IntentType.DEPENDENCY)

    def test_references(self):
        result = classify_intent("Which tables does this module reference?")
        self.assertEqual(result.intent, IntentType.DEPENDENCY)


class TestClassifyIntentEvidence(unittest.TestCase):
    """Test evidence lookup intent detection."""

    def test_japanese_source(self):
        result = classify_intent("この仕様はどこに書いてありますか")
        self.assertEqual(result.intent, IntentType.EVIDENCE_LOOKUP)
        self.assertEqual(result.strategy, RetrievalStrategy.TEXT)

    def test_english_documented(self):
        result = classify_intent("Where is the API contract documented?")
        self.assertEqual(result.intent, IntentType.EVIDENCE_LOOKUP)


class TestClassifyIntentGeneral(unittest.TestCase):
    """Test fallback to general intent."""

    def test_empty_question(self):
        result = classify_intent("")
        self.assertEqual(result.intent, IntentType.GENERAL)
        self.assertEqual(result.confidence, 0.0)

    def test_whitespace_only(self):
        result = classify_intent("   ")
        self.assertEqual(result.intent, IntentType.GENERAL)

    def test_no_pattern_match(self):
        result = classify_intent("hello world")
        self.assertEqual(result.intent, IntentType.GENERAL)
        self.assertEqual(result.strategy, RetrievalStrategy.HYBRID)

    def test_custom_default_strategy(self):
        result = classify_intent("hello", default_strategy=RetrievalStrategy.TEXT)
        self.assertEqual(result.strategy, RetrievalStrategy.TEXT)


class TestIntentClassificationFields(unittest.TestCase):
    """Test IntentClassification result fields."""

    def test_has_confidence(self):
        result = classify_intent("What is X?")
        self.assertGreater(result.confidence, 0)

    def test_has_reasoning(self):
        result = classify_intent("What is X?")
        self.assertTrue(len(result.reasoning) > 0)

    def test_has_keywords_matched(self):
        result = classify_intent("影響分析をしてください")
        self.assertTrue(len(result.keywords_matched) > 0)


if __name__ == "__main__":
    unittest.main()
