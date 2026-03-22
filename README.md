# AppPulse

感知每一条用户心声 — 输入 App 名字，自动抓取 App Store & Google Play 评论，多维度 AI 分析，生成可视化洞察报告。

## 功能特性

**评论抓取**
- 自动搜索 App Store + Google Play 双平台
- 支持 10+ 国家/地区（美国、日本、中国、英国、德国等）
- 自动检测各国可用性，多国家并发抓取
- Google Play 搜索结果交叉验证（名称相似度 + 开发者匹配），防止错误关联
- 混合抓取策略（最新 + 最相关），覆盖更长时间跨度

**AI 分析**
- 情感分析（正面/负面/中性 + 情感分数）
- 评论分类（功能吐槽、体验赞美、需求建议、竞品对比等）
- 痛点提取 + 严重程度评估
- 功能归因（将评论关联到具体功能模块）
- 评分与情感一致性检测（识别刷好评/误操作）
- 关键词提取 + 语义去重（跨语言同义词合并）
- 分析质量自评估 + 自动改进

**可视化仪表盘（Streamlit Web UI）**
- 情感分布饼图 + 评论分类柱状图
- 评分分布图 + 版本评分趋势
- 情感时间趋势（堆叠面积图）
- 功能满意度热力图
- 痛点下钻（展开查看原始评论）
- 评论浏览器（情感/评分/平台/关键词四维筛选 + 分页）
- CSV 数据导出
- 多国家 Tab 切换 + 全局视图

**报告生成**
- 执行摘要 + 分国家深度分析 + 跨国对比 + 行动建议
- Markdown + HTML 双格式下载
- 引用真实评论原文作为论据
- P0/P1/P2 三级优先级行动建议，含量化评分

**持久化**
- 支持本地 SQLite（默认）和 GCS 双存储后端
- 分析历史按 API Key 隔离，支持搜索和删除
- 本地文件缓存防止 session 断连丢失分析结果

## 技术架构

```
用户输入 App 名字
    ↓
Phase 0: 搜索 App（iTunes API + Google Play，交叉验证）
    ↓
Phase 1: 并发抓取评论（多国家 × 多平台，混合策略）
    ↓
Phase 2: 并发分批 AI 分析（50 条/批）
    ↓
Phase 2.5: 功能级满意度分析
    ↓
Phase 3: 质量评估 + 自动改进（最多 3 轮）
    ↓
Phase 3.5: 语义去重（跨语言同义词合并）
    ↓
Phase 4: 分章节生成报告
    ↓
可视化仪表盘 / Markdown + HTML 报告
```

- **Orchestrator 模式**：代码控制流程编排，LLM 负责分析和生成
- **多 LLM 提供商**：支持 OpenAI 兼容接口（MiniMax、OpenAI、DeepSeek 等），Web UI 可动态切换
- **并发优化**：多国家抓取 + 多批次分析均使用 ThreadPoolExecutor 并发
- **双存储后端**：本地 SQLite（默认）或 GCS，按用户隔离历史记录

## 示例报告

以下是对 Instagram 的分析摘要（完整报告见 [examples/Instagram-评论洞察.md](examples/Instagram-评论洞察.md)）：

> **分析样本：** 220 条评论（美国市场，iOS + Android）
>
> **情感分布：** 负面 64.3% | 中性 28.6% | 正面 7.1%
>
> **三大核心痛点：**
> 1. Feed 排序机制 — 用户强烈要求恢复时间顺序排列
> 2. 账号安全问题 — 误判封禁、申诉无响应，最长等待 5 个月
> 3. 应用稳定性 — Stories 功能崩溃问题突出
>
> **行动建议（P0）：** 修复 Stories 崩溃、建立账号误判快速申诉通道
>
> **行动建议（P1）：** 恢复 Feed 时间排序选项、降低广告密度、提升客服响应

报告包含：执行摘要、分国家深度分析、关键词分析、评分分布、代表性评论解读、P0/P1/P2 三级行动建议（含量化优先级评分）。

## 快速开始

### 1. 安装

```bash
git clone https://github.com/TF-Wilbur/Review-Radar.git
cd Review-Radar
pip install -e ".[web,dev]"
```

### 2. 配置

```bash
cp .env.example .env
# 编辑 .env，填入你的 LLM API Key
```

`.env` 配置项：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LLM_API_KEY` | LLM API 密钥 | — |
| `LLM_BASE_URL` | OpenAI 兼容接口地址 | `https://api.minimax.chat/v1` |
| `LLM_MODEL` | 模型名称 | `MiniMax-M2.7` |

### 3. 使用

**Web UI（推荐）**

```bash
streamlit run web/app.py
```

浏览器打开 `http://localhost:8501`，按引导操作即可。

**命令行**

```bash
# 基础用法
apppulse "TikTok"

# 多国家 + 指定平台
apppulse "微信" --countries us,cn,jp --platforms app_store,google_play --count 200
```

CLI 参数：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `app_name` | App 名字 | — |
| `--count` | 每平台每国家评论数 | 100 |
| `--countries` | 国家代码，逗号分隔 | `us` |
| `--platforms` | 平台，逗号分隔 | `app_store,google_play` |
| `--output` | 报告输出目录 | `reports` |

### 4. Docker

```bash
docker build -t apppulse .
docker run -p 8080:8080 --env-file .env apppulse
```

### 5. Cloud Run 部署

```bash
gcloud run deploy apppulse \
  --source . \
  --region asia-east1 \
  --allow-unauthenticated \
  --timeout 600 \
  --set-env-vars "LLM_API_KEY=your-key,LLM_BASE_URL=https://api.minimax.chat/v1,LLM_MODEL=MiniMax-M2.7"
```

## 项目结构

```
review-radar/
├── review_radar/
│   ├── agent.py        # Agent 主循环（Orchestrator 模式）
│   ├── tool_impl.py    # Tool 实现（抓取、分析、评估、报告）
│   ├── scrapers.py     # App Store + Google Play 抓取 + 搜索验证
│   ├── prompts.py      # 所有 Prompt 模板
│   ├── llm.py          # LLM 客户端封装
│   ├── providers.py    # 多 LLM 提供商支持
│   ├── models.py       # 数据模型
│   ├── availability.py # 国家可用性检测
│   ├── history.py      # 分析历史（SQLite / GCS 双后端）
│   ├── config.py       # 配置常量
│   ├── report.py       # 报告保存 + HTML 导出
│   └── cli.py          # CLI 入口 + Rich 终端 UI
├── web/
│   └── app.py          # Streamlit Web UI
├── tests/              # 测试
├── .streamlit/         # Streamlit 配置
├── Dockerfile
├── pyproject.toml
└── .env.example
```

## License

MIT
