"""数据模型定义"""

from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime


class Sentiment(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class Category(str, Enum):
    BUG_COMPLAINT = "功能吐槽"
    PRAISE = "体验赞美"
    FEATURE_REQUEST = "需求建议"
    COMPETITOR_COMPARE = "竞品对比"
    OTHER = "其他"


class Severity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class Review:
    id: str
    platform: str  # "app_store" | "google_play"
    rating: int  # 1-5
    content: str
    date: str  # ISO format
    version: str | None = None
    language: str = "unknown"
    title: str | None = None
    thumbs_up: int = 0
    country: str = "us"  # 国家/地区代码


@dataclass
class AppInfo:
    app_name: str
    app_store_id: str | None = None
    google_play_id: str | None = None
    app_name_en: str | None = None
    icon_url: str | None = None
    category: str | None = None


@dataclass
class AnalyzedReview:
    id: str
    sentiment: Sentiment
    sentiment_score: float  # -1.0 to 1.0
    category: Category
    keywords: list[str] = field(default_factory=list)
    pain_point: str | None = None
    pain_severity: Severity | None = None
    feature: str | None = None              # 功能归因
    usage_scenario: str | None = None       # 用户场景
    rating_sentiment_match: bool = True     # 评分与情感是否一致


@dataclass
class BatchResult:
    batch_index: int
    analyzed_count: int
    results: list[AnalyzedReview] = field(default_factory=list)
    sentiment_distribution: dict[str, int] = field(default_factory=dict)
    category_distribution: dict[str, int] = field(default_factory=dict)
    top_keywords: list[dict] = field(default_factory=list)
    pain_points: list[dict] = field(default_factory=list)


@dataclass
class AggregatedAnalysis:
    total_reviews: int = 0
    total_analyzed: int = 0
    batches: list[BatchResult] = field(default_factory=list)
    sentiment_distribution: dict[str, int] = field(default_factory=dict)
    category_distribution: dict[str, int] = field(default_factory=dict)
    top_keywords: list[dict] = field(default_factory=list)
    top_pain_points: list[dict] = field(default_factory=list)
    version_trends: dict[str, dict] = field(default_factory=dict)
