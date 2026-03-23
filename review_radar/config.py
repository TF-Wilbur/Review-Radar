"""集中配置管理 — 所有可配置项从环境变量读取，提供默认值"""

import os
from pathlib import Path
from dotenv import load_dotenv

# 只在此处调用一次 load_dotenv
load_dotenv()

# ── LLM 配置 ──
LLM_API_KEY: str = os.environ.get("LLM_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")
LLM_BASE_URL: str = os.environ.get("LLM_BASE_URL", "https://api.minimax.chat/v1")
LLM_MODEL: str = os.environ.get("LLM_MODEL", "MiniMax-Text-01")

# ── Agent 配置 ──
BATCH_SIZE: int = int(os.environ.get("BATCH_SIZE", "50"))
MAX_EVAL_ROUNDS: int = int(os.environ.get("MAX_EVAL_ROUNDS", "3"))

# ── 抓取配置 ──
HTTP_TIMEOUT: int = int(os.environ.get("HTTP_TIMEOUT", "15"))
FETCH_MAX_WORKERS: int = int(os.environ.get("FETCH_MAX_WORKERS", "3"))
ANALYZE_MAX_WORKERS: int = int(os.environ.get("ANALYZE_MAX_WORKERS", "3"))
FETCH_DELAY: float = float(os.environ.get("FETCH_DELAY", "0.3"))
FETCH_MAX_RETRIES: int = int(os.environ.get("FETCH_MAX_RETRIES", "3"))
FETCH_BACKOFF_BASE: float = float(os.environ.get("FETCH_BACKOFF_BASE", "1.5"))
MIN_REVIEW_LENGTH: int = int(os.environ.get("MIN_REVIEW_LENGTH", "5"))

# ── Web UI 配置 ──
PAGE_SIZE: int = int(os.environ.get("PAGE_SIZE", "20"))
CACHE_TTL: int = int(os.environ.get("CACHE_TTL", "86400"))  # 24 小时
CACHE_DIR: Path = Path(os.environ.get("CACHE_DIR", "")) if os.environ.get("CACHE_DIR") else None  # None 表示用 tempfile

# ── 报告配置 ──
REPORT_OUTPUT_DIR: str = os.environ.get("REPORT_OUTPUT_DIR", "reports")

# ── 国家 → 语言映射 ──
COUNTRY_LANG: dict[str, str] = {
    "us": "en", "gb": "en", "au": "en", "ca": "en",
    "cn": "zh", "hk": "zh", "tw": "zh", "sg": "en",
    "jp": "ja", "kr": "ko", "de": "de", "fr": "fr",
    "in": "en", "br": "pt", "mx": "es",
}
