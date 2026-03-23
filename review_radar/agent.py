"""Agent 主循环 — Orchestrator 模式（v2 多国家多平台）
代码控制流程编排，LLM 负责分析和生成。
"""

import json
from typing import Callable

from review_radar.tool_impl import (
    tool_search_app, tool_fetch_reviews,
    tool_analyze_batch, tool_evaluate_coverage,
    tool_generate_report, tool_feature_analysis,
    tool_semantic_dedup,
)
from review_radar.availability import COUNTRIES
from review_radar.config import BATCH_SIZE, FETCH_MAX_WORKERS, ANALYZE_MAX_WORKERS, FETCH_DELAY


class ReviewRadarAgent:
    """评论洞察 Agent — Orchestrator 模式（多国家多平台）"""

    def __init__(self, on_event: Callable[[str, dict], None] | None = None):
        self.on_event = on_event or (lambda *_: None)
        self.report: str | None = None
        self.aggregated: dict | None = None
        self.analyzed_reviews: list[dict] = []  # 每条评论的分析结果 + 原始字段

    def run(
        self,
        app_name: str,
        app_store_id: str | None = None,
        google_play_id: str | None = None,
        platforms: list[str] | None = None,
        countries: list[str] | None = None,
        count_per_platform: int = 100,
        country: str = "us",  # 向后兼容旧调用
        fetch_strategy: str = "mixed",
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> str:
        """运行 Agent 全流程

        新版支持多国家多平台，同时向后兼容旧的单国家调用方式。
        """
        self.on_event("agent_start", {"app_name": app_name})

        # 向后兼容：旧调用方式
        if not platforms:
            platforms = []
            if app_store_id:
                platforms.append("app_store")
            if google_play_id:
                platforms.append("google_play")
            if not platforms:
                platforms = ["app_store", "google_play"]

        if not countries:
            countries = [country]

        # ── Phase 0: 搜索 App（如果没有传入 ID）──
        if not app_store_id and not google_play_id:
            self.on_event("phase", {"phase": "Phase 0: 识别 App", "phase_number": 0, "total_phases": 5})
            self.on_event("tool_call", {"tool": "search_app", "input_summary": f"搜索 App: {app_name}"})
            app_info = tool_search_app(app_name, countries[0])
            self.on_event("tool_result", {"tool": "search_app", "message": app_info.get("message", "")})

            app_store_id = app_info.get("app_store_id")
            google_play_id = app_info.get("google_play_id")

            if not app_store_id and not google_play_id:
                return f"未找到 App「{app_name}」的信息，请检查名字是否正确。"
        else:
            app_info = {"app_name_en": app_name}

        display_name = app_info.get("app_name_en") or app_name

        # ── Phase 1: 抓取评论（多国家多平台，并发）──
        self.on_event("phase", {"phase": "Phase 1: 抓取评论", "phase_number": 1, "total_phases": 5})
        all_reviews = []

        use_ios = "app_store" in platforms and app_store_id
        use_gplay = "google_play" in platforms and google_play_id

        def _fetch_country(c_code):
            import time
            time.sleep(FETCH_DELAY)  # 简单速率限制

            def _on_progress(fetched, total, platform, country):
                self.on_event("fetch_progress", {
                    "fetched": fetched, "total": total,
                    "platform": platform, "country": country,
                })

            return tool_fetch_reviews(
                app_store_id=app_store_id if use_ios else None,
                google_play_id=google_play_id if use_gplay else None,
                count=count_per_platform,
                country=c_code,
                platforms=platforms,
                fetch_strategy=fetch_strategy,
                on_progress=_on_progress,
                date_from=date_from,
                date_to=date_to,
            )

        if len(countries) > 1:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            self.on_event("tool_call", {
                "tool": "fetch_reviews",
                "input_summary": f"并发抓取 {len(countries)} 个国家评论 (count={count_per_platform})",
            })
            with ThreadPoolExecutor(max_workers=min(len(countries), FETCH_MAX_WORKERS)) as executor:
                futures = {executor.submit(_fetch_country, c): c for c in countries}
                for future in as_completed(futures):
                    c_code = futures[future]
                    c_name = COUNTRIES.get(c_code, c_code)
                    try:
                        fetch_result = future.result()
                        self.on_event("tool_result", {
                            "tool": "fetch_reviews",
                            "message": f"{c_name}: {fetch_result.get('message', '')}",
                        })
                        if not fetch_result.get("error"):
                            all_reviews.extend(fetch_result.get("reviews", []))
                    except Exception as e:
                        self.on_event("tool_result", {
                            "tool": "fetch_reviews",
                            "message": f"{c_name}: 抓取失败 — {e}",
                        })
        else:
            c_code = countries[0]
            c_name = COUNTRIES.get(c_code, c_code)
            self.on_event("tool_call", {
                "tool": "fetch_reviews",
                "input_summary": f"抓取 {c_name} 评论 (count={count_per_platform})",
            })
            fetch_result = _fetch_country(c_code)
            self.on_event("tool_result", {"tool": "fetch_reviews", "message": fetch_result.get("message", "")})
            if not fetch_result.get("error"):
                all_reviews.extend(fetch_result.get("reviews", []))

        if not all_reviews:
            return "未抓取到任何评论。"

        # 评论去重（ID 去重 + 内容去重）
        seen_ids = set()
        seen_contents = set()
        deduped = []
        for r in all_reviews:
            rid = r["id"]
            content_key = r.get("content", "").strip().lower()
            if rid not in seen_ids and content_key not in seen_contents:
                seen_ids.add(rid)
                if content_key:
                    seen_contents.add(content_key)
                deduped.append(r)
        all_reviews = deduped

        # 分离低质量评论（统计计入总数，但不送 LLM 分析）
        quality_reviews = [r for r in all_reviews if not r.get("low_quality")]
        low_quality_count = len(all_reviews) - len(quality_reviews)
        if low_quality_count > 0:
            self.on_event("tool_result", {
                "tool": "fetch_reviews",
                "message": f"过滤 {low_quality_count} 条低质量评论，{len(quality_reviews)} 条进入分析",
            })

        # 样本量检查
        if len(quality_reviews) < 100:
            self.on_event("warning", {
                "message": f"⚠️ 仅有 {len(quality_reviews)} 条有效评论，样本量较小，分析结论仅供参考"
            })

        # ── Phase 2: 分批分析（并发）──
        self.on_event("phase", {"phase": "Phase 2: 分批分析", "phase_number": 2, "total_phases": 5})
        batches = [quality_reviews[i:i + BATCH_SIZE] for i in range(0, len(quality_reviews), BATCH_SIZE)]
        all_batch_results = [None] * len(batches)

        if len(batches) > 1:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            self.on_event("tool_call", {
                "tool": "analyze_batch",
                "input_summary": f"并发分析 {len(batches)} 个批次（共 {len(quality_reviews)} 条）",
            })
            with ThreadPoolExecutor(max_workers=min(len(batches), ANALYZE_MAX_WORKERS)) as executor:
                futures = {executor.submit(tool_analyze_batch, i, batch): i for i, batch in enumerate(batches)}
                for future in as_completed(futures):
                    idx = futures[future]
                    try:
                        result = future.result()
                        self.on_event("tool_result", {"tool": "analyze_batch", "message": result.get("message", "")})
                        if not result.get("error"):
                            all_batch_results[idx] = result
                    except Exception as e:
                        self.on_event("tool_result", {"tool": "analyze_batch", "message": f"批次 {idx} 失败: {e}"})
            all_batch_results = [r for r in all_batch_results if r is not None]
        else:
            self.on_event("tool_call", {
                "tool": "analyze_batch",
                "input_summary": f"分析批次 0 ({len(batches[0])} 条)",
            })
            result = tool_analyze_batch(0, batches[0])
            self.on_event("tool_result", {"tool": "analyze_batch", "message": result.get("message", "")})
            if not result.get("error"):
                all_batch_results = [result]
            else:
                all_batch_results = []

        # 聚合结果（按国家×平台嵌套）
        aggregated = self._aggregate_results(all_batch_results, all_reviews, countries, platforms)
        self.aggregated = aggregated

        # 保存每条评论的分析结果（供 Web UI 筛选和下钻）
        review_map = {r["id"]: r for r in all_reviews}
        for batch in all_batch_results:
            for result in batch.get("results", []):
                rid = result.get("id", "")
                orig = review_map.get(rid, {})
                self.analyzed_reviews.append({
                    **orig,
                    "sentiment": result.get("sentiment"),
                    "sentiment_score": result.get("sentiment_score"),
                    "category": result.get("category"),
                    "keywords": result.get("keywords", []),
                    "pain_point": result.get("pain_point"),
                    "pain_severity": result.get("pain_severity"),
                    "feature": result.get("feature"),
                    "usage_scenario": result.get("usage_scenario"),
                    "rating_sentiment_match": result.get("rating_sentiment_match", True),
                })

        # ── Phase 2.5: 功能级分析 ──
        feature_data = aggregated.get("global", {}).get("feature_stats", {})
        if feature_data:
            self.on_event("phase", {"phase": "Phase 2.5: 功能级分析", "phase_number": 2, "total_phases": 5})
            self.on_event("tool_call", {"tool": "feature_analysis", "input_summary": "生成功能满意度分析"})
            feature_result = tool_feature_analysis(display_name, feature_data)
            self.on_event("tool_result", {"tool": "feature_analysis", "message": feature_result.get("message", "")})
            aggregated["feature_analysis"] = feature_result.get("features", [])
            aggregated["feature_summary"] = feature_result.get("summary", "")

        # ── Phase 3: 评估质量 ──
        self.on_event("phase", {"phase": "Phase 3: 评估质量", "phase_number": 3, "total_phases": 5})
        # 用 global 数据做评估
        global_agg = aggregated.get("global", {})
        global_agg["total_reviews"] = aggregated.get("total_reviews", 0)
        global_agg["total_analyzed"] = aggregated.get("total_analyzed", 0)

        for eval_round in range(3):
            self.on_event("tool_call", {
                "tool": "evaluate_coverage",
                "input_summary": f"评估质量 (第 {eval_round + 1} 轮)",
            })
            eval_result = tool_evaluate_coverage(
                total_reviews=len(all_reviews),
                analyzed_batches=len(all_batch_results),
                aggregated_results=global_agg,
            )
            self.on_event("tool_result", {"tool": "evaluate_coverage", "message": eval_result.get("message", "")})

            if eval_result.get("is_complete", True):
                break

            actions = eval_result.get("improvement_actions", [])
            if not actions:
                break

            global_agg = self._apply_improvements(global_agg, actions)
            aggregated["global"] = global_agg

        # ── Phase 3.5: 语义去重（跨语言同义词合并）──
        self.on_event("phase", {"phase": "Phase 3.5: 语义去重", "phase_number": 3, "total_phases": 5})
        global_keywords = global_agg.get("top_keywords", [])
        global_pain_points = global_agg.get("top_pain_points", [])

        if global_keywords or global_pain_points:
            self.on_event("tool_call", {"tool": "semantic_dedup", "input_summary": "识别同义词并合并"})
            dedup_result = tool_semantic_dedup(global_keywords, global_pain_points)
            self.on_event("tool_result", {"tool": "semantic_dedup", "message": dedup_result.get("message", "")})

            # 应用关键词合并
            kw_merge_map = {}  # synonym -> primary
            for group in dedup_result.get("keyword_groups", []):
                primary = group.get("primary", "")
                for syn in group.get("synonyms", []):
                    kw_merge_map[syn] = primary

            if kw_merge_map:
                global_agg = self._apply_semantic_dedup_keywords(global_agg, kw_merge_map)
                # 同步更新 analyzed_reviews 中的关键词
                for ar in self.analyzed_reviews:
                    ar["keywords"] = [kw_merge_map.get(kw, kw) for kw in (ar.get("keywords") or [])]

            # 应用痛点合并
            pp_merge_map = {}
            for group in dedup_result.get("pain_point_groups", []):
                primary = group.get("primary", "")
                for syn in group.get("synonyms", []):
                    pp_merge_map[syn] = primary

            if pp_merge_map:
                global_agg = self._apply_semantic_dedup_pain_points(global_agg, pp_merge_map)
                # 同步更新 analyzed_reviews 中的痛点
                for ar in self.analyzed_reviews:
                    pp = ar.get("pain_point")
                    if pp and pp in pp_merge_map:
                        ar["pain_point"] = pp_merge_map[pp]

            aggregated["global"] = global_agg

            # 对每个国家的数据也做同样的合并
            for c_code in countries:
                c_data = aggregated.get("by_country", {}).get(c_code, {}).get("combined", {})
                if c_data:
                    if kw_merge_map:
                        c_data = self._apply_semantic_dedup_keywords(c_data, kw_merge_map)
                    if pp_merge_map:
                        c_data = self._apply_semantic_dedup_pain_points(c_data, pp_merge_map)
                    aggregated["by_country"][c_code]["combined"] = c_data

        # ── Phase 4: 生成报告（多国家动态章节，并发优化）──
        self.on_event("phase", {"phase": "Phase 4: 生成报告", "phase_number": 4, "total_phases": 5})

        from concurrent.futures import ThreadPoolExecutor, as_completed

        # Wave 1: 执行摘要、大纲、总览 并发生成
        self.on_event("tool_call", {"tool": "generate_report", "input_summary": "并发生成执行摘要+大纲+总览"})

        def _gen_exec_summary():
            return tool_generate_report(
                app_name=display_name, analysis_data=aggregated,
                report_step="executive_summary", countries=countries, platforms=platforms,
            )

        def _gen_outline():
            return tool_generate_report(
                app_name=display_name, analysis_data=aggregated,
                report_step="outline", countries=countries, platforms=platforms,
            )

        def _gen_overview():
            return tool_generate_report(
                app_name=display_name, analysis_data=aggregated,
                report_step="overview", countries=countries, platforms=platforms,
            )

        with ThreadPoolExecutor(max_workers=3) as executor:
            f_exec = executor.submit(_gen_exec_summary)
            f_outline = executor.submit(_gen_outline)
            f_overview = executor.submit(_gen_overview)

        exec_summary_result = f_exec.result()
        outline_result = f_outline.result()
        overview_result = f_overview.result()
        outline = outline_result.get("outline", "")

        self.on_event("tool_result", {"tool": "generate_report", "message": "执行摘要+大纲+总览 生成完成"})

        # Wave 2: 各国家章节 + 跨国对比 + 行动建议 并发生成
        wave2_tasks = {}
        self.on_event("tool_call", {"tool": "generate_report", "input_summary": "并发生成国家章节+跨国对比+行动建议"})

        with ThreadPoolExecutor(max_workers=max(len(countries) + 2, 4)) as executor:
            # 各国家章节（依赖 outline，但彼此独立）
            for c_code in countries:
                def _gen_country(cc=c_code):
                    return tool_generate_report(
                        app_name=display_name, analysis_data=aggregated,
                        report_step="country", countries=countries, platforms=platforms,
                        country_code=cc, outline=outline, sample_reviews=all_reviews,
                    )
                wave2_tasks[executor.submit(_gen_country)] = ("country", c_code)

            # 跨国对比（多国家时）
            if len(countries) > 1:
                def _gen_cross():
                    return tool_generate_report(
                        app_name=display_name, analysis_data=aggregated,
                        report_step="cross_country", countries=countries, platforms=platforms,
                    )
                wave2_tasks[executor.submit(_gen_cross)] = ("cross_country", None)

            # 行动建议
            def _gen_action():
                return tool_generate_report(
                    app_name=display_name, analysis_data=aggregated,
                    report_step="action", countries=countries, platforms=platforms,
                )
            wave2_tasks[executor.submit(_gen_action)] = ("action", None)

        # 收集 Wave 2 结果，按类型归位
        country_chapters = {}  # c_code -> content
        cross_chapter = ""
        action_chapter = ""
        for future in wave2_tasks:
            task_type, task_key = wave2_tasks[future]
            result = future.result()
            if task_type == "country":
                country_chapters[task_key] = result.get("chapter_content", "")
            elif task_type == "cross_country":
                cross_chapter = result.get("chapter_content", "")
            elif task_type == "action":
                action_chapter = result.get("chapter_content", "")

        self.on_event("tool_result", {"tool": "generate_report", "message": "国家章节+跨国对比+行动建议 生成完成"})

        # 按正确顺序组装章节
        chapters = []
        chapters.append(exec_summary_result.get("chapter_content", ""))
        chapters.append(overview_result.get("chapter_content", ""))
        for c_code in countries:
            chapters.append(country_chapters.get(c_code, ""))
        if cross_chapter:
            chapters.append(cross_chapter)
        chapters.append(action_chapter)

        # Wave 3: 格式化（依赖所有章节）
        self.on_event("tool_call", {"tool": "generate_report", "input_summary": "格式化报告"})
        final = tool_generate_report(
            app_name=display_name, analysis_data=aggregated,
            report_step="finalize", outline=outline, chapters=chapters,
        )
        self.report = final.get("report", "")
        self.on_event("tool_result", {"tool": "generate_report", "message": final.get("message", "")})

        self.on_event("agent_done", {})
        return self.report

    def _aggregate_results(
        self, batch_results: list[dict], reviews: list[dict],
        countries: list[str], platforms: list[str],
    ) -> dict:
        """聚合所有批次结果，按国家×平台嵌套"""
        total_analyzed = sum(b.get("analyzed_count", 0) for b in batch_results)

        # 先把每条分析结果和原始评论关联上 country + platform
        review_map = {r["id"]: r for r in reviews}

        # 按 country × platform 分桶
        buckets: dict[str, dict[str, list]] = {}
        for c in countries:
            buckets[c] = {p: [] for p in platforms}

        for batch in batch_results:
            for result in batch.get("results", []):
                rid = result.get("id", "")
                orig = review_map.get(rid, {})
                rc = orig.get("country", countries[0])
                rp = orig.get("platform", "")
                if rc in buckets and rp in buckets.get(rc, {}):
                    buckets[rc][rp].append((result, orig))

        # 对每个桶做聚合
        by_country = {}
        for c in countries:
            by_platform = {}
            combined_results = []
            combined_reviews = []

            for p in platforms:
                items = buckets.get(c, {}).get(p, [])
                if not items:
                    continue
                p_results = [i[0] for i in items]
                p_reviews = [i[1] for i in items]
                by_platform[p] = self._aggregate_bucket(p_results, p_reviews)
                combined_results.extend(p_results)
                combined_reviews.extend(p_reviews)

            by_country[c] = {
                "by_platform": by_platform,
                "combined": self._aggregate_bucket(combined_results, combined_reviews) if combined_results else {},
            }

        # 全局聚合
        all_results = []
        all_orig = []
        for batch in batch_results:
            for result in batch.get("results", []):
                all_results.append(result)
                all_orig.append(review_map.get(result.get("id", ""), {}))

        global_agg = self._aggregate_bucket(all_results, all_orig)

        return {
            "total_reviews": len(reviews),
            "total_analyzed": total_analyzed,
            "by_country": by_country,
            "global": global_agg,
        }

    def _aggregate_bucket(self, results: list[dict], reviews: list[dict]) -> dict:
        """聚合单个桶（一组分析结果 + 原始评论）"""
        sentiment_dist = {"positive": 0, "negative": 0, "neutral": 0}
        category_dist = {}
        all_keywords: dict[str, int] = {}
        all_pain_points: dict[str, dict] = {}
        version_data: dict[str, list] = {}
        rating_dist = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        feature_stats: dict[str, dict] = {}
        mismatch_count = 0

        for i, r in enumerate(results):
            # sentiment_score 范围校验
            score = r.get("sentiment_score", 0)
            if isinstance(score, (int, float)):
                r["sentiment_score"] = max(-1.0, min(1.0, float(score)))

            s = r.get("sentiment", "neutral")
            sentiment_dist[s] = sentiment_dist.get(s, 0) + 1

            cat = r.get("category", "其他")
            category_dist[cat] = category_dist.get(cat, 0) + 1

            for kw in r.get("keywords", []):
                all_keywords[kw] = all_keywords.get(kw, 0) + 1

            pp = r.get("pain_point")
            if pp:
                if pp in all_pain_points:
                    all_pain_points[pp]["mention_count"] += 1
                else:
                    all_pain_points[pp] = {
                        "description": pp,
                        "mention_count": 1,
                        "severity": r.get("pain_severity", "medium"),
                    }

            # 功能归因聚合
            feature = r.get("feature")
            if feature:
                if feature not in feature_stats:
                    feature_stats[feature] = {
                        "count": 0, "positive": 0, "negative": 0, "neutral": 0,
                        "pain_points": [],
                    }
                feature_stats[feature]["count"] += 1
                feature_stats[feature][s] = feature_stats[feature].get(s, 0) + 1
                if pp:
                    feature_stats[feature]["pain_points"].append(pp)

            # 评分一致性
            if not r.get("rating_sentiment_match", True):
                mismatch_count += 1

        # 评分分布
        for rv in reviews:
            rating = rv.get("rating", 0)
            if 1 <= rating <= 5:
                rating_dist[rating] += 1
            v = rv.get("version") or "unknown"
            if v not in version_data:
                version_data[v] = []
            version_data[v].append(rating)

        version_trends = {}
        for v, ratings in version_data.items():
            if ratings:
                version_trends[v] = {
                    "avg_rating": round(sum(ratings) / len(ratings), 2),
                    "review_count": len(ratings),
                }

        top_keywords = sorted(
            [{"word": w, "count": c} for w, c in all_keywords.items()],
            key=lambda x: x["count"], reverse=True,
        )[:20]

        severity_weight = {"high": 3, "medium": 2, "low": 1}
        top_pain_points = sorted(
            list(all_pain_points.values()),
            key=lambda x: x["mention_count"] * severity_weight.get(x.get("severity", "medium"), 2),
            reverse=True,
        )[:10]

        return {
            "review_count": len(results),
            "sentiment_distribution": sentiment_dist,
            "category_distribution": category_dist,
            "top_keywords": top_keywords,
            "top_pain_points": top_pain_points,
            "version_trends": version_trends,
            "rating_distribution": rating_dist,
            "feature_stats": feature_stats,
            "mismatch_count": mismatch_count,
            "mismatch_rate": round(mismatch_count / max(len(results), 1), 3),
        }

    def _apply_improvements(self, aggregated: dict, actions: list[dict]) -> dict:
        """应用评估建议的改进"""
        for action in actions:
            act_type = action.get("action", "")
            details = action.get("details", {})

            if act_type == "merge_keywords":
                groups = details.get("groups", [])
                keywords = aggregated.get("top_keywords", [])
                for group in groups:
                    if len(group) < 2:
                        continue
                    primary = group[0]
                    total_count = 0
                    remaining = []
                    for kw in keywords:
                        if kw["word"] in group:
                            total_count += kw["count"]
                        else:
                            remaining.append(kw)
                    if total_count > 0:
                        remaining.append({"word": primary, "count": total_count})
                    keywords = sorted(remaining, key=lambda x: x["count"], reverse=True)
                aggregated["top_keywords"] = keywords[:20]

            elif act_type == "merge_pain_points":
                pain_points = aggregated.get("top_pain_points", [])
                seen = set()
                deduped = []
                for pp in pain_points:
                    desc = pp["description"]
                    if desc not in seen:
                        seen.add(desc)
                        deduped.append(pp)
                aggregated["top_pain_points"] = deduped[:10]

        return aggregated

    def _apply_semantic_dedup_keywords(self, aggregated: dict, merge_map: dict) -> dict:
        """应用语义去重：合并关键词同义词"""
        keywords = aggregated.get("top_keywords", [])
        merged: dict[str, int] = {}
        for kw in keywords:
            word = kw["word"]
            primary = merge_map.get(word, word)
            merged[primary] = merged.get(primary, 0) + kw["count"]
        aggregated["top_keywords"] = sorted(
            [{"word": w, "count": c} for w, c in merged.items()],
            key=lambda x: x["count"], reverse=True,
        )[:20]
        return aggregated

    def _apply_semantic_dedup_pain_points(self, aggregated: dict, merge_map: dict) -> dict:
        """应用语义去重：合并痛点同义表达"""
        pain_points = aggregated.get("top_pain_points", [])
        merged: dict[str, dict] = {}
        for pp in pain_points:
            desc = pp["description"]
            primary = merge_map.get(desc, desc)
            if primary in merged:
                merged[primary]["mention_count"] += pp["mention_count"]
                # 保留更高的严重程度
                sev_order = {"high": 3, "medium": 2, "low": 1}
                if sev_order.get(pp.get("severity", "medium"), 2) > sev_order.get(merged[primary].get("severity", "medium"), 2):
                    merged[primary]["severity"] = pp["severity"]
            else:
                merged[primary] = {
                    "description": primary,
                    "mention_count": pp["mention_count"],
                    "severity": pp.get("severity", "medium"),
                }
        severity_weight = {"high": 3, "medium": 2, "low": 1}
        aggregated["top_pain_points"] = sorted(
            list(merged.values()),
            key=lambda x: x["mention_count"] * severity_weight.get(x.get("severity", "medium"), 2),
            reverse=True,
        )[:10]
        return aggregated
