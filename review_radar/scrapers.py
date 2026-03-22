"""评论抓取封装 — App Store (iTunes RSS/API) + Google Play 并行抓取

v2: 重试机制、Review ID 修复、多排序支持、进度回调
"""

import hashlib
import json
import logging
import time
from datetime import datetime
from typing import Callable

import httpx
from google_play_scraper import Sort, reviews as gplay_reviews, search as gplay_search, app as gplay_app

from review_radar.models import Review, AppInfo
from review_radar.config import (
    COUNTRY_LANG, HTTP_TIMEOUT,
    FETCH_MAX_RETRIES, FETCH_BACKOFF_BASE,
)

logger = logging.getLogger("review_radar.scrapers")

# 进度回调类型：(fetched, total, platform, country)
ProgressCallback = Callable[[int, int, str, str], None] | None


# ── 重试工具 ────────────────────────────────────────────────────

def _retry(fn, max_retries: int = FETCH_MAX_RETRIES, backoff_base: float = FETCH_BACKOFF_BASE):
    """带指数退避的重试，返回结果或抛出最后一次异常"""
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if attempt < max_retries:
                wait = backoff_base ** attempt
                logger.warning("重试 %d/%d (%.1fs 后): %s", attempt + 1, max_retries, wait, e)
                time.sleep(wait)
    raise last_exc


# ── App 搜索 ────────────────────────────────────────────────────

def search_app_store(app_name: str, country: str = "us") -> dict | None:
    """搜索 App Store，用 iTunes Search API"""
    try:
        def _do():
            return httpx.get(
                "https://itunes.apple.com/search",
                params={"term": app_name, "country": country, "media": "software", "limit": 5},
                timeout=HTTP_TIMEOUT,
            )
        resp = _retry(_do)
        results = resp.json().get("results", [])
        if not results:
            return None
        app = results[0]
        return {
            "app_id": app.get("trackId"),
            "app_name": app.get("trackName"),
            "bundle_id": app.get("bundleId"),
            "icon_url": app.get("artworkUrl100"),
            "category": app.get("primaryGenreName"),
            "developer": app.get("artistName", ""),
        }
    except Exception as e:
        logger.warning("App Store 搜索失败: %s", e)
        return None


def _name_similarity(a: str, b: str) -> float:
    """简单的名称相似度：基于共同词的 Jaccard 系数"""
    if not a or not b:
        return 0.0
    # 统一小写，去除标点
    import re
    def _tokens(s):
        return set(re.sub(r'[^\w\s]', ' ', s.lower()).split())
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def search_google_play(app_name: str, bundle_id: str | None = None,
                       app_store_name: str | None = None,
                       app_store_developer: str | None = None) -> dict | None:
    """搜索 Google Play，带名称和开发者交叉验证"""
    try:
        # 1. 先用 bundle_id 精确匹配
        if bundle_id:
            try:
                info = gplay_app(bundle_id)
                if info:
                    return {
                        "app_id": info.get("appId") or bundle_id,
                        "app_name": info.get("title"),
                        "icon_url": info.get("icon"),
                        "category": info.get("genre"),
                    }
            except Exception:
                pass

        # 2. 搜索并验证（优先用 App Store 返回的正确名称，避免用户拼写错误导致搜不到）
        search_term = app_store_name or app_name
        results = gplay_search(search_term, n_hits=5, lang="en")
        if not results and search_term != app_name:
            # 如果纠正后的名称也搜不到，再试原始输入
            results = gplay_search(app_name, n_hits=5, lang="en")
        if not results:
            return None

        ref_name = app_store_name or app_name
        ref_dev = (app_store_developer or "").lower().strip()

        for r in results:
            if not r.get("appId"):
                continue

            gp_name = r.get("title", "")
            gp_dev = (r.get("developer", "") or "").lower().strip()

            # 开发者名称匹配（最可靠的信号）
            dev_match = ref_dev and gp_dev and (
                ref_dev in gp_dev or gp_dev in ref_dev
            )

            # 名称相似度
            sim = _name_similarity(ref_name, gp_name)

            # 通过条件：开发者匹配 + 名称有一定相似度，或名称高度相似
            if dev_match and sim >= 0.2:
                return {
                    "app_id": r["appId"],
                    "app_name": gp_name,
                    "icon_url": r.get("icon"),
                    "category": r.get("genre"),
                }
            if sim >= 0.5:
                return {
                    "app_id": r["appId"],
                    "app_name": gp_name,
                    "icon_url": r.get("icon"),
                    "category": r.get("genre"),
                }

        # 没有匹配的结果
        logger.info("Google Play 未找到匹配: %s (ref_dev=%s)", app_name, ref_dev)
        return None
    except Exception as e:
        logger.warning("Google Play 搜索失败: %s", e)
        return None


def search_app(app_name: str, country: str = "us") -> AppInfo:
    """搜索 App Store 和 Google Play，返回 AppInfo"""
    app_store_result = search_app_store(app_name, country)
    bundle_id = app_store_result.get("bundle_id") if app_store_result else None
    app_store_name = app_store_result.get("app_name") if app_store_result else None
    app_store_developer = app_store_result.get("developer") if app_store_result else None
    gplay_result = search_google_play(
        app_name,
        bundle_id=bundle_id,
        app_store_name=app_store_name,
        app_store_developer=app_store_developer,
    )

    return AppInfo(
        app_name=app_name,
        app_store_id=str(app_store_result["app_id"]) if app_store_result else None,
        google_play_id=gplay_result["app_id"] if gplay_result else None,
        app_name_en=app_store_result.get("app_name") if app_store_result else (
            gplay_result.get("app_name") if gplay_result else None
        ),
        icon_url=app_store_result.get("icon_url") if app_store_result else (
            gplay_result.get("icon_url") if gplay_result else None
        ),
        category=app_store_result.get("category") if app_store_result else (
            gplay_result.get("category") if gplay_result else None
        ),
    )


# ── 评论 ID 生成 ────────────────────────────────────────────────

def _make_review_id(platform: str, content: str, date: str, extra: str = "") -> str:
    """生成评论唯一 ID — 用完整 content + extra 区分字段"""
    raw = f"{platform}:{content}:{date}:{extra}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


# ── App Store 评论抓取 ──────────────────────────────────────────

def fetch_app_store_reviews(
    app_id: str,
    country: str = "us",
    count: int = 200,
    sort: str = "mostrecent",
    on_progress: ProgressCallback = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[Review]:
    """抓取 App Store 评论 — iTunes RSS JSON feed + 分页 + 重试 + 日期过滤"""
    reviews = []
    page = 1
    # 有日期过滤时多抓几页，因为过滤后数量会减少
    extra_pages = 5 if (date_from or date_to) else 0
    max_pages = (count // 50) + 2 + extra_pages
    consecutive_failures = 0

    while len(reviews) < count and page <= max_pages:
        def _fetch_page(p=page):
            url = (
                f"https://itunes.apple.com/{country}/rss/customerreviews"
                f"/page={p}/id={app_id}/sortby={sort}/json"
            )
            resp = httpx.get(url, timeout=HTTP_TIMEOUT, follow_redirects=True)
            if resp.status_code != 200:
                raise httpx.HTTPStatusError(
                    f"HTTP {resp.status_code}", request=resp.request, response=resp
                )
            return resp.json()

        try:
            data = _retry(_fetch_page)
            consecutive_failures = 0
        except Exception as e:
            logger.warning("App Store 第 %d 页抓取失败（已重试）: %s", page, e)
            consecutive_failures += 1
            if consecutive_failures >= 2:
                logger.warning("连续 %d 页失败，终止分页", consecutive_failures)
                break
            page += 1
            continue

        feed = data.get("feed", {})
        entries = feed.get("entry", [])
        if not entries:
            break

        for entry in entries:
            if "im:rating" not in entry:
                continue
            content = entry.get("content", {}).get("label", "").strip()
            if not content:
                continue

            title = entry.get("title", {}).get("label", "")
            rating = int(entry.get("im:rating", {}).get("label", "0"))
            version = entry.get("im:version", {}).get("label")
            author = entry.get("author", {}).get("name", {}).get("label", "")
            date_str = entry.get("updated", {}).get("label", "")[:10]

            # 日期过滤
            if date_from and date_str < date_from:
                continue
            if date_to and date_str > date_to:
                continue

            reviews.append(Review(
                id=_make_review_id("app_store", content, date_str, author),
                platform="app_store",
                rating=rating,
                content=content,
                date=date_str,
                version=version,
                title=title if title else None,
                country=country,
                language=COUNTRY_LANG.get(country, "en"),
            ))

        if on_progress:
            on_progress(len(reviews), count, "app_store", country)

        page += 1

    return reviews[:count]


# ── Google Play 评论抓取 ────────────────────────────────────────

def fetch_google_play_reviews(
    app_id: str,
    count: int = 200,
    country: str = "us",
    lang: str = "",
    sort: str = "newest",
    on_progress: ProgressCallback = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[Review]:
    """抓取 Google Play 评论 — 带分页 + 重试 + 日期过滤"""
    if not lang:
        lang = COUNTRY_LANG.get(country, "en")

    sort_enum = Sort.MOST_RELEVANT if sort == "relevant" else Sort.NEWEST

    reviews = []
    continuation_token = None
    # 每页请求量：google_play_scraper 单次最多约 200 条
    per_page = min(count, 200)
    # 有日期过滤时多抓几页，因为过滤后数量会减少
    extra_pages = 5 if (date_from or date_to) else 0
    max_pages = max((count // per_page) + 2, 5) + extra_pages  # 安全上限防止死循环

    try:
        for page in range(max_pages):
            if len(reviews) >= count:
                break

            def _do(token=continuation_token):
                return gplay_reviews(
                    app_id, lang=lang, country=country,
                    sort=sort_enum, count=per_page,
                    continuation_token=token,
                )

            result, continuation_token = _retry(_do)

            if not result:
                break

            for r in result:
                content = (r.get("content") or "").strip()
                if not content:
                    continue
                date_val = r.get("at")
                date_str = date_val.strftime("%Y-%m-%d") if isinstance(date_val, datetime) else str(date_val)[:10]
                thumbs = str(r.get("thumbsUpCount", 0))

                # 日期过滤
                if date_from and date_str < date_from:
                    continue
                if date_to and date_str > date_to:
                    continue

                reviews.append(Review(
                    id=_make_review_id("google_play", content, date_str, thumbs),
                    platform="google_play",
                    rating=r.get("score", 0),
                    content=content,
                    date=date_str,
                    version=r.get("reviewCreatedVersion"),
                    thumbs_up=r.get("thumbsUpCount", 0),
                    country=country,
                    language=lang,
                ))

            if on_progress:
                on_progress(len(reviews), count, "google_play", country)

            # 没有下一页了
            if continuation_token is None:
                break

    except Exception as e:
        logger.warning("Google Play 抓取失败（已重试）: %s", e)

    return reviews[:count]
