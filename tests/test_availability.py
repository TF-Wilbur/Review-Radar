"""测试 availability.py — 可用性检测"""

from unittest.mock import patch, MagicMock

from review_radar.availability import COUNTRIES


class TestCountries:
    def test_countries_not_empty(self):
        assert len(COUNTRIES) > 0

    def test_us_in_countries(self):
        assert "us" in COUNTRIES

    def test_cn_in_countries(self):
        assert "cn" in COUNTRIES
