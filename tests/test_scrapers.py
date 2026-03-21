"""测试 scraper 的解析逻辑（mock HTTP 调用）"""

import pytest
from unittest.mock import patch, MagicMock
from review_radar.scrapers import (
    search_app_store, search_google_play,
    fetch_app_store_reviews, _make_review_id,
)


class TestMakeReviewId:
    def test_deterministic(self):
        id1 = _make_review_id("app_store", "Great app", "2026-01-01")
        id2 = _make_review_id("app_store", "Great app", "2026-01-01")
        assert id1 == id2

    def test_different_inputs(self):
        id1 = _make_review_id("app_store", "Great app", "2026-01-01")
        id2 = _make_review_id("google_play", "Great app", "2026-01-01")
        assert id1 != id2

    def test_length(self):
        rid = _make_review_id("app_store", "test", "2026-01-01")
        assert len(rid) == 12


class TestSearchAppStore:
    @patch("review_radar.scrapers.httpx.get")
    def test_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "results": [{
                "trackId": 123456,
                "trackName": "TestApp",
                "bundleId": "com.test.app",
                "artworkUrl100": "https://example.com/icon.png",
                "primaryGenreName": "Social",
            }]
        }
        mock_get.return_value = mock_resp

        result = search_app_store("TestApp")
        assert result is not None
        assert result["app_id"] == 123456
        assert result["app_name"] == "TestApp"
        assert result["bundle_id"] == "com.test.app"

    @patch("review_radar.scrapers.httpx.get")
    def test_no_results(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": []}
        mock_get.return_value = mock_resp

        result = search_app_store("NonExistentApp")
        assert result is None

    @patch("review_radar.scrapers.httpx.get")
    def test_exception(self, mock_get):
        mock_get.side_effect = Exception("Network error")
        result = search_app_store("TestApp")
        assert result is None


class TestSearchGooglePlay:
    @patch("review_radar.scrapers.gplay_search")
    @patch("review_radar.scrapers.gplay_app")
    def test_with_bundle_id(self, mock_app, mock_search):
        mock_app.return_value = {
            "appId": "com.test.app",
            "title": "TestApp",
            "icon": "https://example.com/icon.png",
            "genre": "Social",
        }

        result = search_google_play("TestApp", bundle_id="com.test.app")
        assert result is not None
        assert result["app_id"] == "com.test.app"
        mock_search.assert_not_called()

    @patch("review_radar.scrapers.gplay_search")
    @patch("review_radar.scrapers.gplay_app")
    def test_fallback_to_search(self, mock_app, mock_search):
        mock_app.side_effect = Exception("Not found")
        mock_search.return_value = [{
            "appId": "com.test.app2",
            "title": "TestApp2",
            "icon": "https://example.com/icon2.png",
            "genre": "Tools",
        }]

        result = search_google_play("TestApp", bundle_id="com.bad.id")
        assert result is not None
        assert result["app_id"] == "com.test.app2"

    @patch("review_radar.scrapers.gplay_search")
    def test_no_results(self, mock_search):
        mock_search.return_value = []
        result = search_google_play("NonExistent")
        assert result is None


class TestFetchAppStoreReviews:
    @patch("review_radar.scrapers.httpx.get")
    def test_basic_fetch(self, mock_get):
        # 第一页返回评论，第二页返回空（模拟分页结束）
        page1_resp = MagicMock()
        page1_resp.status_code = 200
        page1_resp.json.return_value = {
            "feed": {
                "entry": [
                    {  # App info entry (no im:rating, should be skipped)
                        "id": {"label": "app-info"},
                        "title": {"label": "App"},
                    },
                    {  # Actual review
                        "im:rating": {"label": "5"},
                        "content": {"label": "Great app!"},
                        "title": {"label": "Love it"},
                        "im:version": {"label": "2.0"},
                        "author": {"name": {"label": "User1"}},
                        "updated": {"label": "2026-03-01T00:00:00"},
                    },
                    {  # Another review
                        "im:rating": {"label": "1"},
                        "content": {"label": "Crashes all the time"},
                        "title": {"label": "Bad"},
                        "im:version": {"label": "2.0"},
                        "author": {"name": {"label": "User2"}},
                        "updated": {"label": "2026-03-02T00:00:00"},
                    },
                ]
            }
        }
        page2_resp = MagicMock()
        page2_resp.status_code = 200
        page2_resp.json.return_value = {"feed": {"entry": []}}

        mock_get.side_effect = [page1_resp, page2_resp]

        reviews = fetch_app_store_reviews("123456", "us", count=10)
        assert len(reviews) == 2
        assert reviews[0].platform == "app_store"
        assert reviews[0].rating == 5
        assert reviews[0].content == "Great app!"
        assert reviews[0].country == "us"

    @patch("review_radar.scrapers.httpx.get")
    def test_empty_feed(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"feed": {"entry": []}}
        mock_get.return_value = mock_resp

        reviews = fetch_app_store_reviews("123456", "us", count=10)
        assert len(reviews) == 0

    @patch("review_radar.scrapers.httpx.get")
    def test_http_error(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp

        reviews = fetch_app_store_reviews("123456", "us", count=10)
        assert len(reviews) == 0
