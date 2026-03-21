"""评论抓取封装 — App Store (iTunes RSS/API) + Google Play 并行抓取"""

import asyncio
import hashlib
import json
import xml.etree.ElementTree as ET
from datetime import datetime

import httpx
from google_play_scraper import Sort, reviews as gplay_reviews, search as gplay_search, app as gplay_app

from review_radar.models import Review, AppInfo


# ── App 搜索 ────────────────────────────────────────────────────

def search_app_store(app_name: str, country: str = "us") -> dict | None:
    """搜索 App Store，用 iTunes Search API"""
    try:
        resp = httpx.get(
            "https://itunes.apple.com/search",
            params={"term": app_name, "country": country, "media": "software", "limit": 5},
            timeout=15,
        )
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
        }
    except Exception as e:
        print(f"[search_app_store] 搜索失败: {e}")
        return None


def search_google_play(app_name: str, bundle_id: str | None = None) -> dict | None:
    """搜索 Google Play，appId 为 None 时用 bundleId fallback"""
    try:
        # 优先用 bundleId 直接查（最准确）
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

        # fallback: 搜索
        results = gplay_search(app_name, n_hits=5, lang="en")
        if results:
            for r in results:
                if r.get("appId"):
                    return {
                        "app_id": r["appId"],
                        "app_name": r.get("title"),
                        "icon_url": r.get("icon"),
                        "category": r.get("genre"),
                    }

        return None
    except Exception as e:
        print(f"[search_google_play] 搜索失败: {e}")
        return None


def search_app(app_name: str, country: str = "us") -> AppInfo:
    """搜索 App Store 和 Google Play，返回 AppInfo"""
    app_store_result = search_app_store(app_name, country)
    bundle_id = app_store_result.get("bundle_id") if app_store_result else None
    gplay_result = search_google_play(app_name, bundle_id=bundle_id)

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


# ── 评论抓取 ────────────────────────────────────────────────────

def _make_review_id(platform: str, content: str, date: str) -> str:
    """生成评论唯一 ID"""
    raw = f"{platform}:{content[:50]}:{date}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def fetch_app_store_reviews(app_id: str, country: str = "us", count: int = 200) -> list[Review]:
    """抓取 App Store 评论 — 用 iTunes RSS JSON feed + 分页"""
    reviews = []
    page = 1
    max_pages = (count // 50) + 2  # RSS 每页最多 50 条

    while len(reviews) < count and page <= max_pages:
        try:
            url = (
                f"https://itunes.apple.com/{country}/rss/customerreviews"
                f"/page={page}/id={app_id}/sortby=mostrecent/json"
            )
            resp = httpx.get(url, timeout=15, follow_redirects=True)
            if resp.status_code != 200:
                break

            data = resp.json()
            feed = data.get("feed", {})
            entries = feed.get("entry", [])

            if not entries:
                break

            # 第一个 entry 通常是 app 信息，跳过
            for entry in entries:
                # 跳过非评论 entry（app 信息）
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

                reviews.append(Review(
                    id=_make_review_id("app_store", content, date_str),
                    platform="app_store",
                    rating=rating,
                    content=content,
                    date=date_str,
                    version=version,
                    title=title if title else None,
                    country=country,
                ))

            page += 1

        except Exception as e:
            print(f"[fetch_app_store] 第 {page} 页抓取失败: {e}")
            break

    return reviews[:count]


def fetch_google_play_reviews(app_id: str, count: int = 200, country: str = "us", lang: str = "zh") -> list[Review]:
    """抓取 Google Play 评论"""
    reviews = []
    try:
        result, _ = gplay_reviews(
            app_id,
            lang=lang,
            country=country,
            sort=Sort.NEWEST,
            count=count,
        )

        for r in result:
            content = (r.get("content") or "").strip()
            if not content:
                continue
            date_val = r.get("at")
            date_str = date_val.strftime("%Y-%m-%d") if isinstance(date_val, datetime) else str(date_val)[:10]

            reviews.append(Review(
                id=_make_review_id("google_play", content, date_str),
                platform="google_play",
                rating=r.get("score", 0),
                content=content,
                date=date_str,
                version=r.get("reviewCreatedVersion"),
                thumbs_up=r.get("thumbsUpCount", 0),
                country=country,
            ))
    except Exception as e:
        print(f"[fetch_google_play] 抓取失败: {e}")

    return reviews


async def fetch_all_reviews(
    app_store_id: str | None,
    google_play_id: str | None,
    count: int = 200,
    country: str = "us",
) -> list[Review]:
    """并行抓取 App Store + Google Play 评论"""
    loop = asyncio.get_event_loop()
    tasks = []

    if app_store_id:
        tasks.append(loop.run_in_executor(
            None, fetch_app_store_reviews, app_store_id, country, count
        ))
    if google_play_id:
        tasks.append(loop.run_in_executor(
            None, fetch_google_play_reviews, google_play_id, count, country
        ))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_reviews = []
    for r in results:
        if isinstance(r, list):
            all_reviews.extend(r)
        elif isinstance(r, Exception):
            print(f"[fetch_all_reviews] 抓取异常: {r}")

    # 按日期倒序
    all_reviews.sort(key=lambda x: x.date, reverse=True)
    return all_reviews
