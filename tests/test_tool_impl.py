"""测试 tool_impl.py — JSON 提取、analyze_batch、报告生成"""

import json
from unittest.mock import patch, MagicMock

from review_radar.tool_impl import _extract_json, tool_analyze_batch, tool_evaluate_coverage


class TestExtractJson:
    def test_plain_json(self):
        text = '{"key": "value"}'
        result = _extract_json(text)
        assert result == {"key": "value"}

    def test_json_in_markdown_block(self):
        text = '```json\n{"key": "value"}\n```'
        result = _extract_json(text)
        assert result == {"key": "value"}

    def test_json_with_surrounding_text(self):
        text = '这是分析结果：\n{"results": [1, 2, 3]}\n以上是结果。'
        result = _extract_json(text)
        assert result is not None
        assert result.get("results") == [1, 2, 3]

    def test_invalid_json(self):
        text = "这不是 JSON"
        result = _extract_json(text)
        assert result is None

    def test_empty_string(self):
        result = _extract_json("")
        assert result is None


class TestAnalyzeBatch:
    @patch("review_radar.tool_impl.chat_simple")
    def test_successful_analysis(self, mock_chat):
        mock_chat.return_value = json.dumps({
            "results": [
                {"id": "r1", "sentiment": "positive", "sentiment_score": 0.8,
                 "category": "功能", "keywords": ["好用"], "pain_point": None,
                 "pain_severity": None, "feature": "搜索", "usage_scenario": "日常",
                 "rating_sentiment_match": True}
            ],
            "batch_summary": {"positive": 1, "negative": 0, "neutral": 0}
        })

        reviews = [{"id": "r1", "content": "很好用", "rating": 5, "platform": "app_store",
                     "version": "1.0", "date": "2024-01-01", "country": "us"}]
        result = tool_analyze_batch(0, reviews)

        assert result["batch_index"] == 0
        assert result["analyzed_count"] == 1
        assert len(result["results"]) == 1

    @patch("review_radar.tool_impl.chat_simple")
    def test_json_parse_failure_returns_error(self, mock_chat):
        mock_chat.return_value = "这不是 JSON"

        reviews = [{"id": "r1", "content": "测试", "rating": 3, "platform": "app_store",
                     "version": "1.0", "date": "2024-01-01", "country": "us"}]
        result = tool_analyze_batch(0, reviews)

        assert "error" in result


class TestEvaluateCoverage:
    @patch("review_radar.tool_impl.chat_simple")
    def test_parse_failure_returns_not_complete(self, mock_chat):
        """评估解析失败时应返回 is_complete=False"""
        mock_chat.return_value = "无法解析的响应"

        result = tool_evaluate_coverage(
            total_reviews=100,
            analyzed_batches=2,
            aggregated_results={"total_analyzed": 100},
        )

        assert result["is_complete"] is False
        assert "解析失败" in result["message"]

    @patch("review_radar.tool_impl.chat_simple")
    def test_successful_evaluation(self, mock_chat):
        mock_chat.return_value = json.dumps({
            "is_complete": True,
            "coverage_score": 0.95,
            "issues": [],
            "improvement_actions": [],
            "strategy_adjustments": [],
        })

        result = tool_evaluate_coverage(
            total_reviews=100,
            analyzed_batches=2,
            aggregated_results={"total_analyzed": 100},
        )

        assert result["is_complete"] is True
        assert result["coverage_score"] == 0.95
