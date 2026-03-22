"""AppPulse — Streamlit Web UI v2（4 步引导交互）"""

import streamlit as st
import plotly.graph_objects as go
import json
import time
import os
import html as html_mod
import hashlib
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import review_radar.config  # noqa: F401 — 确保 load_dotenv 被调用

from review_radar.scrapers import search_app_store, search_google_play
from review_radar.availability import check_availability_sync, COUNTRIES
from review_radar.agent import ReviewRadarAgent
from review_radar.report import save_report, generate_html_report
from review_radar.providers import list_provider_names, get_provider, fetch_models
from review_radar.llm import set_runtime_config, check_health
from review_radar.history import save_analysis, list_analyses, get_analysis, delete_analysis, user_hash_from_key

# ── 文件缓存（防 session 丢失）──
from review_radar.config import CACHE_TTL, CACHE_DIR as _CACHE_DIR_CFG
CACHE_DIR = _CACHE_DIR_CFG or Path(tempfile.gettempdir()) / "review_radar_cache"
CACHE_DIR.mkdir(exist_ok=True)


def _cache_key(app_name: str, countries: list, platforms: list, count: int,
               date_from: str | None = None, date_to: str | None = None) -> str:
    raw = f"{app_name}|{'_'.join(sorted(countries))}|{'_'.join(sorted(platforms))}|{count}|{date_from or ''}|{date_to or ''}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _save_cache(key: str, data: dict):
    path = CACHE_DIR / f"{key}.json"
    data["_cache_timestamp"] = time.time()
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _load_cache(key: str) -> dict | None:
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            # TTL 检查
            ts = data.pop("_cache_timestamp", 0)
            if time.time() - ts > CACHE_TTL:
                return None
            return data
        except Exception:
            return None
    return None

# ── 页面配置 ──
st.set_page_config(page_title="AppPulse", page_icon="📊", layout="centered")

# ── AppPulse 品牌 CSS ──
st.markdown("""
<style>
    .stApp { background-color: #FFFFFF; color: #1E1E2E; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", sans-serif; }
    .main-title {
        font-size: 40px; font-weight: 800; letter-spacing: -0.5px; margin-bottom: 2px;
        background: linear-gradient(135deg, #4F46E5, #7C3AED);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
    }
    .sub-title { font-size: 16px; color: #6B7280; margin-bottom: 36px; font-weight: 400; letter-spacing: 0.3px; }
    .section-title { font-size: 22px; font-weight: 700; color: #1E1E2E; margin-top: 40px; margin-bottom: 18px; padding-bottom: 10px; border-bottom: 2px solid #E5E7EB; }
    .step-title { font-size: 20px; font-weight: 700; color: #1E1E2E; margin-bottom: 10px; }
    .step-desc { font-size: 14px; color: #6B7280; margin-bottom: 22px; line-height: 1.6; }
    .metric-card { padding: 20px 16px; text-align: center; background: #F8F7FF; border-radius: 12px; border: 1px solid #E5E7EB; }
    .metric-value { font-size: 32px; font-weight: 800; color: #4F46E5; line-height: 1.2; }
    .metric-label { font-size: 13px; color: #6B7280; margin-top: 6px; font-weight: 500; }
    .app-card {
        display: flex; align-items: center; gap: 16px; padding: 20px 24px;
        border: 1px solid #E5E7EB; border-radius: 12px; margin: 16px 0; background: #FFFFFF;
        box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.06);
        transition: box-shadow 0.2s ease;
    }
    .app-card:hover { box-shadow: 0 4px 12px rgba(79,70,229,0.08); }
    .app-icon { width: 64px; height: 64px; border-radius: 14px; }
    .app-info { flex: 1; }
    .app-name { font-size: 20px; font-weight: 700; color: #1E1E2E; }
    .app-category { font-size: 14px; color: #6B7280; }
    .country-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin: 12px 0; }
    .country-item { padding: 8px 12px; font-size: 14px; }
    .country-ok { background: #F0FDF4; color: #166534; border: 1px solid #BBF7D0; border-radius: 8px; }
    .country-no { background: #FEF2F2; color: #991B1B; text-decoration: line-through; border: 1px solid #FECACA; border-radius: 8px; }
    .phase-item { padding: 6px 0; font-size: 15px; color: #1E1E2E; }
    .phase-done { color: #6B7280; }
    .phase-active { font-weight: 600; }
    #MainMenu {visibility: hidden;} footer {visibility: hidden;}
    header [data-testid="stHeader"] {visibility: visible !important;}
    button[kind="header"] {visibility: visible !important;}
    .stButton > button {
        background: linear-gradient(135deg, #4F46E5, #7C3AED); color: white;
        border: none; padding: 10px 28px; font-size: 15px; border-radius: 8px; font-weight: 600;
        transition: all 0.2s ease; box-shadow: 0 1px 3px rgba(79,70,229,0.3);
    }
    .stButton > button:hover {
        background: linear-gradient(135deg, #4338CA, #6D28D9);
        box-shadow: 0 4px 12px rgba(79,70,229,0.35); transform: translateY(-1px);
    }
    .stButton > button:active { transform: translateY(0); }
    section[data-testid="stSidebar"] { background-color: #FAFAFE; border-right: 1px solid #E5E7EB; }
    section[data-testid="stSidebar"] .stMarkdown h3 { font-size: 15px; font-weight: 700; color: #1E1E2E; letter-spacing: 0.02em; }
    section[data-testid="stSidebar"] .stButton > button {
        background: #FFFFFF !important; color: #4F46E5 !important;
        border: 1px solid #4F46E5 !important; box-shadow: none;
        font-size: 13px; padding: 6px 12px;
    }
    section[data-testid="stSidebar"] .stButton > button:hover {
        background: #F8F7FF !important; transform: none; box-shadow: none;
    }
    hr { border: none; border-top: 1px solid #E5E7EB; margin: 24px 0; }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] { border-radius: 8px 8px 0 0; font-weight: 600; font-size: 14px; }
    .stDownloadButton > button {
        background: #FFFFFF !important; color: #4F46E5 !important;
        border: 1px solid #4F46E5 !important; border-radius: 8px; font-weight: 600;
    }
    .stDownloadButton > button:hover { background: #F8F7FF !important; }
    .streamlit-expanderHeader { font-weight: 600; font-size: 14px; }
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
    "count": 200,
    "fetch_strategy": "mixed",
    "date_from": None,
    "date_to": None,
    "report": None,
    "aggregated": None,
    "analyzed_reviews": None,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── 侧边栏：LLM 配置 ──
with st.sidebar:
    st.markdown("### ⚙️ LLM 配置")

    # localStorage 读写（通过 streamlit query params 模拟持久化）
    if "llm_provider" not in st.session_state:
        st.session_state["llm_provider"] = "MiniMax"
    if "llm_api_key" not in st.session_state:
        st.session_state["llm_api_key"] = ""
    if "llm_model" not in st.session_state:
        st.session_state["llm_model"] = ""
    if "llm_base_url" not in st.session_state:
        st.session_state["llm_base_url"] = ""
    if "llm_health_ok" not in st.session_state:
        st.session_state["llm_health_ok"] = None
    if "llm_models_list" not in st.session_state:
        st.session_state["llm_models_list"] = []

    provider_names = list_provider_names()
    selected_provider = st.selectbox(
        "供应商",
        provider_names,
        index=provider_names.index(st.session_state["llm_provider"])
        if st.session_state["llm_provider"] in provider_names else 0,
        key="_llm_provider_select",
    )

    # 供应商切换时更新 base_url 并加载预设模型
    provider_cfg = get_provider(selected_provider)
    if selected_provider != st.session_state.get("llm_provider"):
        st.session_state["llm_provider"] = selected_provider
        st.session_state["llm_base_url"] = provider_cfg["base_url"]
        st.session_state["llm_model"] = provider_cfg["default_model"]
        st.session_state["llm_health_ok"] = None
        st.session_state["llm_models_list"] = provider_cfg.get("known_models", [])

    # 自定义供应商显示 base_url 输入框
    if selected_provider == "自定义":
        base_url = st.text_input("Base URL", value=st.session_state.get("llm_base_url", ""), key="_llm_base_url")
        st.session_state["llm_base_url"] = base_url
    else:
        base_url = provider_cfg["base_url"]
        st.session_state["llm_base_url"] = base_url
        st.caption(f"Base URL: `{base_url}`")

    api_key = st.text_input("API Key", value=st.session_state.get("llm_api_key", ""), type="password", key="_llm_api_key")
    st.session_state["llm_api_key"] = api_key

    # 获取模型列表按钮
    col_fetch, col_health = st.columns(2)
    with col_fetch:
        if st.button("获取模型", disabled=not api_key or not base_url):
            with st.spinner("获取中..."):
                models, err = fetch_models(api_key, base_url)
                st.session_state["llm_models_list"] = models
                if models:
                    st.success(f"找到 {len(models)} 个模型")
                else:
                    st.warning(f"未获取到模型列表：{err}")

    with col_health:
        if st.button("测试连接", disabled=not api_key or not base_url):
            with st.spinner("测试中..."):
                model_to_test = st.session_state.get("llm_model", "") or provider_cfg["default_model"]
                ok, msg = check_health(api_key, base_url, model_to_test)
                st.session_state["llm_health_ok"] = ok
                if ok:
                    st.success(msg)
                else:
                    st.error(msg)

    # 模型选择
    models_list = st.session_state.get("llm_models_list", [])
    current_model = st.session_state.get("llm_model", "") or provider_cfg["default_model"]
    if models_list:
        default_idx = models_list.index(current_model) if current_model in models_list else 0
        selected_model = st.selectbox("模型", models_list, index=default_idx, key="_llm_model_select")
    else:
        selected_model = st.text_input("模型", value=current_model, key="_llm_model_input")
    st.session_state["llm_model"] = selected_model

    # 应用配置到运行时
    if api_key and base_url and selected_model:
        set_runtime_config(api_key=api_key, base_url=base_url, model=selected_model)
        st.session_state["user_hash"] = user_hash_from_key(api_key)

    # 健康状态指示
    health = st.session_state.get("llm_health_ok")
    if health is True:
        st.caption("🟢 LLM 连接正常")
    elif health is False:
        st.caption("🔴 LLM 连接失败，请检查配置")
    elif not api_key:
        st.caption("⚠️ 请输入 API Key")

    st.markdown("---")
    st.caption("配置仅在当前会话有效。")

    # ── 历史记录 ──
    st.markdown("### 📋 分析历史")
    uh = st.session_state.get("user_hash", "")
    if uh:
        history = list_analyses(user_hash=uh, limit=20)
    else:
        history = []
    if history:
        hist_search = st.text_input("搜索历史", placeholder="输入 App 名称...", key="hist_search", label_visibility="collapsed")
        if hist_search:
            history = [h for h in history if hist_search.lower() in h["app_name"].lower()]
        for h in history:
            ts = datetime.fromtimestamp(h["timestamp"], tz=timezone(timedelta(hours=8))).strftime("%m-%d %H:%M")
            label = f'{h["app_name"]} ({ts}, {h["review_count"]} 条)'
            col_load, col_del = st.columns([4, 1])
            with col_load:
                if st.button(label, key=f"hist_{h['id']}"):
                    record = get_analysis(user_hash=uh, analysis_id=h["id"])
                    if record:
                        st.session_state.report = record.get("report_text", "")
                        st.session_state.aggregated = record.get("aggregated")
                        st.session_state.analyzed_reviews = record.get("analyzed_reviews")
                        st.session_state.confirmed_name = record.get("app_name", "")
                        st.session_state.elapsed = 0
                        st.session_state.step = 4
                        st.rerun()
            with col_del:
                if st.button("🗑", key=f"del_{h['id']}", help="删除此记录"):
                    delete_analysis(user_hash=uh, analysis_id=h["id"])
                    st.rerun()
    else:
        st.caption("暂无历史记录")

# ── 标题 ──
st.markdown('<div class="main-title">AppPulse</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">感知每一条用户心声</div>', unsafe_allow_html=True)

# ── 步骤指示器 ──
step = st.session_state.step
steps = ["搜索 App", "选择市场与国家", "高级选项", "分析"]
cols = st.columns(len(steps))
for i, (col, label) in enumerate(zip(cols, steps), 1):
    if i < step:
        col.markdown(f"<div style='text-align:center;color:#10B981;font-weight:600;font-size:14px;'>✓ {label}</div>", unsafe_allow_html=True)
    elif i == step:
        col.markdown(f"<div style='text-align:center;font-weight:700;color:#4F46E5;font-size:14px;padding:4px 0;border-bottom:2px solid #4F46E5;'>● {label}</div>", unsafe_allow_html=True)
    else:
        col.markdown(f"<div style='text-align:center;color:#D1D5DB;font-size:14px;'>○ {label}</div>", unsafe_allow_html=True)

st.markdown("---")


# ════════════════════════════════════════════════════════════════
# 辅助函数（必须在 Step 逻辑之前定义）
# ════════════════════════════════════════════════════════════════
def _render_sentiment_pie(sentiment: dict, title: str):
    """情感分布饼图"""
    colors_map = {"positive": "#4F46E5", "negative": "#F59E0B", "neutral": "#D1D5DB"}
    labels_cn = {"positive": "正面", "negative": "负面", "neutral": "中性"}
    fig = go.Figure(data=[go.Pie(
        labels=[labels_cn.get(k, k) for k in sentiment.keys()],
        values=list(sentiment.values()),
        marker=dict(colors=[colors_map.get(k, "#999") for k in sentiment.keys()]),
        hole=0.45, textinfo="label+percent", textfont=dict(size=14),
    )])
    fig.update_layout(showlegend=False, margin=dict(t=20, b=20, l=20, r=20), height=280,
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font=dict(family="-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif", color="#1E1E2E"))
    st.plotly_chart(fig, use_container_width=True)


def _render_category_bar(categories: dict, title: str):
    """评论分类柱状图"""
    sorted_cats = sorted(categories.items(), key=lambda x: x[1], reverse=True)
    fig2 = go.Figure(data=[go.Bar(
        x=[c[1] for c in sorted_cats], y=[c[0] for c in sorted_cats],
        orientation='h', marker_color="#4F46E5",
    )])
    fig2.update_layout(margin=dict(t=20, b=20, l=20, r=20), height=280,
                       paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                       xaxis=dict(showgrid=False), yaxis=dict(showgrid=False, autorange="reversed"),
                       font=dict(family="-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif", color="#1E1E2E"))
    st.plotly_chart(fig2, use_container_width=True)


def _render_rating_dist(rating_dist: dict, title: str):
    """评分分布柱状图"""
    stars = sorted(rating_dist.keys(), key=lambda x: int(x))
    colors_rating = {1: "#EF4444", 2: "#F59E0B", 3: "#FBBF24", 4: "#34D399", 5: "#4F46E5"}
    fig3 = go.Figure(data=[go.Bar(
        x=[f"{s} 星" for s in stars],
        y=[rating_dist[s] for s in stars],
        marker_color=[colors_rating.get(int(s), "#999") for s in stars],
        text=[rating_dist[s] for s in stars],
        textposition="outside",
    )])
    fig3.update_layout(margin=dict(t=20, b=20, l=20, r=20), height=280,
                       paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                       xaxis=dict(showgrid=False), yaxis=dict(showgrid=False),
                       font=dict(family="-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif", color="#1E1E2E"))
    st.plotly_chart(fig3, use_container_width=True)


def _render_version_trend(version_trends: dict, title: str):
    """版本评分趋势图"""
    vt = {k: v for k, v in version_trends.items() if k != "unknown"}
    if not vt:
        st.info("📊 无有效版本数据，无法生成版本趋势图。")
        return

    def _version_sort_key(v):
        parts = []
        for x in v.split('.'):
            try: parts.append(int(x))
            except ValueError: parts.append(0)
        return parts

    sorted_versions = sorted(vt.keys(), key=_version_sort_key)
    fig4 = go.Figure()
    fig4.add_trace(go.Scatter(
        x=sorted_versions,
        y=[vt[v]["avg_rating"] for v in sorted_versions],
        mode="lines+markers+text",
        text=[f'{vt[v]["avg_rating"]:.1f}' for v in sorted_versions],
        textposition="top center",
        marker=dict(
            size=[max(8, min(30, vt[v]["review_count"])) for v in sorted_versions],
            color="#4F46E5",
        ),
        line=dict(color="#4F46E5", width=2),
    ))
    fig4.update_layout(margin=dict(t=20, b=20, l=20, r=20), height=280,
                       paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                       xaxis=dict(showgrid=False, title="版本"),
                       yaxis=dict(showgrid=True, title="平均评分", range=[0.5, 5.5]),
                       font=dict(family="-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif", color="#1E1E2E"))
    st.plotly_chart(fig4, use_container_width=True)


def _render_time_trend(analyzed_reviews: list[dict], title: str):
    """情感时间趋势图（按天聚合）"""
    import pandas as pd
    from collections import defaultdict

    dated = [r for r in analyzed_reviews if r.get("date")]
    if len(dated) < 5:
        st.info(f"📊 有日期的评论不足 5 条（当前 {len(dated)} 条），无法生成时间趋势图。建议增加抓取数量。")
        return

    weekly = defaultdict(lambda: {"positive": 0, "negative": 0, "neutral": 0, "total": 0})
    for r in dated:
        try:
            d = pd.to_datetime(r["date"])
            week_key = d.strftime("%Y-%m-%d")
        except Exception:
            continue
        s = r.get("sentiment", "neutral")
        weekly[week_key][s] += 1
        weekly[week_key]["total"] += 1

    if len(weekly) < 3:
        st.info(f"📊 评论时间跨度不足 3 天（当前 {len(weekly)} 天），无法生成时间趋势图。")
        return

    st.markdown(f"**情感时间趋势 — {title}**")
    sorted_weeks = sorted(weekly.keys())
    fig_time = go.Figure()
    fig_time.add_trace(go.Scatter(
        x=sorted_weeks, y=[weekly[w]["positive"] for w in sorted_weeks],
        name="正面", mode="lines", line=dict(color="#4F46E5", width=2), stackgroup="one",
    ))
    fig_time.add_trace(go.Scatter(
        x=sorted_weeks, y=[weekly[w]["neutral"] for w in sorted_weeks],
        name="中性", mode="lines", line=dict(color="#D1D5DB", width=2), stackgroup="one",
    ))
    fig_time.add_trace(go.Scatter(
        x=sorted_weeks, y=[weekly[w]["negative"] for w in sorted_weeks],
        name="负面", mode="lines", line=dict(color="#F59E0B", width=2), stackgroup="one",
    ))
    fig_time.update_layout(
        margin=dict(t=20, b=20, l=20, r=20), height=280,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(showgrid=False), yaxis=dict(showgrid=True, title="评论数"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        font=dict(family="-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif", color="#1E1E2E"),
    )
    st.plotly_chart(fig_time, use_container_width=True)


def _render_mismatch_metric(data: dict, title: str):
    """评分一致性指标"""
    mismatch_rate = data.get("mismatch_rate", 0)
    if mismatch_rate <= 0:
        return
    mismatch_count = data.get("mismatch_count", 0)
    st.markdown(f"**评分一致性 — {title}**")
    st.metric("评分与情感不一致率", f"{mismatch_rate:.1%}", delta=f"{mismatch_count} 条", delta_color="inverse")
    st.caption("评分与评论内容情感不一致（如 5 星但内容负面），可能存在刷好评或误操作")


def _render_pain_points(pain_points: list, title: str, analyzed_reviews: list[dict] | None):
    """痛点下钻"""
    if not pain_points:
        return
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
                            f'> ★{r.get("rating", 0)} [{platform}] "{html_mod.escape(r.get("content", "")[:150])}" '
                            f'—— v{html_mod.escape(str(r.get("version", "?")))}, {r.get("date", "?")}'
                        )
                else:
                    st.caption("该痛点暂无匹配的原始评论，可能是聚合分析中识别的问题")
            else:
                st.caption("历史记录中未保存原始评论数据，重新分析可查看详情")


def _render_feature_table(feature_stats: dict, title: str):
    """功能满意度表格"""
    import pandas as pd
    if not feature_stats or len(feature_stats) < 2:
        st.info("📊 识别到的功能模块不足 2 个，无法生成功能满意度表格。")
        return
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


def _render_keywords_table(keywords: list, title: str):
    """高频关键词表格"""
    import pandas as pd
    if not keywords:
        return
    st.markdown(f"**高频关键词 — {title}**")
    kw_data = [{"关键词": kw["word"], "频次": kw["count"]} for kw in keywords[:15]]
    st.dataframe(pd.DataFrame(kw_data), use_container_width=True, hide_index=True)


def _render_charts(data: dict, title: str, analyzed_reviews: list[dict] | None = None):
    """渲染一组图表（调度函数）"""
    sentiment = data.get("sentiment_distribution", {})
    categories = data.get("category_distribution", {})
    pain_points = data.get("top_pain_points", [])
    keywords = data.get("top_keywords", [])
    rating_dist = data.get("rating_distribution", {})
    version_trends = data.get("version_trends", {})
    feature_stats = data.get("feature_stats", {})

    # 第一行：情感饼图 + 分类柱状图
    if sentiment:
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown(f"**情感分布 — {title}**")
            _render_sentiment_pie(sentiment, title)
        with col_b:
            st.markdown(f"**评论分类 — {title}**")
            if categories:
                _render_category_bar(categories, title)

    # 第二行：评分分布 + 版本趋势
    col_c, col_d = st.columns(2)
    with col_c:
        if rating_dist and any(v > 0 for v in rating_dist.values()):
            st.markdown(f"**评分分布 — {title}**")
            _render_rating_dist(rating_dist, title)
    with col_d:
        if version_trends and len(version_trends) > 1:
            st.markdown(f"**版本评分趋势 — {title}**")
            _render_version_trend(version_trends, title)

    # 时间趋势
    if analyzed_reviews:
        _render_time_trend(analyzed_reviews, title)

    # 评分一致性
    _render_mismatch_metric(data, title)

    # 痛点下钻
    _render_pain_points(pain_points, title, analyzed_reviews)

    # 功能满意度
    _render_feature_table(feature_stats, title)

    # 关键词
    _render_keywords_table(keywords, title)


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

    # 样本量警告
    if total < 500:
        st.warning(f"⚠️ 当前样本量 {total} 条，统计置信度有限。建议抓取 ≥500 条评论以获得更可靠的分析结论。")

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
            plat_label = "🍎 App Store" if r.get("platform") == "app_store" else "🤖 Google Play"
            stars = "★" * r.get("rating", 0) + "☆" * (5 - r.get("rating", 0))
            sent_emoji = {"positive": "😊 正面", "negative": "😞 负面", "neutral": "😐 中性"}.get(r.get("sentiment", ""), "")
            version = r.get("version", "")
            date = r.get("date", "")
            content = r.get("content", "")[:300]
            category = r.get("category", "")

            st.markdown(
                f'{plat_label} {stars} {sent_emoji} '
                f'<span style="color:#6B7280;font-size:12px;">v{html_mod.escape(str(version))} | {html_mod.escape(date)} | {html_mod.escape(category)}</span>\n\n'
                f'> {html_mod.escape(content)}',
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
    if total < 500:
        st.caption(f"📊 本报告基于 {total} 条评论样本，统计置信度有限，结论仅供参考。")
    st.markdown(report)

    # 下载 + 重新分析
    st.markdown("---")
    col_dl_md, col_dl_html, col_new = st.columns(3)
    with col_dl_md:
        st.download_button(
            label="下载 Markdown 报告",
            data=report,
            file_name=f"{app_name}-评论洞察-{datetime.now().strftime('%Y%m%d')}.md",
            mime="text/markdown",
            use_container_width=True,
        )
    with col_dl_html:
        html_report = generate_html_report(report, app_name)
        st.download_button(
            label="下载 HTML 报告",
            data=html_report,
            file_name=f"{app_name}-评论洞察-{datetime.now().strftime('%Y%m%d')}.html",
            mime="text/html",
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
            gplay_result = search_google_play(
                app_name, bundle_id=bundle_id,
                app_store_name=ios_result.get("app_name") if ios_result else None,
                app_store_developer=ios_result.get("developer") if ios_result else None,
            )

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
            <img class="app-icon" src="{html_mod.escape(icon)}" alt="icon" onerror="this.style.display='none'"/>
            <div class="app-info">
                <div class="app-name">{html_mod.escape(name)}</div>
                <div class="app-category">{html_mod.escape(category)}</div>
                <div style="font-size:13px;color:#6B7280;margin-top:4px;">
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

    # 国家可用性检测（App 变更时才重新检测）
    st.markdown("**选择国家/地区：**")

    _avail_key = f"{st.session_state.app_store_id}|{st.session_state.google_play_id}"
    if st.session_state.country_availability is None or st.session_state.get("_avail_app_key") != _avail_key:
        with st.spinner("正在检测各国家可用性（约 5-8 秒）..."):
            avail = check_availability_sync(
                st.session_state.app_store_id,
                st.session_state.google_play_id,
            )
            st.session_state.country_availability = avail
            st.session_state["_avail_app_key"] = _avail_key

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
        # 不再无条件清空 country_availability，只在 App 变更时重新检测
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
    if "fetch_strategy" not in st.session_state:
        st.session_state.fetch_strategy = "mixed"

    st.number_input(
        "每个平台每个国家的评论数（最少 1）",
        min_value=1, max_value=2000, step=10,
        key="count_input",
    )

    strategy_options = {
        "混合（推荐）": "mixed",
        "最新评论": "recent",
        "最相关评论": "relevant",
    }
    strategy_label = st.selectbox(
        "抓取策略",
        options=list(strategy_options.keys()),
        index=0,
        help="混合：50% 最新 + 50% 最相关，覆盖面更广；最新：偏向近期评论；最相关：偏向高赞/热门评论",
    )
    st.session_state.fetch_strategy = strategy_options[strategy_label]

    # 日期范围过滤
    st.markdown("**评论时间范围（可选）：**")
    date_col1, date_col2 = st.columns(2)
    with date_col1:
        date_from_val = st.date_input(
            "开始日期",
            value=None,
            key="date_from_input",
            help="只抓取该日期之后的评论，留空则不限制",
        )
    with date_col2:
        date_to_val = st.date_input(
            "结束日期",
            value=None,
            key="date_to_input",
            help="只抓取该日期之前的评论，留空则不限制",
        )
    st.session_state["date_from"] = date_from_val.strftime("%Y-%m-%d") if date_from_val else None
    st.session_state["date_to"] = date_to_val.strftime("%Y-%m-%d") if date_to_val else None
    if date_from_val or date_to_val:
        range_desc = ""
        if date_from_val:
            range_desc += f"从 {date_from_val}"
        if date_to_val:
            range_desc += f" 到 {date_to_val}"
        st.caption(f"📅 时间过滤：{range_desc.strip()}（过滤后实际数量可能少于设定值）")

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
    count_for_cache = st.session_state.get("count", 200)  # 与 count_input 默认值一致
    date_from_for_cache = st.session_state.get("date_from")
    date_to_for_cache = st.session_state.get("date_to")

    if app_name_for_cache:
        ck = _cache_key(app_name_for_cache, countries_for_cache, platforms_for_cache, count_for_cache, date_from_for_cache, date_to_for_cache)
        cached = _load_cache(ck)
        if cached:
            st.session_state.report = cached.get("report", "")
            st.session_state.aggregated = cached.get("aggregated")
            st.session_state.analyzed_reviews = cached.get("analyzed_reviews")
            st.session_state.elapsed = cached.get("elapsed", 0)
            st.session_state.step = 5
            _show_results()
            st.stop()

    st.markdown('<div class="step-title">Step 4: 分析中</div>', unsafe_allow_html=True)

    import threading
    from concurrent.futures import ThreadPoolExecutor, Future

    # ── 用 cache_resource 存储跨 rerun 存活的任务状态 ──
    @st.cache_resource(show_spinner=False)
    def _get_running_task(task_key):
        """返回一个跨 rerun 存活的任务容器"""
        return {
            "future": None,
            "pool": None,
            "agent": None,
            "logs": [],
            "lock": threading.Lock(),
            "start_time": None,
            "phase_number": 0,
            "total_phases": 5,
        }

    task_key = f"analysis_{app_name_for_cache}_{count_for_cache}"
    task = _get_running_task(task_key)

    def _log_to_task(icon, text):
        with task["lock"]:
            task["logs"].append(f"{icon} {text}")

    def on_event(event_type, data):
        if event_type == "phase":
            phase_number = data.get("phase_number", 0)
            total_phases = data.get("total_phases", 5)
            with task["lock"]:
                task["phase_number"] = phase_number
                task["total_phases"] = total_phases
            _log_to_task("🔄", f"**{data.get('phase', '')}**")
        elif event_type == "tool_call":
            _log_to_task("  ⚙️", data.get("input_summary", ""))
        elif event_type == "tool_result":
            msg = data.get("message", "")
            if msg:
                _log_to_task("  ✅", msg)
        elif event_type == "fetch_progress":
            fetched = data.get("fetched", 0)
            total = data.get("total", 0)
            platform = "App Store" if data.get("platform") == "app_store" else "Google Play"
            country = COUNTRIES.get(data.get("country", ""), data.get("country", ""))
            _log_to_task("  📥", f"{country} {platform}: 已抓取 {fetched}/{total} 条")
        elif event_type == "agent_done":
            _log_to_task("🎉", "**全部完成**")

    # 只在没有运行中的任务时启动
    if task["future"] is None or (task["future"].done() and task["future"].exception()):
        task["logs"] = []
        task["start_time"] = time.time()
        fetch_strategy = st.session_state.get("fetch_strategy", "mixed")

        agent = ReviewRadarAgent(on_event=on_event)
        task["agent"] = agent

        def _run_agent():
            return agent.run(
                app_name=app_name_for_cache,
                app_store_id=st.session_state.get("app_store_id"),
                google_play_id=st.session_state.get("google_play_id"),
                platforms=platforms_for_cache,
                countries=countries_for_cache,
                count_per_platform=count_for_cache,
                fetch_strategy=fetch_strategy,
                date_from=st.session_state.get("date_from"),
                date_to=st.session_state.get("date_to"),
            )

        task["pool"] = ThreadPoolExecutor(max_workers=1)
        task["future"] = task["pool"].submit(_run_agent)

    # ── 显示进度 ──
    with st.status("正在分析...", expanded=True) as status_ui:
        progress_bar = st.progress(0)
        phase_label = st.empty()
        log_area = st.empty()

        while task["future"] and not task["future"].done():
            with task["lock"]:
                snapshot = list(task["logs"][-20:])
                p_num = task["phase_number"]
                p_total = task["total_phases"]
            progress_val = min(p_num / max(p_total, 1), 1.0)
            progress_bar.progress(progress_val, text=f"阶段 {p_num}/{p_total}")
            if snapshot:
                log_area.markdown("\n\n".join(snapshot))
            time.sleep(2)

        # 最终刷新
        with task["lock"]:
            snapshot = list(task["logs"][-20:])
        progress_bar.progress(1.0, text="完成")
        if snapshot:
            log_area.markdown("\n\n".join(snapshot))

        # 获取结果
        try:
            report = task["future"].result()
        except Exception as e:
            status_ui.update(label="分析失败", state="error", expanded=True)
            st.error(f"错误: {e}")
            # 清理缓存允许重试
            _get_running_task.clear()
            if st.button("← 返回重试"):
                st.session_state.step = 3
                st.rerun()
            st.stop()

        agent = task["agent"]
        elapsed = time.time() - (task["start_time"] or time.time())

        if task["pool"]:
            task["pool"].shutdown(wait=False)

        if not report:
            status_ui.update(label="未生成报告", state="error")
            _get_running_task.clear()
            st.stop()

        # 保存到 session
        st.session_state.report = report
        st.session_state.aggregated = agent.aggregated
        st.session_state.analyzed_reviews = agent.analyzed_reviews
        st.session_state.elapsed = elapsed
        save_report(report, app_name_for_cache)

        # 保存到文件缓存（防 session 丢失）
        if app_name_for_cache:
            ck = _cache_key(app_name_for_cache, countries_for_cache, platforms_for_cache, count_for_cache, date_from_for_cache, date_to_for_cache)
            _save_cache(ck, {
                "report": report,
                "aggregated": agent.aggregated,
                "analyzed_reviews": agent.analyzed_reviews,
                "elapsed": elapsed,
            })

        # 保存到分析历史
        try:
            uh = st.session_state.get("user_hash", "")
            if uh:
                save_analysis(
                    user_hash=uh,
                    app_name=app_name_for_cache or "unknown",
                    countries=countries_for_cache,
                    platforms=platforms_for_cache,
                    review_count=len(agent.analyzed_reviews or []),
                    aggregated=agent.aggregated,
                    report=report,
                    analyzed_reviews=agent.analyzed_reviews,
                )
        except Exception:
            pass  # 历史保存失败不影响主流程

        status_ui.update(label=f"分析完成（耗时 {elapsed:.0f} 秒）", state="complete", expanded=False)

    # 清理任务缓存
    _get_running_task.clear()

    # 标记完成，防止 rerun 时重新执行分析
    st.session_state.step = 5
    _show_results()

elif step == 5:
    # rerun 后直接显示已有结果
    if st.session_state.get("report"):
        _show_results()
    else:
        # session 丢失，回到开始
        st.session_state.step = 1
        st.rerun()
