"""测试数据模型、JSON 解析、聚合逻辑"""

import pytest
from review_radar.models import Review, AppInfo, AnalyzedReview, Sentiment, Category, Severity


# ── Review / AppInfo 创建 ──

class TestModels:
    def test_review_defaults(self):
        r = Review(id="r1", platform="app_store", rating=5, content="Great", date="2026-01-01")
        assert r.country == "us"
        assert r.thumbs_up == 0
        assert r.version is None

    def test_review_with_all_fields(self):
        r = Review(
            id="r2", platform="google_play", rating=1, content="Bad",
            date="2026-03-01", version="2.0", language="zh",
            title="差评", thumbs_up=10, country="cn",
        )
        assert r.rating == 1
        assert r.country == "cn"
        assert r.thumbs_up == 10

    def test_app_info_defaults(self):
        info = AppInfo(app_name="Test")
        assert info.app_store_id is None
        assert info.google_play_id is None

    def test_analyzed_review_defaults(self):
        ar = AnalyzedReview(
            id="a1", sentiment=Sentiment.POSITIVE,
            sentiment_score=0.8, category=Category.PRAISE,
        )
        assert ar.keywords == []
        assert ar.pain_point is None


# ── _extract_json 边界情况 ──

class TestExtractJson:
    @pytest.fixture(autouse=True)
    def _import(self):
        from review_radar.tool_impl import _extract_json
        self.extract = _extract_json

    def test_plain_json(self):
        result = self.extract('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_in_code_block(self):
        text = '```json\n{"key": "value"}\n```'
        result = self.extract(text)
        assert result == {"key": "value"}

    def test_json_in_generic_code_block(self):
        text = '```\n{"key": 123}\n```'
        result = self.extract(text)
        assert result == {"key": 123}

    def test_json_with_surrounding_text(self):
        text = 'Here is the result:\n{"a": 1, "b": 2}\nDone.'
        result = self.extract(text)
        assert result == {"a": 1, "b": 2}

    def test_invalid_json(self):
        result = self.extract("not json at all")
        assert result is None

    def test_empty_string(self):
        result = self.extract("")
        assert result is None

    def test_nested_json(self):
        text = '{"results": [{"id": "1", "score": 0.5}]}'
        result = self.extract(text)
        assert result["results"][0]["id"] == "1"


# ── _aggregate_bucket 聚合逻辑 ──

class TestAggregateBucket:
    @pytest.fixture(autouse=True)
    def _setup(self):
        from review_radar.agent import ReviewRadarAgent
        self.agent = ReviewRadarAgent()

    def test_basic_aggregation(self):
        results = [
            {"sentiment": "positive", "category": "体验赞美", "keywords": ["好用", "流畅"], "pain_point": None},
            {"sentiment": "negative", "category": "功能吐槽", "keywords": ["闪退", "卡顿"], "pain_point": "闪退", "pain_severity": "high"},
            {"sentiment": "negative", "category": "功能吐槽", "keywords": ["闪退"], "pain_point": "闪退", "pain_severity": "high"},
            {"sentiment": "neutral", "category": "其他", "keywords": ["更新"], "pain_point": None},
        ]
        reviews = [
            {"rating": 5, "version": "1.0"},
            {"rating": 1, "version": "1.0"},
            {"rating": 2, "version": "1.1"},
            {"rating": 3, "version": "1.1"},
        ]
        agg = self.agent._aggregate_bucket(results, reviews)

        assert agg["review_count"] == 4
        assert agg["sentiment_distribution"]["positive"] == 1
        assert agg["sentiment_distribution"]["negative"] == 2
        assert agg["sentiment_distribution"]["neutral"] == 1
        assert agg["category_distribution"]["功能吐槽"] == 2
        # 闪退出现 3 次（2 条评论的 keywords + pain_point 合并后 keywords 有 3 次）
        kw_map = {kw["word"]: kw["count"] for kw in agg["top_keywords"]}
        assert kw_map["闪退"] >= 2
        # 痛点
        assert len(agg["top_pain_points"]) >= 1
        assert agg["top_pain_points"][0]["description"] == "闪退"
        assert agg["top_pain_points"][0]["mention_count"] == 2
        # 版本趋势
        assert "1.0" in agg["version_trends"]
        assert "1.1" in agg["version_trends"]

    def test_empty_input(self):
        agg = self.agent._aggregate_bucket([], [])
        assert agg["review_count"] == 0
        assert agg["sentiment_distribution"]["positive"] == 0


# ── _apply_improvements 关键词合并和痛点去重 ──

class TestApplyImprovements:
    @pytest.fixture(autouse=True)
    def _setup(self):
        from review_radar.agent import ReviewRadarAgent
        self.agent = ReviewRadarAgent()

    def test_merge_keywords(self):
        agg = {
            "top_keywords": [
                {"word": "crash", "count": 5},
                {"word": "闪退", "count": 3},
                {"word": "崩溃", "count": 2},
                {"word": "卡顿", "count": 4},
            ],
            "top_pain_points": [],
        }
        actions = [{"action": "merge_keywords", "details": {"groups": [["crash", "闪退", "崩溃"]]}}]
        result = self.agent._apply_improvements(agg, actions)

        kw_map = {kw["word"]: kw["count"] for kw in result["top_keywords"]}
        assert "crash" in kw_map
        assert kw_map["crash"] == 10  # 5 + 3 + 2
        assert "闪退" not in kw_map
        assert "崩溃" not in kw_map

    def test_merge_pain_points(self):
        agg = {
            "top_keywords": [],
            "top_pain_points": [
                {"description": "闪退", "mention_count": 5, "severity": "high"},
                {"description": "闪退", "mention_count": 3, "severity": "high"},
                {"description": "卡顿", "mention_count": 2, "severity": "medium"},
            ],
        }
        actions = [{"action": "merge_pain_points", "details": {}}]
        result = self.agent._apply_improvements(agg, actions)

        assert len(result["top_pain_points"]) == 2
        descs = [pp["description"] for pp in result["top_pain_points"]]
        assert descs.count("闪退") == 1
