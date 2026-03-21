"""国家/地区可用性检测 — 检测 App 在各国家的上架情况"""

import asyncio
from concurrent.futures import ThreadPoolExecutor

import httpx
from google_play_scraper import app as gplay_app

# 支持的国家列表
COUNTRIES = {
    "us": "🇺🇸 美国",
    "cn": "🇨🇳 中国",
    "jp": "🇯🇵 日本",
    "kr": "🇰🇷 韩国",
    "gb": "🇬🇧 英国",
    "de": "🇩🇪 德国",
    "fr": "🇫🇷 法国",
    "au": "🇦🇺 澳大利亚",
    "ca": "🇨🇦 加拿大",
    "hk": "🇭🇰 中国香港",
    "tw": "🇹🇼 中国台湾",
    "sg": "🇸🇬 新加坡",
    "in": "🇮🇳 印度",
    "br": "🇧🇷 巴西",
    "mx": "🇲🇽 墨西哥",
}


async def check_app_store_availability(
    app_store_id: str, countries: list[str]
) -> dict[str, bool]:
    """检测 App Store 在各国家的可用性（iTunes Lookup API）"""
    sem = asyncio.Semaphore(5)
    results = {}

    async def _check(client: httpx.AsyncClient, code: str):
        async with sem:
            try:
                resp = await client.get(
                    "https://itunes.apple.com/lookup",
                    params={"id": app_store_id, "country": code},
                    timeout=10,
                )
                data = resp.json()
                results[code] = data.get("resultCount", 0) > 0
            except Exception:
                results[code] = False

    async with httpx.AsyncClient() as client:
        await asyncio.gather(*[_check(client, c) for c in countries])

    return results


async def check_google_play_availability(
    google_play_id: str, countries: list[str]
) -> dict[str, bool]:
    """检测 Google Play 在各国家的可用性"""
    sem = asyncio.Semaphore(3)
    results = {}
    executor = ThreadPoolExecutor(max_workers=5)

    def _check_sync(code: str) -> tuple[str, bool]:
        try:
            gplay_app(google_play_id, country=code)
            return code, True
        except Exception:
            return code, False

    async def _check(code: str):
        async with sem:
            loop = asyncio.get_event_loop()
            c, ok = await loop.run_in_executor(executor, _check_sync, code)
            results[c] = ok

    await asyncio.gather(*[_check(c) for c in countries])
    executor.shutdown(wait=False)
    return results


async def check_availability(
    app_store_id: str | None,
    google_play_id: str | None,
    countries: list[str] | None = None,
) -> dict[str, dict[str, bool]]:
    """检测 App 在各国家各平台的可用性

    返回: {"us": {"app_store": True, "google_play": False}, ...}
    """
    if countries is None:
        countries = list(COUNTRIES.keys())

    tasks = []
    if app_store_id:
        tasks.append(check_app_store_availability(app_store_id, countries))
    if google_play_id:
        tasks.append(check_google_play_availability(google_play_id, countries))

    results_list = await asyncio.gather(*tasks)

    ios_results = results_list[0] if app_store_id else {}
    gplay_idx = 1 if app_store_id else 0
    gplay_results = results_list[gplay_idx] if google_play_id and gplay_idx < len(results_list) else {}

    combined = {}
    for code in countries:
        combined[code] = {
            "app_store": ios_results.get(code, False) if app_store_id else False,
            "google_play": gplay_results.get(code, False) if google_play_id else False,
        }

    return combined


def check_availability_sync(
    app_store_id: str | None,
    google_play_id: str | None,
    countries: list[str] | None = None,
) -> dict[str, dict[str, bool]]:
    """同步版本，供 Streamlit 调用"""
    return asyncio.run(check_availability(app_store_id, google_play_id, countries))
