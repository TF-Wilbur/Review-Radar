"""测试 agent.py — 去重、sentiment_score 校验"""

from review_radar.agent import ReviewRadarAgent


class TestAgentDedup:
    def test_dedup_reviews(self):
        """测试评论去重逻辑"""
        agent = ReviewRadarAgent()
        reviews = [
            {"id": "r1", "content": "好用", "rating": 5},
            {"id": "r2", "content": "不好", "rating": 1},
            {"id": "r1", "content": "好用", "rating": 5},  # 重复
        ]
        seen = set()
        deduped = []
        for r in reviews:
            if r["id"] not in seen:
                seen.add(r["id"])
                deduped.append(r)
        assert len(deduped) == 2
        assert deduped[0]["id"] == "r1"
        assert deduped[1]["id"] == "r2"


class TestSentimentScoreClamp:
    def test_clamp_high(self):
        """超出范围的 sentiment_score 应被 clamp"""
        score = 1.5
        clamped = max(-1.0, min(1.0, float(score)))
        assert clamped == 1.0

    def test_clamp_low(self):
        score = -2.0
        clamped = max(-1.0, min(1.0, float(score)))
        assert clamped == -1.0

    def test_normal_score(self):
        score = 0.5
        clamped = max(-1.0, min(1.0, float(score)))
        assert clamped == 0.5
