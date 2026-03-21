"""System Prompt 和分析 Prompt 模板"""

SYSTEM_PROMPT = """你是一个 App 用户评论分析 Agent。你必须通过调用工具来完成任务，不要用文字描述你要做什么。

**核心规则：永远通过调用工具来行动，不要只是描述步骤。每次回复都必须包含工具调用，直到所有步骤完成。**

工具列表：
1. search_app — 搜索 App ID
2. fetch_reviews — 抓取评论
3. analyze_batch — 分析一批评论（每次最多 50 条）
4. evaluate_coverage — 评估分析质量
5. generate_report — 生成报告

**重要：**
- 每次回复必须调用工具，不要只输出文字
- 不编造数据
"""

ANALYZE_BATCH_PROMPT = """你是一个专业的 App 评论分析师。请对以下 {count} 条评论进行多维度分析。

**评论列表：**
{reviews_json}

**请对每条评论分析以下维度：**

1. **情感分析**
   - sentiment: positive / negative / neutral
   - sentiment_score: -1.0（极度负面）到 1.0（极度正面）
   - 以评论文本为准，评分仅参考
   - 注意识别反讽、阴阳怪气等隐含情感

2. **评论分类**（每条归入一个主分类）
   - 功能吐槽：报告 bug、功能异常、崩溃、性能问题
   - 体验赞美：正面评价功能、设计、体验
   - 需求建议：提出新功能需求、改进建议
   - 竞品对比：与其他 App 对比
   - 其他：无实质内容、灌水、无关话题

3. **关键词提取**：每条评论提取 2-5 个关键词

4. **痛点识别**：如果评论包含痛点，提取痛点描述和严重程度（high/medium/low）

5. **功能归因**：识别评论提到的具体功能模块（如"支付"、"聊天"、"登录"、"通知"、"搜索"等）
   - feature: 功能名称或 null（如果评论未提及具体功能）

6. **用户场景**：识别用户的使用场景或目的（如"工作沟通"、"日常社交"、"购物支付"等）
   - usage_scenario: 场景描述或 null（如果无法识别）

7. **评分一致性**：判断评分与评论内容的情感是否一致
   - rating_sentiment_match: true/false（如 5 星但内容负面 = false）

{strategy_hint}

**请严格按以下 JSON 格式返回：**
{{
    "results": [
        {{
            "id": "评论ID",
            "sentiment": "positive/negative/neutral",
            "sentiment_score": 0.8,
            "category": "体验赞美",
            "keywords": ["关键词1", "关键词2"],
            "pain_point": "痛点描述或null",
            "pain_severity": "high/medium/low/null",
            "feature": "功能名称或null",
            "usage_scenario": "场景描述或null",
            "rating_sentiment_match": true
        }}
    ],
    "batch_summary": {{
        "sentiment_distribution": {{"positive": 10, "negative": 20, "neutral": 5}},
        "category_distribution": {{"功能吐槽": 15, "体验赞美": 8, "需求建议": 7, "竞品对比": 2, "其他": 3}},
        "top_keywords": [{{"word": "闪退", "count": 8}}, {{"word": "卡顿", "count": 5}}],
        "pain_points": [{{"description": "更新后频繁闪退", "mention_count": 6, "severity": "high"}}]
    }}
}}
"""

EVALUATE_PROMPT = """你是一个数据质量评估专家。请评估以下 App 评论分析结果的完整度和质量。

**分析概况：**
- 评论总数：{total_reviews}
- 已分析批次：{analyzed_batches}
- 已分析评论数：{total_analyzed}

**聚合结果：**
{aggregated_json}

**请检查以下维度：**

1. **覆盖率**：已分析数 / 总数 >= 95%？
2. **关键词质量**：Top 20 关键词是否有明显的同义词未合并？（如 crash/闪退/崩溃）
3. **痛点去重**：痛点列表是否有语义重复？
4. **版本样本**：主要版本是否都有 >= 5 条评论？
5. **分类一致性**：分类分布是否合理？

**请严格按以下 JSON 格式返回：**
{{
    "is_complete": true/false,
    "coverage_score": 0.95,
    "issues": [
        {{
            "dimension": "keyword_quality",
            "issue": "具体问题描述",
            "suggestion": "改进建议"
        }}
    ],
    "improvement_actions": [
        {{
            "action": "merge_keywords",
            "details": {{"groups": [["crash", "闪退", "崩溃"]]}}
        }}
    ],
    "strategy_adjustments": [
        {{
            "type": "focus_version",
            "details": "版本 X.X.X 负面评论集中，建议深入分析"
        }}
    ]
}}
"""

FEATURE_ANALYSIS_PROMPT = """你是一个产品分析专家。基于以下评论分析结果中的功能归因数据，生成功能级别的满意度分析。

**App：** {app_name}
**功能数据：**
{feature_data}

**要求：**
- 列出所有被提及的功能模块
- 每个功能统计：提及次数、正面评论数、负面评论数、中性评论数、负面率
- 列出每个功能的 Top 3 痛点（如果有）
- 按负面率降序排列（最需要改进的功能排在前面）
- 识别"无人提及"的功能盲区（用户完全没讨论的功能方向）

**请严格按以下 JSON 格式返回：**
{{
    "features": [
        {{
            "name": "功能名称",
            "mention_count": 15,
            "positive": 3,
            "negative": 10,
            "neutral": 2,
            "negative_rate": 0.67,
            "top_pain_points": ["痛点1", "痛点2"]
        }}
    ],
    "summary": "一句话总结功能满意度全貌"
}}
"""

# ── 报告生成 Prompt ──────────────────────────────────────────

REPORT_EXECUTIVE_SUMMARY_PROMPT = """基于以下 App 评论分析数据，用 5 句话写一个执行摘要。

**App：** {app_name}
**报告日期：** {current_date}

**数据：**
{global_summary}

**要求（严格按顺序，每句话不超过 30 字）：**
- 第 1 句：数据概况（X 条评论，来自 Y 个国家，覆盖 Z 个平台）
- 第 2 句：整体情感判断（一句话定性，引用正面/负面比例）
- 第 3 句：最严重的 1 个问题（引用具体数据）
- 第 4 句：最大的 1 个机会（用户最想要什么）
- 第 5 句：最紧急的 1 个行动（产品团队现在应该做什么）

直接输出 5 句话，不要标题、不要编号、不要多余格式。
"""

REPORT_OUTLINE_PROMPT = """你是一个资深产品分析师。请基于以下分析数据，生成一份 App 评论洞察报告的大纲。

**App：** {app_name}
**报告日期：** {current_date}
**分析范围：** {countries_desc}（平台：{platforms_desc}）

**全局数据概况：**
- 总评论数：{total_reviews}
- 情感分布：{sentiment_dist}
- 分类分布：{category_dist}
- Top 10 痛点：{pain_points}
- Top 20 关键词：{keywords}

**各国家数据概况：**
{country_summaries}

**报告大纲结构：**
1. 总览（全局数据概览、跨国对比摘要）
{country_outline_items}
N-1. 跨国对比分析
N. 行动建议

每个国家章节内部结构：
- X.1 iOS 分析（情感/分类/痛点/关键词）— 如果有 iOS 数据
- X.2 Android 分析 — 如果有 Android 数据
- X.3 跨平台对比 — 如果两个平台都有数据

每个章节列出 2-3 个要点。用 Markdown 格式输出。
"""

REPORT_COUNTRY_CHAPTER_PROMPT = """你正在撰写一份 App 评论洞察报告中「{country_name}」市场的分析章节。

**App：** {app_name}
**报告日期：** {current_date}
**本章国家：** {country_name}（{country_code}）
**本章平台：** {platform_desc}

**完整大纲：**
{outline}

**本国家数据：**
{country_data}

**代表性评论样本：**
{sample_reviews}

**写作要求：**
- 用数据说话，引用具体数字和百分比
- 引用评论时必须标注版本号和日期，格式：> "评论内容" —— v{{version}}, {{date}}
- 如果有多个平台数据，分 iOS 和 Android 小节分别分析，最后做跨平台对比
- 包含表格展示关键数据（情感分布表、分类分布表、痛点排名表）
- 每个数据点都要有洞察解读——这个数据意味着什么？背后的用户行为模式是什么？
- 不要在本章节给出行动建议，建议统一在最后的行动建议章节
- 分析评分分布（1-5 星各占比多少），找出评分集中区间
- 如果有功能归因数据，按功能模块分析满意度差异
- 如果有版本趋势数据，分析版本更新对评分的影响
- 至少引用 3-5 条有代表性的原始评论（正面和负面各至少 1 条）
- 语言简洁专业，面向产品团队
- 不编造数据，只使用提供的数据
"""

REPORT_OVERVIEW_PROMPT = """你正在撰写一份 App 评论洞察报告的「总览」章节。

**App：** {app_name}
**报告日期：** {current_date}
**分析范围：** {countries_desc}（平台：{platforms_desc}）

**全局聚合数据：**
{global_data}

**各国家摘要：**
{country_summaries}

**写作要求：**
- 总览章节控制在 300 字以内，只呈现最关键的 3-5 个发现
- 不要重复各国家章节会详细展开的内容
- 用一句话概括每个国家的核心特征，不展开
- 概述全局数据：总评论数、整体情感分布、主要痛点
- 用数据说话，引用具体数字和百分比
- 包含一个总览表格（国家、评论数、正面率、负面率、Top 1 痛点）
- 如果有功能分析数据，用一句话点出最需要关注的功能模块
- 语言简洁专业
- 不编造数据
"""

REPORT_CROSS_COUNTRY_PROMPT = """你正在撰写一份 App 评论洞察报告的「跨国对比分析」章节。

**App：** {app_name}
**报告日期：** {current_date}
**分析国家：** {countries_desc}

**各国家数据：**
{all_country_data}

**写作要求：**
- 用一个总览对比表格开头，列出各国家的：评论数、正面率、负面率、Top 1 痛点
- 对比各国家的情感分布差异，找出情感最正面和最负面的市场
- 对比各国家的 Top 痛点差异：
  - 全球共性痛点（多个国家都出现的）
  - 地区特有痛点（仅某国出现的）
- 对比各国家的关键词差异，分析文化/使用习惯差异
- 如果有版本趋势数据，对比各国家的版本评分差异
- 引用评论时必须标注版本号和日期，格式：> "评论内容" —— v{{version}}, {{date}}
- 每个对比点都要有"so what"——对产品国际化策略的启示
- 不编造数据
"""

REPORT_ACTION_PROMPT = """你正在撰写一份 App 评论洞察报告的「行动建议」章节。

**App：** {app_name}
**报告日期：** {current_date}

**全局聚合数据：**
{global_data}

**各国家数据摘要：**
{country_summaries}

**写作要求：**
- 全报告的行动建议不超过 10 条，宁缺毋滥
- 每条建议必须包含量化的优先级评分：
  - 影响面（1-5）：受影响用户比例，基于提及频率
  - 严重程度（1-5）：对用户体验的影响程度
  - 可解决性（1-5）：技术实现难度的反面（5=很容易解决）
  - 综合分 = 影响面 × 严重程度 × 可解决性
- 按综合分降序排列，分三个优先级：
  - P0 紧急修复（1-2 周）：综合分最高的 bug 和崩溃问题
  - P1 短期优化（1-3 月）：高频痛点、用户强烈需求
  - P2 长期规划（3-6 月）：竞品差距、新功能方向
- 每条建议必须包含：
  - 问题描述（一句话）
  - 数据支撑（引用具体数字和百分比）
  - 影响范围（全球/特定国家/特定平台）
  - 优先级评分表格（影响面/严重程度/可解决性/综合分）
- 删除所有泛化建议（如"加强测试"、"优化性能"），每条建议必须具体到可执行的动作
- 最后给出"快速胜利"清单：投入最小但用户感知最强的 3 件事
- 不编造数据
"""

REPORT_FINALIZE_PROMPT = """请将以下各章节内容整合为一份完整的 Markdown 报告。

**App：** {app_name}
**报告生成时间：** {current_date}
**总评论数：** {total_reviews}
**大纲：**
{outline}

**各章节内容：**
{chapters}

**内容优化要求（最重要）：**
- 检查并删除所有重复内容：如果同一个观点/建议在多个章节出现，只保留最详细的那一处
- 删除所有泛化的、不基于数据的建议（如"加强测试"、"优化性能"这类任何人都能说的话）
- 每个章节的核心观点不超过 5 个
- 全报告总长度控制在 2000 字以内（不含表格和引用）
- 如果总评论数 < 100，在报告开头添加醒目提示："> ⚠️ 本次分析基于 {total_reviews} 条评论，样本量较小，结论仅供参考"

**格式化要求：**
- 报告标题：# {{App名称}} 用户评论洞察报告
- 标题下方标注：**报告生成时间：** {current_date}
- 统一格式：标题层级、表格样式、引用格式
- 引用评论格式统一为：> "评论内容" —— v{{version}}, {{date}}
- 在末尾添加"分析说明"章节，说明数据来源、样本量、分析方法和局限性
- 确保所有 Markdown 语法正确
- 确保报告生成时间使用 {current_date}，不要使用其他日期
"""
