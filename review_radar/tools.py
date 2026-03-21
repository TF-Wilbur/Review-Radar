"""5 个 Tool 的 JSON Schema 定义"""

TOOLS = [
    {
        "name": "search_app",
        "description": "根据 App 名字自动搜索 App Store 和 Google Play，找到对应的 App ID 和包名。用户只需要提供 App 名字，不需要知道技术参数。",
        "input_schema": {
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "description": "App 名字，如'微信'、'飞书'、'Notion'"
                },
                "country": {
                    "type": "string",
                    "description": "国家/地区代码，默认 us",
                    "default": "us"
                }
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "fetch_reviews",
        "description": "从 App Store 和 Google Play 并行抓取用户评论。需要先通过 search_app 获取 App ID。返回标准化的评论列表。",
        "input_schema": {
            "type": "object",
            "properties": {
                "app_store_id": {
                    "type": "string",
                    "description": "App Store 的 app ID（数字）"
                },
                "google_play_id": {
                    "type": "string",
                    "description": "Google Play 的包名，如 com.tencent.mm"
                },
                "count": {
                    "type": "integer",
                    "description": "每个平台抓取的评论数量，默认 200",
                    "default": 200
                },
                "country": {
                    "type": "string",
                    "description": "国家/地区代码，默认 us",
                    "default": "us"
                }
            },
            "required": []
        }
    },
    {
        "name": "analyze_batch",
        "description": "对一批评论进行多维度分析（情感、分类、关键词、痛点）。每次最多分析 50 条评论。需要多次调用以覆盖所有评论。",
        "input_schema": {
            "type": "object",
            "properties": {
                "batch_index": {
                    "type": "integer",
                    "description": "批次编号，从 0 开始"
                },
                "reviews": {
                    "type": "array",
                    "description": "本批次待分析的评论列表，最多 50 条",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "content": {"type": "string"},
                            "rating": {"type": "integer"},
                            "platform": {"type": "string"},
                            "version": {"type": "string"},
                            "date": {"type": "string"}
                        }
                    }
                }
            },
            "required": ["batch_index", "reviews"]
        }
    },
    {
        "name": "evaluate_coverage",
        "description": "评估当前分析的完整度和质量。检查所有批次的分析结果，判断是否存在遗漏、不一致或需要补充的区域。可以动态调整后续分析策略。最多调用 3 次。",
        "input_schema": {
            "type": "object",
            "properties": {
                "total_reviews": {
                    "type": "integer",
                    "description": "评论总数"
                },
                "analyzed_batches": {
                    "type": "integer",
                    "description": "已分析的批次数"
                },
                "aggregated_results": {
                    "type": "object",
                    "description": "所有批次的聚合结果"
                }
            },
            "required": ["total_reviews", "analyzed_batches", "aggregated_results"]
        }
    },
    {
        "name": "generate_report",
        "description": "基于完整的分析结果生成洞察报告。采用三步 Prompt Chaining：先生成大纲，再逐章生成正文，最后格式化。每个数据点都要有'so what'推理。",
        "input_schema": {
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "description": "App 名称"
                },
                "analysis_data": {
                    "type": "object",
                    "description": "完整的分析数据"
                },
                "report_step": {
                    "type": "string",
                    "enum": ["outline", "chapter", "finalize"],
                    "description": "报告生成阶段"
                },
                "chapter_index": {
                    "type": "integer",
                    "description": "当 report_step=chapter 时，指定生成第几章"
                },
                "outline": {
                    "type": "string",
                    "description": "已生成的大纲"
                },
                "chapters": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "已生成的章节内容"
                }
            },
            "required": ["app_name", "analysis_data", "report_step"]
        }
    },
]
