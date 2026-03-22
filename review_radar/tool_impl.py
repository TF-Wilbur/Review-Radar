"""5 个 Tool 的具体实现"""

import json
import logging
import re
from datetime import datetime

from review_radar.models import AppInfo, Review
from review_radar.scrapers import (
    search_app as _search_app,
    fetch_app_store_reviews, fetch_google_play_reviews,
)
from review_radar.prompts import (
    ANALYZE_BATCH_PROMPT, EVALUATE_PROMPT, FEATURE_ANALYSIS_PROMPT,
    SEMANTIC_DEDUP_PROMPT,
    REPORT_EXECUTIVE_SUMMARY_PROMPT,
    REPORT_OUTLINE_PROMPT, REPORT_COUNTRY_CHAPTER_PROMPT,
    REPORT_OVERVIEW_PROMPT, REPORT_CROSS_COUNTRY_PROMPT,
    REPORT_ACTION_PROMPT, REPORT_FINALIZE_PROMPT,
)
from review_radar.llm import chat_simple
from review_radar.availability import COUNTRIES
from review_radar.config import MIN_REVIEW_LENGTH

logger = logging.getLogger("review_radar.tool_impl")


def _extract_json(text: str) -> dict | None:
    """从 LLM 返回的文本中提取 JSON，支持多种格式"""
    m = re.search(r'```json\s*(.*?)```', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    m = re.search(r'```\s*(.*?)```', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    first_brace = text.find('{')
    last_brace = text.rfind('}')
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        try:
            return json.loads(text[first_brace:last_brace + 1])
        except json.JSONDecodeError:
            pass

    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    return None


def _now() -> str:
    return datetime.now().strftime("%Y年%m月%d日")


def _country_name(code: str) -> str:
    return COUNTRIES.get(code, code)


def _platform_name(p: str) -> str:
    return "iOS (App Store)" if p == "app_store" else "Android (Google Play)"


# ── Tool 0: search_app ──────────────────────────────────────────

def tool_search_app(app_name: str, country: str = "us") -> dict:
    """搜索 App，返回 App 信息"""
    info = _search_app(app_name, country)
    return {
        "app_name": info.app_name,
        "app_store_id": info.app_store_id,
        "google_play_id": info.google_play_id,
        "app_name_en": info.app_name_en,
        "icon_url": info.icon_url,
        "category": info.category,
        "message": f"找到 App: {info.app_name_en or info.app_name}"
                   + (f" | App Store ID: {info.app_store_id}" if info.app_store_id else "")
                   + (f" | Google Play: {info.google_play_id}" if info.google_play_id else ""),
    }


# ── 评论质量过滤 ──────────────────────────────────────────────

_EMOJI_PATTERN = re.compile(
    r'^[\s\U0001F600-\U0001F64F\U0001F300-\U0001F5FF'
    r'\U0001F680-\U0001F6FF\U0001F900-\U0001F9FF'
    r'\U00002702-\U000027B0\U0000FE00-\U0000FE0F'
    r'\U0000200D\U00002640\U00002642\U00002600-\U000026FF'
    r'!?.,;:~*#@&%$^()+=\-_/\\|<>\[\]{}\'\"]+$'
)


def _is_low_quality(content: str) -> bool:
    """判断评论是否低质量（过短、纯符号/表情）"""
    stripped = content.strip()
    if len(stripped) < MIN_REVIEW_LENGTH:
        return True
    if _EMOJI_PATTERN.match(stripped):
        return True
    return False


# ── Tool 1: fetch_reviews ───────────────────────────────────────

def tool_fetch_reviews(
    app_store_id: str | None = None,
    google_play_id: str | None = None,
    count: int = 200,
    country: str = "us",
    platforms: list[str] | None = None,
    fetch_strategy: str = "mixed",
    on_progress=None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    """抓取评论，支持 mixed/recent/relevant 策略 + 日期过滤"""
    if not app_store_id and not google_play_id:
        return {"error": "至少需要提供 app_store_id 或 google_play_id"}

    use_ios = app_store_id and (not platforms or "app_store" in platforms)
    use_gplay = google_play_id and (not platforms or "google_play" in platforms)

    reviews: list = []

    if fetch_strategy == "mixed":
        # 50% 最新 + 50% 最相关，去重合并
        half = max(count // 2, 1)
        if use_ios:
            try:
                recent = fetch_app_store_reviews(app_store_id, country, half, sort="mostrecent", on_progress=on_progress, date_from=date_from, date_to=date_to)
                helpful = fetch_app_store_reviews(app_store_id, country, half, sort="mosthelpful", on_progress=on_progress, date_from=date_from, date_to=date_to)
                reviews.extend(recent)
                reviews.extend(helpful)
            except Exception as e:
                logger.warning("App Store 抓取失败: %s", e)
        if use_gplay:
            try:
                recent = fetch_google_play_reviews(google_play_id, half, country, sort="newest", on_progress=on_progress, date_from=date_from, date_to=date_to)
                relevant = fetch_google_play_reviews(google_play_id, half, country, sort="relevant", on_progress=on_progress, date_from=date_from, date_to=date_to)
                reviews.extend(recent)
                reviews.extend(relevant)
            except Exception as e:
                logger.warning("Google Play 抓取失败: %s", e)
    else:
        ios_sort = "mosthelpful" if fetch_strategy == "relevant" else "mostrecent"
        gplay_sort = "relevant" if fetch_strategy == "relevant" else "newest"
        if use_ios:
            try:
                ios_reviews = fetch_app_store_reviews(app_store_id, country, count, sort=ios_sort, on_progress=on_progress, date_from=date_from, date_to=date_to)
                reviews.extend(ios_reviews)
            except Exception as e:
                logger.warning("App Store 抓取失败: %s", e)
        if use_gplay:
            try:
                gplay_result = fetch_google_play_reviews(google_play_id, count, country, sort=gplay_sort, on_progress=on_progress, date_from=date_from, date_to=date_to)
                reviews.extend(gplay_result)
            except Exception as e:
                logger.warning("Google Play 抓取失败: %s", e)

    # 按 ID 去重（mixed 策略两次抓取可能重叠）
    seen_ids = set()
    deduped = []
    for r in reviews:
        if r.id not in seen_ids:
            seen_ids.add(r.id)
            deduped.append(r)
    reviews = deduped

    # 按日期倒序
    reviews.sort(key=lambda x: x.date, reverse=True)

    app_store_count = sum(1 for r in reviews if r.platform == "app_store")
    gplay_count = sum(1 for r in reviews if r.platform == "google_play")

    reviews_data = [
        {
            "id": r.id, "platform": r.platform, "rating": r.rating,
            "content": r.content, "date": r.date, "version": r.version,
            "title": r.title, "thumbs_up": r.thumbs_up, "country": r.country,
            "low_quality": _is_low_quality(r.content),
        }
        for r in reviews
    ]

    low_quality_count = sum(1 for r in reviews_data if r["low_quality"])

    return {
        "total_count": len(reviews),
        "app_store_count": app_store_count,
        "google_play_count": gplay_count,
        "low_quality_count": low_quality_count,
        "reviews": reviews_data,
        "message": (
            f"共抓取 {len(reviews)} 条评论"
            f"（App Store: {app_store_count}, Google Play: {gplay_count}"
            f"，低质量: {low_quality_count} 条已标记）"
        ),
    }


# ── Tool 2: analyze_batch ───────────────────────────────────────

def tool_analyze_batch(batch_index: int, reviews: list[dict], strategy_hint: str = "") -> dict:
    """分析一批评论（内部调用 LLM）"""
    slim_reviews = [
        {"id": r["id"], "content": r["content"], "rating": r.get("rating", 0),
         "platform": r.get("platform", ""), "version": r.get("version", ""),
         "date": r.get("date", ""), "country": r.get("country", "")}
        for r in reviews
    ]
    reviews_json = json.dumps(slim_reviews, ensure_ascii=False, indent=2)

    prompt = ANALYZE_BATCH_PROMPT.format(
        count=len(reviews),
        reviews_json=reviews_json,
        strategy_hint=f"\n**分析重点调整：** {strategy_hint}" if strategy_hint else "",
    )

    text = chat_simple(prompt, max_tokens=8000)
    result = _extract_json(text)

    # JSON 解析失败时，用精简指令重试一次
    if result is None:
        retry_prompt = (
            "你上一次的回复格式不正确，无法解析为 JSON。"
            "请只返回纯 JSON，不要任何解释文字、不要 markdown 代码块。"
        )
        text = chat_simple(retry_prompt, max_tokens=8000)
        result = _extract_json(text)

    if result is None:
        return {
            "batch_index": batch_index,
            "error": "分析结果解析失败",
            "raw_response": text[:500],
        }

    return {
        "batch_index": batch_index,
        "analyzed_count": len(reviews),
        "results": result.get("results", []),
        "batch_summary": result.get("batch_summary", {}),
        "message": f"批次 {batch_index} 分析完成，共 {len(reviews)} 条评论",
    }


# ── Tool 3: evaluate_coverage ───────────────────────────────────

def tool_evaluate_coverage(
    total_reviews: int,
    analyzed_batches: int,
    aggregated_results: dict,
) -> dict:
    """评估分析质量（内部调用 LLM）"""
    total_analyzed = aggregated_results.get("total_analyzed", 0)

    prompt = EVALUATE_PROMPT.format(
        total_reviews=total_reviews,
        analyzed_batches=analyzed_batches,
        total_analyzed=total_analyzed,
        aggregated_json=json.dumps(aggregated_results, ensure_ascii=False, indent=2),
    )

    text = chat_simple(prompt)
    result = _extract_json(text)

    if result is None:
        return {
            "is_complete": False,
            "coverage_score": total_analyzed / max(total_reviews, 1),
            "issues": [],
            "improvement_actions": [],
            "strategy_adjustments": [],
            "message": "评估结果解析失败，跳过本轮评估",
        }

    result["message"] = (
        f"评估完成 | 覆盖率: {result.get('coverage_score', 0):.0%} | "
        f"问题数: {len(result.get('issues', []))} | "
        f"{'通过 ✓' if result.get('is_complete') else '需要补充分析'}"
    )
    return result


# ── Tool 3.5: feature_analysis ────────────────────────────────

def tool_feature_analysis(app_name: str, feature_stats: dict) -> dict:
    """功能级满意度分析（内部调用 LLM）"""
    # 将 feature_stats 格式化为可读文本
    feature_data = json.dumps(feature_stats, ensure_ascii=False, indent=2)

    prompt = FEATURE_ANALYSIS_PROMPT.format(
        app_name=app_name,
        feature_data=feature_data,
    )

    text = chat_simple(prompt, max_tokens=4000)
    result = _extract_json(text)

    if result is None:
        return {
            "features": [],
            "summary": "功能分析结果解析失败",
            "message": "功能分析结果解析失败",
        }

    return {
        "features": result.get("features", []),
        "summary": result.get("summary", ""),
        "message": f"功能分析完成，识别到 {len(result.get('features', []))} 个功能模块",
    }


# ── Tool 3.6: semantic_dedup ─────────────────────────────────

def tool_semantic_dedup(keywords: list[dict], pain_points: list[dict]) -> dict:
    """语义去重：用 LLM 识别关键词和痛点中的同义词组"""
    keywords_json = json.dumps(
        [kw["word"] for kw in keywords[:30]],
        ensure_ascii=False,
    )
    pain_points_json = json.dumps(
        [pp["description"] for pp in pain_points[:15]],
        ensure_ascii=False,
    )

    prompt = SEMANTIC_DEDUP_PROMPT.format(
        keywords_json=keywords_json,
        pain_points_json=pain_points_json,
    )

    text = chat_simple(prompt, max_tokens=2000)
    result = _extract_json(text)

    if result is None:
        return {
            "keyword_groups": [],
            "pain_point_groups": [],
            "message": "语义去重结果解析失败，跳过去重",
        }

    return {
        "keyword_groups": result.get("keyword_groups", []),
        "pain_point_groups": result.get("pain_point_groups", []),
        "message": (
            f"语义去重完成：合并 {len(result.get('keyword_groups', []))} 组关键词，"
            f"{len(result.get('pain_point_groups', []))} 组痛点"
        ),
    }


# ── Tool 4: generate_report（多国家版）─────────────────────────

def tool_generate_report(
    app_name: str,
    analysis_data: dict,
    report_step: str,
    countries: list[str] | None = None,
    platforms: list[str] | None = None,
    sample_reviews: list[dict] | None = None,
    outline: str | None = None,
    chapters: list[str] | None = None,
    chapter_type: str | None = None,
    country_code: str | None = None,
) -> dict:
    """生成报告（多国家动态章节）"""
    countries = countries or ["us"]
    platforms = platforms or ["app_store", "google_play"]
    current_date = _now()

    if report_step == "executive_summary":
        return _generate_executive_summary(app_name, analysis_data, countries, platforms, current_date)
    elif report_step == "outline":
        return _generate_outline(app_name, analysis_data, countries, platforms, current_date)
    elif report_step == "overview":
        return _generate_overview(app_name, analysis_data, countries, platforms, current_date)
    elif report_step == "country":
        return _generate_country_chapter(
            app_name, analysis_data, country_code or "us",
            platforms, current_date, outline or "", sample_reviews or [],
        )
    elif report_step == "cross_country":
        return _generate_cross_country(app_name, analysis_data, countries, current_date)
    elif report_step == "action":
        return _generate_action(app_name, analysis_data, countries, current_date)
    elif report_step == "finalize":
        return _finalize_report(app_name, outline or "", chapters or [], current_date,
                                total_reviews=analysis_data.get("total_reviews", 0))
    else:
        return {"error": f"未知的 report_step: {report_step}"}


def _llm_chapter(prompt: str, message: str, max_tokens: int = 3000, key: str = "chapter_content") -> dict:
    """通用的 LLM 章节生成辅助函数"""
    text = chat_simple(prompt, max_tokens=max_tokens)
    return {key: text, "message": message}


def _generate_executive_summary(app_name, data, countries, platforms, current_date):
    global_data = data.get("global", {})
    summary_data = {
        "total_reviews": data.get("total_reviews", 0),
        "countries": len(countries),
        "platforms": len(platforms),
        "sentiment_distribution": global_data.get("sentiment_distribution", {}),
        "top_pain_points": global_data.get("top_pain_points", [])[:3],
        "top_keywords": global_data.get("top_keywords", [])[:5],
        "feature_summary": data.get("feature_summary", ""),
    }
    prompt = REPORT_EXECUTIVE_SUMMARY_PROMPT.format(
        app_name=app_name,
        current_date=current_date,
        global_summary=json.dumps(summary_data, ensure_ascii=False, indent=2),
    )
    return _llm_chapter(prompt, "执行摘要生成完成", max_tokens=500)


def _generate_outline(app_name, data, countries, platforms, current_date):
    countries_desc = "、".join(_country_name(c) for c in countries)
    platforms_desc = "、".join(_platform_name(p) for p in platforms)

    country_summaries = ""
    by_country = data.get("by_country", {})
    for code in countries:
        cd = by_country.get(code, {}).get("combined", {})
        country_summaries += f"\n**{_country_name(code)}：** 评论 {cd.get('review_count', 0)} 条，"
        sd = cd.get("sentiment_distribution", {})
        country_summaries += f"正面 {sd.get('positive', 0)}，负面 {sd.get('negative', 0)}，中性 {sd.get('neutral', 0)}\n"

    country_outline_items = ""
    for i, code in enumerate(countries, 2):
        country_outline_items += f"{i}. {_country_name(code)}市场分析\n"

    global_data = data.get("global", {})
    prompt = REPORT_OUTLINE_PROMPT.format(
        app_name=app_name,
        current_date=current_date,
        countries_desc=countries_desc,
        platforms_desc=platforms_desc,
        total_reviews=data.get("total_reviews", 0),
        sentiment_dist=json.dumps(global_data.get("sentiment_distribution", {}), ensure_ascii=False),
        category_dist=json.dumps(global_data.get("category_distribution", {}), ensure_ascii=False),
        pain_points=json.dumps(global_data.get("top_pain_points", [])[:10], ensure_ascii=False),
        keywords=json.dumps(global_data.get("top_keywords", [])[:20], ensure_ascii=False),
        country_summaries=country_summaries,
        country_outline_items=country_outline_items,
    )
    text = chat_simple(prompt)
    return {"outline": text, "message": "报告大纲生成完成"}


def _generate_overview(app_name, data, countries, platforms, current_date):
    countries_desc = "、".join(_country_name(c) for c in countries)
    platforms_desc = "、".join(_platform_name(p) for p in platforms)

    country_summaries = ""
    by_country = data.get("by_country", {})
    for code in countries:
        cd = by_country.get(code, {}).get("combined", {})
        country_summaries += f"\n### {_country_name(code)}\n"
        country_summaries += json.dumps(cd, ensure_ascii=False, indent=2)[:2000] + "\n"

    prompt = REPORT_OVERVIEW_PROMPT.format(
        app_name=app_name,
        current_date=current_date,
        countries_desc=countries_desc,
        platforms_desc=platforms_desc,
        global_data=json.dumps(data.get("global", {}), ensure_ascii=False, indent=2)[:4000],
        country_summaries=country_summaries[:6000],
    )
    return _llm_chapter(prompt, "总览章节生成完成")


def _generate_country_chapter(app_name, data, country_code, platforms, current_date, outline, sample_reviews):
    country_name = _country_name(country_code)
    by_country = data.get("by_country", {})
    country_data = by_country.get(country_code, {})

    platform_desc = "、".join(_platform_name(p) for p in platforms if country_data.get("by_platform", {}).get(p))
    if not platform_desc:
        platform_desc = "、".join(_platform_name(p) for p in platforms)

    # 筛选该国家的 sample reviews
    country_samples = [r for r in sample_reviews if r.get("country") == country_code][:20]
    sample_text = ""
    for r in country_samples:
        v = r.get("version") or "未知版本"
        d = r.get("date") or "未知日期"
        p = "iOS" if r.get("platform") == "app_store" else "Android"
        sample_text += f'- [{p}] ★{r.get("rating", 0)} > "{r.get("content", "")[:100]}" —— v{v}, {d}\n'

    prompt = REPORT_COUNTRY_CHAPTER_PROMPT.format(
        app_name=app_name,
        current_date=current_date,
        country_name=country_name,
        country_code=country_code,
        platform_desc=platform_desc,
        outline=outline[:2000],
        country_data=json.dumps(country_data, ensure_ascii=False, indent=2)[:6000],
        sample_reviews=sample_text[:3000] if sample_text else "无样本评论",
    )
    text = chat_simple(prompt, max_tokens=4000)
    return {"chapter_content": text, "message": f"{country_name}市场分析章节生成完成"}


def _generate_cross_country(app_name, data, countries, current_date):
    countries_desc = "、".join(_country_name(c) for c in countries)
    by_country = data.get("by_country", {})

    all_country_data = ""
    for code in countries:
        cd = by_country.get(code, {}).get("combined", {})
        all_country_data += f"\n### {_country_name(code)}\n"
        all_country_data += json.dumps(cd, ensure_ascii=False, indent=2)[:2000] + "\n"

    prompt = REPORT_CROSS_COUNTRY_PROMPT.format(
        app_name=app_name,
        current_date=current_date,
        countries_desc=countries_desc,
        all_country_data=all_country_data[:8000],
    )
    return _llm_chapter(prompt, "跨国对比章节生成完成")


def _generate_action(app_name, data, countries, current_date):
    country_summaries = ""
    by_country = data.get("by_country", {})
    for code in countries:
        cd = by_country.get(code, {}).get("combined", {})
        country_summaries += f"\n### {_country_name(code)}\n"
        pp = cd.get("top_pain_points", [])[:5]
        country_summaries += f"Top 痛点: {json.dumps(pp, ensure_ascii=False)}\n"

    prompt = REPORT_ACTION_PROMPT.format(
        app_name=app_name,
        current_date=current_date,
        global_data=json.dumps(data.get("global", {}), ensure_ascii=False, indent=2)[:4000],
        country_summaries=country_summaries[:4000],
    )
    return _llm_chapter(prompt, "行动建议章节生成完成")


def _finalize_report(app_name, outline, chapters, current_date, total_reviews=0):
    chapters_text = "\n\n---\n\n".join(
        f"### 章节 {i+1}\n{ch}" for i, ch in enumerate(chapters)
    )
    prompt = REPORT_FINALIZE_PROMPT.format(
        app_name=app_name,
        current_date=current_date,
        outline=outline,
        chapters=chapters_text,
        total_reviews=total_reviews,
    )
    return _llm_chapter(prompt, "报告格式化完成", max_tokens=8000, key="report")


# ── Tool Dispatcher ─────────────────────────────────────────────

def dispatch_tool(tool_name: str, tool_input: dict) -> dict:
    """根据 tool name 分发到对应实现"""
    if tool_name == "search_app":
        return tool_search_app(**tool_input)
    elif tool_name == "fetch_reviews":
        return tool_fetch_reviews(**tool_input)
    elif tool_name == "analyze_batch":
        return tool_analyze_batch(**tool_input)
    elif tool_name == "evaluate_coverage":
        return tool_evaluate_coverage(**tool_input)
    elif tool_name == "generate_report":
        return tool_generate_report(**tool_input)
    else:
        return {"error": f"未知的 Tool: {tool_name}"}
