"""测试 config.py 配置加载"""

import os
from unittest import mock


def test_default_values():
    """默认值应正确加载"""
    from review_radar.config import BATCH_SIZE, HTTP_TIMEOUT, FETCH_MAX_WORKERS, CACHE_TTL
    assert BATCH_SIZE == 50
    assert HTTP_TIMEOUT == 15
    assert FETCH_MAX_WORKERS == 3
    assert CACHE_TTL == 86400


def test_country_lang_mapping():
    """国家语言映射应包含主要国家"""
    from review_radar.config import COUNTRY_LANG
    assert COUNTRY_LANG["us"] == "en"
    assert COUNTRY_LANG["cn"] == "zh"
    assert COUNTRY_LANG["jp"] == "ja"
    assert COUNTRY_LANG["kr"] == "ko"
    assert COUNTRY_LANG["de"] == "de"


def test_env_override():
    """环境变量应能覆盖默认值"""
    with mock.patch.dict(os.environ, {"BATCH_SIZE": "100"}):
        # 需要重新加载模块
        import importlib
        import review_radar.config as cfg
        importlib.reload(cfg)
        assert cfg.BATCH_SIZE == 100
        # 恢复
        importlib.reload(cfg)
