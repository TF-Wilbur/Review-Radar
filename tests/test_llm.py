"""测试 llm.py — Client 缓存、健康检查、运行时配置"""

from unittest import mock
from unittest.mock import MagicMock, patch

from review_radar.llm import (
    get_client, get_model, set_runtime_config, clear_runtime_config,
    check_health, _cached_client,
)


class TestRuntimeConfig:
    def setup_method(self):
        clear_runtime_config()

    def teardown_method(self):
        clear_runtime_config()

    def test_set_and_get_model(self):
        set_runtime_config(model="gpt-4o")
        assert get_model() == "gpt-4o"

    def test_clear_runtime_config(self):
        set_runtime_config(model="gpt-4o", api_key="test-key")
        clear_runtime_config()
        # 应回退到 .env 配置
        assert get_model() != "gpt-4o" or get_model() == ""

    def test_param_overrides_runtime(self):
        set_runtime_config(model="runtime-model")
        assert get_model("param-model") == "param-model"


class TestClientCache:
    def test_same_params_return_same_client(self):
        _cached_client.cache_clear()
        c1 = _cached_client("key1", "https://api.example.com/v1")
        c2 = _cached_client("key1", "https://api.example.com/v1")
        assert c1 is c2

    def test_different_params_return_different_client(self):
        _cached_client.cache_clear()
        c1 = _cached_client("key1", "https://api.example.com/v1")
        c2 = _cached_client("key2", "https://api.example.com/v1")
        assert c1 is not c2


class TestCheckHealth:
    @patch("review_radar.llm.get_client")
    def test_health_success(self, mock_get_client):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "hello"
        mock_client.chat.completions.create.return_value = mock_resp
        mock_get_client.return_value = mock_client

        ok, msg = check_health("key", "url", "model")
        assert ok is True
        assert "成功" in msg

    @patch("review_radar.llm.get_client")
    def test_health_failure(self, mock_get_client):
        mock_get_client.side_effect = Exception("connection refused")

        ok, msg = check_health("key", "url", "model")
        assert ok is False
        assert "失败" in msg
