"""Review Radar — Streamlit Web UI v2（4 步引导交互）"""

import streamlit as st
import plotly.graph_objects as go
import json
import time
import os
import hashlib
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from review_radar.scrapers import search_app_store, search_google_play
from review_radar.availability import check_availability_sync, COUNTRIES
from review_radar.agent import ReviewRadarAgent
from review_radar.report import save_report

# ── 文件缓存（防 session 丢失）──
CACHE_DIR = Path("/tmp/review_radar_cache")
CACHE_DIR.mkdir(exist_ok=True)


def _cache_key(app_name: str, countries: list, platforms: list, count: int) -> str:
    raw = f"{app_name}|{'_'.join(sorted(countries))}|{'_'.join(sorted(platforms))}|{count}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _save_cache(key: str, data: dict):
    path = CACHE_DIR / f"{key}.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _load_cache(key: str) -> dict | None:
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None

# ── 页面配置 ──
st.set_page_config(page_title="Review Radar", page_icon="📡", layout="centered")

# ── Notion 风格 CSS ──
st.markdown("""
<style>
    .stApp { background-color: #FFFFFF; color: #37352F; }
    .main-title { font-size: 42px; font-weight: 700; color: #37352F; margin-bottom: 4px; letter-spacing: -0.5px; }
    .sub-title { font-size: 18px; color: #787774; margin-bottom: 32px; font-weight: 400; }
    .section-title { font-size: 24px; font-weight: 600; color: #37352F; margin-top: 36px; margin-bottom: 16px; padding-bottom: 8px; border-bottom: 1px solid #E8E8E8; }
    .step-title { font-size: 20px; font-weight: 600; color: #37352F; margin-bottom: 12px; }
    .step-desc { font-size: 15px; color: #787774; margin-bottom: 20px; }
    .metric-card { padding: 24px 0; text-align: center; }
    .metric-value { font-size: 36px; font-weight: 700; color: #37352F; line-height: 1.2; }
    .metric-label { font-size: 14px; color: #787774; margin-top: 4px; }
    .app-card { display: flex; align-items: center; gap: 16px; padding: 20px; border: 1px solid #E8E8E8; border-radius: 8px; margin: 16px 0; }
    .app-icon { width: 64px; height: 64px; border-radius: 14px; }
    .app-info { flex: 1; }
    .app-name { font-size: 20px; font-weight: 600; color: #37352F; }
    .app-category { font-size: 14px; color: #787774; }
    .country-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin: 12px 0; }
    .country-item { padding: 8px 12px; border-radius: 6px; font-size: 14px; }
    .country-ok { background: #F0FFF0; color: #2E7D32; }
    .country-no { background: #FFF0F0; color: #C62828; text-decoration: line-through; }
    .phase-item { padding: 6px 0; font-size: 15px; color: #37352F; }
    .phase-done { color: #787774; }
    .phase-active { font-weight: 600; }
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    .stButton > button { background-color: #37352F; color: white; border: none; padding: 12px 32px; font-size: 16px; border-radius: 4px; font-weight: 500; }
    .stButton > button:hover { background-color: #555555; }
</style>
""", unsafe_allow_html=True)

# ── Session State 初始化 ──
defaults = {
    "step": 1,
    "app_name_input": "",
    "app_info_ios": None,
    "app_info_gplay": None,
    "icon_url": None,
    "confirmed_name": None,
    "app_store_id": None,
    "google_play_id": None,
    "country_availability": None,
    "selected_platforms": [],
    "selected_countries": [],
    "count": 100,
    "report": None,
    "aggregated": None,
    "analyzed_reviews": None,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── 标题 ──
st.markdown('<div class="main-title">Review Radar</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">输入 App 名字，自动分析用户评论，生成洞察报告</div>', unsafe_allow_html=True)

# ── 步骤指示器 ──
step = st.session_state.step
steps = ["搜索 App", "选择市场与国家", "高级选项", "分析"]
cols = st.columns(len(steps))
for i, (col, label) in enumerate(zip(cols, steps), 1):
    if i < step:
        col.markdown(f"<div style='text-align:center;color:#787774;'>✓ {label}</div>", unsafe_allow_html=True)
    elif i == step:
        col.markdown(f"<div style='text-align:center;font-weight:600;color:#37352F;'>● {label}</div>", unsafe_allow_html=True)
    else:
        col.markdown(f"<div style='text-align:center;color:#CFCFCF;'>○ {label}</div>", unsafe_allow_html=True)

st.markdown("---")


# ════════════════════════════════════════════════════════════════
# 辅助函数（必须在 Step 逻辑之前定义）
# ════════════════════════════════════════════════════════════════
def _render_charts(data: dict, title: str, analyzed_reviews: list[dict] | None = None):
    """渲染一组图表（情感饼图 + 分类柱状图 + 评分分布 + 版本趋势 + 痛点下钻 + 关键词）"""
    import pandas as pd

    sentiment = data.get("sentiment_distribution", {})
    categories = data.get("category_distribution", {})
    pain_points = data.get("top_pain_points", [])
    keywords = data.get("top_keywords", [])
    rating_dist = data.get("rating_distribution", {})
    version_trends = data.get("version_trends", {})
    feature_stats = data.get("feature_stats", {})
    mismatch_rate = data.get("mismatch_rate", 0)

    # ── 第一行：情感饼图 + 分类柱状图 ──
    if sentiment:
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown(f"**情感分布 — {title}**")
            colors_map = {"positive": "#4CAF50", "negative": "#E57373", "neutral": "#BDBDBD"}
            labels_cn = {"positive": "正面", "negative": "负面", "neutral": "中性"}
            fig = go.Figure(data=[go.Pie(
                labels=[labels_cn.get(k, k) for k in sentiment.keys()],
                values=list(sentiment.values()),
                marker=dict(colors=[colors_map.get(k, "#999") for k in sentiment.keys()]),
                hole=0.45, textinfo="label+percent", textfont=dict(size=14),
            )])
            fig.update_layout(showlegend=False, margin=dict(t=20, b=20, l=20, r=20), height=280,
                              paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True)

        with col_b:
            st.markdown(f"**评论分类 — {title}**")
            if categories:
                sorted_cats = sorted(categories.items(), key=lambda x: x[1], reverse=True)
                fig2 = go.Figure(data=[go.Bar(
                    x=[c[1] for c in sorted_cats], y=[c[0] for c in sorted_cats],
                    orientation='h', marker_color="#37352F",
                )])
                fig2.update_layout(margin=dict(t=20, b=20, l=20, r=20), height=280,
                                   paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                                   xaxis=dict(showgrid=False), yaxis=dict(showgrid=False, autorange="reversed"))
                st.plotly_chart(fig2, use_container_width=True)

    # ── 第二行：评分分布 + 版本趋势 ──
    col_c, col_d = st.columns(2)
    with col_c:
        if rating_dist and any(v > 0 for v in rating_dist.values()):
            st.markdown(f"**评分分布 — {title}**")
            stars = sorted(rating_dist.keys(), key=lambda x: int(x))
            colors_rating = {1: "#E57373", 2: "#FFB74D", 3: "#FFD54F", 4: "#AED581", 5: "#4CAF50"}
            fig3 = go.Figure(data=[go.Bar(
                x=[f"{s} 星" for s in stars],
                y=[rating_dist[s] for s in stars],
                marker_color=[colors_rating.get(int(s), "#999") for s in stars],
                text=[rating_dist[s] for s in stars],
                textposition="outside",
            )])
            fig3.update_layout(margin=dict(t=20, b=20, l=20, r=20), height=280,
                               paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                               xaxis=dict(showgrid=False), yaxis=dict(showgrid=False))
            st.plotly_chart(fig3, use_container_width=True)

    with col_d:
        if version_trends and len(version_trends) > 1:
            st.markdown(f"**版本评分趋势 — {title}**")
            # 过滤掉 unknown，按版本排序
            vt = {k: v for k, v in version_trends.items() if k != "unknown"}
            if vt:
                sorted_versions = sorted(vt.keys())
                fig4 = go.Figure()
                fig4.add_trace(go.Scatter(
                    x=sorted_versions,
                    y=[vt[v]["avg_rating"] for v in sorted_versions],
                    mode="lines+markers+text",
                    text=[f'{vt[v]["avg_rating"]:.1f}' for v in sorted_versions],
                    textposition="top center",
                    marker=dict(
                        size=[max(8, min(30, vt[v]["review_count"])) for v in sorted_versions],
                        color="#37352F",
                    ),
                    line=dict(color="#37352F", width=2),
                ))
                fig4.update_layout(margin=dict(t=20, b=20, l=20, r=20), height=280,
                                   paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                                   xaxis=dict(showgrid=False, title="版本"),
                                   yaxis=dict(showgrid=True, title="平均评分", range=[0.5, 5.5]))
                st.plotly_chart(fig4, use_container_width=True)

    # ── 时间趋势图（按周聚合情感变化）──
    if analyzed_reviews:
        # 过滤有日期的评论
        dated = [r for r in analyzed_reviews if r.get("date")]
        if len(dated) >= 5:
            from collections import defaultdict
            weekly = defaultdict(lambda: {"positive": 0, "negative": 0, "neutral": 0, "total": 0})
            for r in dated:
                try:
                    d = pd.to_datetime(r["date"])
                    week_key = d.strftime("%Y-%m-%d")  # 按天
                except Exception:
                    continue
                s = r.get("sentiment", "neutral")
                weekly[week_key][s] += 1
                weekly[week_key]["total"] += 1

            if len(weekly) >= 3:
                st.markdown(f"**情感时间趋势 — {title}**")
                sorted_weeks = sorted(weekly.keys())
                fig_time = go.Figure()
                fig_time.add_trace(go.Scatter(
                    x=sorted_weeks,
                    y=[weekly[w]["positive"] for w in sorted_weeks],
                    name="正面", mode="lines", line=dict(color="#4CAF50", width=2),
                    stackgroup="one",
                ))
                fig_time.add_trace(go.Scatter(
                    x=sorted_weeks,
                    y=[weekly[w]["neutral"] for w in sorted_weeks],
                    name="中性", mode="lines", line=dict(color="#BDBDBD", width=2),
                    stackgroup="one",
                ))
                fig_time.add_trace(go.Scatter(
                    x=sorted_weeks,
                    y=[weekly[w]["negative"] for w in sorted_weeks],
                    name="负面", mode="lines", line=dict(color="#E57373", width=2),
                    stackgroup="one",
                ))
                fig_time.update_layout(
                    margin=dict(t=20, b=20, l=20, r=20), height=280,
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    xaxis=dict(showgrid=False), yaxis=dict(showgrid=True, title="评论数"),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                )
                st.plotly_chart(fig_time, use_container_width=True)

    # ── 评分一致性指标 ──
    if mismatch_rate > 0:
        st.markdown(f"**评分一致性 — {title}**")
        mismatch_count = data.get("mismatch_count", 0)
        st.metric("评分与情感不一致率", f"{mismatch_rate:.1%}", delta=f"{mismatch_count} 条",
                  delta_color="inverse")
        st.caption("评分与评论内容情感不一致（如 5 星但内容负面），可能存在刷好评或误操作")

    # ── 痛点下钻 ──
    if pain_points:
        st.markdown(f"**Top 痛点 — {title}**")
        severity_cn = {"high": "🔴 高", "medium": "🟡 中", "low": "🟢 低"}
        for i, pp in enumerate(pain_points[:10], 1):
            desc = pp.get("description", "")
            count = pp.get("mention_count", 0)
            sev = severity_cn.get(pp.get("severity", "medium"), "中")
            with st.expander(f"{i}. {desc} — 提及 {count} 次 | {sev}"):
                if analyzed_reviews:
                    matching = [r for r in analyzed_reviews if r.get("pain_point") == desc][:5]
                    if matching:
                        for r in matching:
                            platform = "iOS" if r.get("platform") == "app_store" else "Android"
                            st.markdown(
                                f'> ★{r.get("rating", 0)} [{platform}] "{r.get("content", "")[:150]}" '
                                f'—— v{r.get("version", "?")}, {r.get("date", "?")}'
                            )
                    else:
                        st.caption("暂无匹配的原始评论")
                else:
                    st.caption("暂无原始评论数据")

    # ── 功能满意度热力图 ──
    if feature_stats and len(feature_stats) >= 2:
        st.markdown(f"**功能满意度 — {title}**")
        feat_data = []
        for fname, fdata in feature_stats.items():
            total = fdata.get("count", 0)
            neg = fdata.get("negative", 0)
            neg_rate = neg / max(total, 1)
            feat_data.append({"功能": fname, "提及次数": total,
                              "正面": fdata.get("positive", 0), "负面": neg,
                              "负面率": f"{neg_rate:.0%}"})
        feat_df = pd.DataFrame(feat_data).sort_values("负面率", ascending=False)
        st.dataframe(feat_df, use_container_width=True, hide_index=True)

    # ── 关键词 ──
    if keywords:
        st.markdown(f"**高频关键词 — {title}**")
        kw_data = [{"关键词": kw["word"], "频次": kw["count"]} for kw in keywords[:15]]
        st.dataframe(pd.DataFrame(kw_data), use_container_width=True, hide_index=True)


def _show_results():
    import pandas as pd

    report = st.session_state.report
    agg = st.session_state.aggregated or {}
    elapsed = st.session_state.get("elapsed", 0)
    app_name = st.session_state.confirmed_name or st.session_state.app_name_input
    countries = st.session_state.selected_countries or ["us"]
    analyzed_reviews = st.session_state.get("analyzed_reviews") or []

    st.markdown("---")
    st.markdown('<div class="section-title">数据概览</div>', unsafe_allow_html=True)

    global_data = agg.get("global", {})
    total = agg.get("total_reviews", 0)
    sentiment = global_data.get("sentiment_distribution", {})
    total_sent = sum(sentiment.values()) or 1
    pos_pct = sentiment.get("positive", 0) / total_sent * 100
    neg_pct = sentiment.get("negative", 0) / total_sent * 100

    # 从评分分布计算平均评分
    rd = global_data.get("rating_distribution", {})
    rd_total = sum(rd.values())
    avg_rating = sum(int(k) * v for k, v in rd.items()) / max(rd_total, 1) if rd_total else 0

    c1, c2, c3, c4, c5 = st.columns(5)
    for col, val, label in [
        (c1, str(total), "评论总数"),
        (c2, f"{avg_rating:.1f}" if avg_rating else "—", "平均评分"),
        (c3, f"{pos_pct:.0f}%", "正面评论"),
        (c4, f"{neg_pct:.0f}%", "负面评论"),
        (c5, f"{elapsed:.0f}s", "分析耗时"),
    ]:
        col.markdown(f'''
        <div class="metric-card">
            <div class="metric-value">{val}</div>
            <div class="metric-label">{label}</div>
        </div>
        ''', unsafe_allow_html=True)

    # 按国家 tab 展示图表
    if len(countries) > 1:
        country_labels = [COUNTRIES.get(c, c) for c in countries] + ["全局"]
        tabs = st.tabs(country_labels)

        for i, c_code in enumerate(countries):
            with tabs[i]:
                cd = agg.get("by_country", {}).get(c_code, {}).get("combined", {})
                _render_charts(cd, COUNTRIES.get(c_code, c_code), analyzed_reviews)

        with tabs[-1]:
            _render_charts(global_data, "全局", analyzed_reviews)
    else:
        _render_charts(global_data, "全局", analyzed_reviews)

    # ── 评论浏览器 ──
    if analyzed_reviews:
        st.markdown("---")
        st.markdown('<div class="section-title">评论浏览器</div>', unsafe_allow_html=True)

        # 筛选器
        fc1, fc2, fc3, fc4 = st.columns(4)
        with fc1:
            filter_sentiment = st.selectbox("情感", ["全部", "正面", "负面", "中性"], key="f_sent")
        with fc2:
            filter_rating = st.selectbox("评分", ["全部", "1 星", "2 星", "3 星", "4 星", "5 星"], key="f_rate")
        with fc3:
            plat_opts = ["全部"]
            if any(r.get("platform") == "app_store" for r in analyzed_reviews):
                plat_opts.append("iOS")
            if any(r.get("platform") == "google_play" for r in analyzed_reviews):
                plat_opts.append("Android")
            filter_platform = st.selectbox("平台", plat_opts, key="f_plat")
        with fc4:
            filter_keyword = st.text_input("关键词搜索", key="f_kw", placeholder="输入关键词...")

        # 应用筛选
        filtered = analyzed_reviews
        sent_map = {"正面": "positive", "负面": "negative", "中性": "neutral"}
        if filter_sentiment != "全部":
            s_val = sent_map.get(filter_sentiment)
            filtered = [r for r in filtered if r.get("sentiment") == s_val]
        if filter_rating != "全部":
            r_val = int(filter_rating[0])
            filtered = [r for r in filtered if r.get("rating") == r_val]
        if filter_platform == "iOS":
            filtered = [r for r in filtered if r.get("platform") == "app_store"]
        elif filter_platform == "Android":
            filtered = [r for r in filtered if r.get("platform") == "google_play"]
        if filter_keyword:
            kw_lower = filter_keyword.lower()
            filtered = [r for r in filtered if kw_lower in (r.get("content") or "").lower()]

        st.caption(f"共 {len(filtered)} 条评论（筛选自 {len(analyzed_reviews)} 条）")

        # 分页展示
        page_size = 20
        total_pages = max(1, (len(filtered) + page_size - 1) // page_size)
        if "review_page" not in st.session_state:
            st.session_state.review_page = 0
        page = st.session_state.review_page
        page = min(page, total_pages - 1)

        page_reviews = filtered[page * page_size : (page + 1) * page_size]

        for r in page_reviews:
            plat_label = "🍎" if r.get("platform") == "app_store" else "🤖"
            stars = "★" * r.get("rating", 0) + "☆" * (5 - r.get("rating", 0))
            sent_emoji = {"positive": "😊", "negative": "😞", "neutral": "😐"}.get(r.get("sentiment", ""), "")
            version = r.get("version", "")
            date = r.get("date", "")
            content = r.get("content", "")[:300]
            category = r.get("category", "")

            st.markdown(
                f'{plat_label} {stars} {sent_emoji} '
                f'<span style="color:#787774;font-size:12px;">v{version} | {date} | {category}</span>\n\n'
                f'> {content}',
                unsafe_allow_html=True,
            )

        # 分页控制
        if total_pages > 1:
            pc1, pc2, pc3 = st.columns([1, 2, 1])
            with pc1:
                if st.button("← 上一页", disabled=page == 0, key="prev_page"):
                    st.session_state.review_page = page - 1
                    st.rerun()
            with pc2:
                st.markdown(f'<div style="text-align:center;padding-top:8px;">{page + 1} / {total_pages}</div>',
                            unsafe_allow_html=True)
            with pc3:
                if st.button("下一页 →", disabled=page >= total_pages - 1, key="next_page"):
                    st.session_state.review_page = page + 1
                    st.rerun()

        # CSV 导出
        import io, csv
        csv_buf = io.StringIO()
        writer = csv.DictWriter(csv_buf, fieldnames=[
            "platform", "rating", "sentiment", "category", "content",
            "version", "date", "country", "pain_point", "feature", "keywords",
        ], extrasaction="ignore")
        writer.writeheader()
        for r in filtered:
            row = {**r, "keywords": ", ".join(r.get("keywords") or [])}
            writer.writerow(row)
        st.download_button(
            label=f"导出 CSV（{len(filtered)} 条）",
            data=csv_buf.getvalue(),
            file_name=f"{app_name}-评论数据-{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    # 完整报告
    st.markdown("---")
    st.markdown('<div class="section-title">完整报告</div>', unsafe_allow_html=True)
    st.markdown(report)

    # 下载 + 重新分析
    st.markdown("---")
    col_dl, col_new = st.columns(2)
    with col_dl:
        st.download_button(
            label="下载 Markdown 报告",
            data=report,
            file_name=f"{app_name}-评论洞察-{datetime.now().strftime('%Y%m%d')}.md",
            mime="text/markdown",
            use_container_width=True,
        )
    with col_new:
        if st.button("分析另一个 App", use_container_width=True):
            for k in defaults:
                st.session_state[k] = defaults[k]
            st.rerun()


# ════════════════════════════════════════════════════════════════
# Step 1: 搜索 App
# ════════════════════════════════════════════════════════════════
if step == 1:
    st.markdown('<div class="step-title">Step 1: 搜索 App</div>', unsafe_allow_html=True)
    st.markdown('<div class="step-desc">输入 App 名字，我们会自动搜索 App Store 和 Google Play</div>', unsafe_allow_html=True)

    app_name = st.text_input("App 名字", placeholder="例如：TikTok、微信、Notion", label_visibility="collapsed")
    search_btn = st.button("搜索", use_container_width=True, type="primary")

    if search_btn and app_name:
        with st.spinner("正在搜索 App Store 和 Google Play..."):
            ios_result = search_app_store(app_name)
            bundle_id = ios_result.get("bundle_id") if ios_result else None
            gplay_result = search_google_play(app_name, bundle_id=bundle_id)

        st.session_state.app_name_input = app_name
        st.session_state.app_info_ios = ios_result
        st.session_state.app_info_gplay = gplay_result

        if not ios_result and not gplay_result:
            st.error(f"未找到「{app_name}」，请检查名字后重试。")
        else:
            icon = (ios_result or {}).get("icon_url") or (gplay_result or {}).get("icon_url") or ""
            name = (ios_result or {}).get("app_name") or (gplay_result or {}).get("app_name") or app_name
            category = (ios_result or {}).get("category") or (gplay_result or {}).get("category") or ""

            st.session_state.icon_url = icon
            st.session_state.confirmed_name = name
            st.session_state.app_store_id = str(ios_result["app_id"]) if ios_result else None
            st.session_state.google_play_id = gplay_result["app_id"] if gplay_result else None
            st.session_state._search_done = True
            st.rerun()

    elif search_btn and not app_name:
        st.warning("请输入 App 名字")

    # 搜索完成后展示 App 卡片 + 确认按钮（持久化）
    if st.session_state.get("_search_done") and st.session_state.confirmed_name:
        ios_result = st.session_state.app_info_ios
        gplay_result = st.session_state.app_info_gplay
        icon = st.session_state.icon_url or ""
        name = st.session_state.confirmed_name
        category = (ios_result or {}).get("category") or (gplay_result or {}).get("category") or ""

        st.markdown(f'''
        <div class="app-card">
            <img class="app-icon" src="{icon}" alt="icon" onerror="this.style.display='none'"/>
            <div class="app-info">
                <div class="app-name">{name}</div>
                <div class="app-category">{category}</div>
                <div style="font-size:13px;color:#787774;margin-top:4px;">
                    {"✅ App Store" if ios_result else "❌ App Store"}
                    &nbsp;|&nbsp;
                    {"✅ Google Play" if gplay_result else "❌ Google Play"}
                </div>
            </div>
        </div>
        ''', unsafe_allow_html=True)

        if st.button("确认，下一步", use_container_width=True):
            st.session_state._search_done = False
            st.session_state.step = 2
            st.rerun()

# ════════════════════════════════════════════════════════════════
# Step 2: 选择市场 + 国家
# ════════════════════════════════════════════════════════════════
elif step == 2:
    st.markdown('<div class="step-title">Step 2: 选择市场与国家</div>', unsafe_allow_html=True)

    # 市场选择
    st.markdown("**选择分析平台：**")
    has_ios = st.session_state.app_store_id is not None
    has_gplay = st.session_state.google_play_id is not None

    col1, col2 = st.columns(2)
    with col1:
        sel_ios = st.checkbox("App Store (iOS)", value=has_ios, disabled=not has_ios)
    with col2:
        sel_gplay = st.checkbox("Google Play (Android)", value=has_gplay, disabled=not has_gplay)

    selected_platforms = []
    if sel_ios and has_ios:
        selected_platforms.append("app_store")
    if sel_gplay and has_gplay:
        selected_platforms.append("google_play")

    if not selected_platforms:
        st.warning("请至少选择一个平台")
        st.stop()

    st.session_state.selected_platforms = selected_platforms

    # 国家可用性检测
    st.markdown("**选择国家/地区：**")

    if st.session_state.country_availability is None:
        with st.spinner("正在检测各国家可用性（约 5-8 秒）..."):
            avail = check_availability_sync(
                st.session_state.app_store_id,
                st.session_state.google_play_id,
            )
            st.session_state.country_availability = avail

    avail = st.session_state.country_availability

    # 展示可用性网格
    available_countries = []
    grid_html = '<div class="country-grid">'
    for code, label in COUNTRIES.items():
        ca = avail.get(code, {})
        ios_ok = ca.get("app_store", False) and "app_store" in selected_platforms
        gplay_ok = ca.get("google_play", False) and "google_play" in selected_platforms
        any_ok = ios_ok or gplay_ok

        if any_ok:
            available_countries.append(code)
            platforms_str = ""
            if ios_ok and gplay_ok:
                platforms_str = "iOS + Android"
            elif ios_ok:
                platforms_str = "仅 iOS"
            else:
                platforms_str = "仅 Android"
            grid_html += f'<div class="country-item country-ok">{label} <small>({platforms_str})</small></div>'
        else:
            grid_html += f'<div class="country-item country-no">{label}</div>'
    grid_html += '</div>'
    st.markdown(grid_html, unsafe_allow_html=True)

    # 多选
    if available_countries:
        country_options = {COUNTRIES[c]: c for c in available_countries}
        selected_labels = st.multiselect(
            "选择要分析的国家（可多选）",
            options=list(country_options.keys()),
            default=[list(country_options.keys())[0]] if country_options else [],
        )
        selected_countries = [country_options[l] for l in selected_labels]
        st.session_state.selected_countries = selected_countries

        if selected_countries and st.button("下一步", use_container_width=True, type="primary"):
            st.session_state.step = 3
            st.rerun()
    else:
        st.error("该 App 在所有国家均不可用")

    if st.button("← 返回上一步"):
        st.session_state.step = 1
        st.session_state.country_availability = None
        st.rerun()

# ════════════════════════════════════════════════════════════════
# Step 3: 高级选项
# ════════════════════════════════════════════════════════════════
elif step == 3:
    st.markdown('<div class="step-title">Step 3: 高级选项</div>', unsafe_allow_html=True)

    name = st.session_state.confirmed_name or st.session_state.app_name_input
    plats = ", ".join("iOS" if p == "app_store" else "Android" for p in st.session_state.selected_platforms)
    ctrs = ", ".join(COUNTRIES.get(c, c) for c in st.session_state.selected_countries)
    st.markdown(f"**App:** {name} | **平台:** {plats} | **国家:** {ctrs}")

    if "count_input" not in st.session_state:
        st.session_state.count_input = 200
    if "confirm_start" not in st.session_state:
        st.session_state.confirm_start = False

    st.number_input(
        "每个平台每个国家的评论数（最少 1）",
        min_value=1, max_value=2000, step=10,
        key="count_input",
    )

    actual_count = st.session_state.count_input
    n_countries = len(st.session_state.selected_countries)
    n_platforms = len(st.session_state.selected_platforms)
    total_est = actual_count * n_countries * n_platforms
    st.caption(f"将抓取约 {actual_count} 条 × {n_countries} 个国家 × {n_platforms} 个平台 ≈ {total_est} 条评论")

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("← 返回", use_container_width=True):
            st.session_state.confirm_start = False
            st.session_state.step = 2
            st.rerun()
    with col_b:
        if not st.session_state.confirm_start:
            if st.button("开始分析", use_container_width=True, type="primary"):
                st.session_state.confirm_start = True
                st.rerun()
        else:
            st.warning(
                f"确认开始分析？\n\n"
                f"**App:** {name}\n\n"
                f"**平台:** {plats} | **国家:** {ctrs}\n\n"
                f"**评论数:** 每平台每国家 {actual_count} 条（预计总计约 {total_est} 条）\n\n"
                f"分析过程可能需要几分钟，请勿关闭页面。"
            )
            col_yes, col_no = st.columns(2)
            with col_yes:
                if st.button("确认开始", use_container_width=True, type="primary"):
                    st.session_state.count = actual_count
                    st.session_state.confirm_start = False
                    st.session_state.step = 4
                    st.rerun()
            with col_no:
                if st.button("取消", use_container_width=True):
                    st.session_state.confirm_start = False
                    st.rerun()

# ════════════════════════════════════════════════════════════════
# Step 4: 运行分析 + 展示结果
# ════════════════════════════════════════════════════════════════
elif step == 4:
    # 如果已有报告，直接展示
    if st.session_state.report:
        _show_results()
        st.stop()

    # 检查文件缓存（session 断连恢复时）
    app_name_for_cache = st.session_state.get("confirmed_name") or st.session_state.get("app_name_input") or ""
    countries_for_cache = st.session_state.get("selected_countries") or ["us"]
    platforms_for_cache = st.session_state.get("selected_platforms") or ["app_store"]
    count_for_cache = st.session_state.get("count", 200)

    if app_name_for_cache:
        ck = _cache_key(app_name_for_cache, countries_for_cache, platforms_for_cache, count_for_cache)
        cached = _load_cache(ck)
        if cached:
            st.session_state.report = cached.get("report", "")
            st.session_state.aggregated = cached.get("aggregated")
            st.session_state.analyzed_reviews = cached.get("analyzed_reviews")
            st.session_state.elapsed = cached.get("elapsed", 0)
            _show_results()
            st.stop()

    st.markdown('<div class="step-title">Step 4: 分析中</div>', unsafe_allow_html=True)

    # 用 st.status 展示实时进度（不触发 rerun）
    with st.status("正在分析...", expanded=True) as status_ui:
        log = st.empty()
        lines = []

        def _log(icon, text):
            lines.append(f"{icon} {text}")
            log.markdown("\n\n".join(lines[-20:]))

        def on_event(event_type, data):
            if event_type == "phase":
                phase = data.get("phase", "")
                _log("🔄", f"**{phase}**")
            elif event_type == "tool_call":
                detail = data.get("input_summary", "")
                _log("  ⚙️", detail)
            elif event_type == "tool_result":
                msg = data.get("message", "")
                if msg:
                    _log("  ✅", msg)
            elif event_type == "agent_done":
                _log("🎉", "**全部完成**")

        agent = ReviewRadarAgent(on_event=on_event)
        start_time = time.time()

        try:
            report = agent.run(
                app_name=app_name_for_cache,
                app_store_id=st.session_state.get("app_store_id"),
                google_play_id=st.session_state.get("google_play_id"),
                platforms=platforms_for_cache,
                countries=countries_for_cache,
                count_per_platform=count_for_cache,
            )
        except Exception as e:
            status_ui.update(label="分析失败", state="error", expanded=True)
            st.error(f"错误: {e}")
            if st.button("← 返回重试"):
                st.session_state.step = 3
                st.rerun()
            st.stop()

        elapsed = time.time() - start_time

        if not report:
            status_ui.update(label="未生成报告", state="error")
            st.stop()

        # 保存到 session
        st.session_state.report = report
        st.session_state.aggregated = agent.aggregated
        st.session_state.analyzed_reviews = agent.analyzed_reviews
        st.session_state.elapsed = elapsed
        save_report(report, app_name_for_cache)

        # 保存到文件缓存（防 session 丢失）
        if app_name_for_cache:
            ck = _cache_key(app_name_for_cache, countries_for_cache, platforms_for_cache, count_for_cache)
            _save_cache(ck, {
                "report": report,
                "aggregated": agent.aggregated,
                "analyzed_reviews": agent.analyzed_reviews,
                "elapsed": elapsed,
            })

        status_ui.update(label=f"分析完成（耗时 {elapsed:.0f} 秒）", state="complete", expanded=False)

    # 直接展示结果（不 rerun）
    _show_results()
