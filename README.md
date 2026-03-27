# AI Weekly Intelligence Agent

> 每周自动生成两份报告：**Paper Digest（学术论文深度解读）** + **Official Monitor（AI 行业官方信号图谱）**，通过邮件推送给团队。

---

## 架构总览

```
daily_paper_agent.py (主入口)
│
├── Part 1: Paper Digest — 学术论文周报
│   ├── 数据采集：arXiv / Crossref / OpenAlex / Semantic Scholar / RSS
│   ├── 排序：主题评分 → 多源去重 → 社交热度评分 (GitHub/X/Reddit)
│   ├── 精读：下载 PDF → 提取全文 → LLM 逐篇深度解读
│   └── 输出：Top 3 论文解读 + PDF 原文 + 质量检查 Excel
│
└── Part 2: Official Monitor — AI 行业信号图谱
    ├── 数据采集：45 个国际 AI 大厂 & VC 官方通道（含 engineering/research 页面）
    ├── 筛选：轻量噪声过滤（保留播客/深度分析/研究/产品发布等）
    ├── 聚类：Token 相似度聚类 → 合并/再平衡 → LLM 主题生成
    ├── 自反思：LLM 回顾筛选质量，输出遗漏/误选/建议
    └── 输出：2-4 个主题聚类 + 战略信号解读 + 全量 Excel
```

---

## 快速开始

### 1. 环境准备

```bash
cd agent
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
# 必填
export GOOGLE_API_KEY="your-gemini-api-key"
export REPORT_EMAIL_TO="recipient@example.com"
export SMTP_PASS="your-smtp-password"

# 可选
export GEMINI_MODEL="gemini-3.0-flash-preview"   # LLM 模型（默认值）
export SMTP_HOST="smtp.163.com"                   # SMTP 服务器
export SMTP_PORT="465"
export AGENT_MODE="once"                          # once | schedule
```

### 3. 运行

```bash
# 单次执行
python daily_paper_agent.py

# 定时任务（每周一 10:00 北京时间）
AGENT_MODE=schedule REPORT_TIME=10:00 TZ=Asia/Shanghai python daily_paper_agent.py
```

---

## Part 1: Paper Digest — 学术论文周报

### 关注方向

聚焦 **World Engine / Data Infra for Physical AI** — 如何解决具身智能和 Physical AI 的数据问题，包括：
- 数据采集与生产管线（data scaling law for robot, cross-embodiment data, open x-embodiment）
- 合成数据（synthetic data for robot, sim-to-real）
- 数据飞轮（data flywheel, robot dataset, embodied dataset）
- World Model / 仿真引擎 / 感知数据基础设施

### 数据源

| 来源 | 采集量 | 特点 |
|------|--------|------|
| arXiv | ~120 篇 | RSS + API，覆盖 cs.RO / cs.CV / cs.AI |
| Crossref | ~30/词 | 期刊元数据，含引用量 |
| OpenAlex | ~25/页 | 倒排索引摘要重建，引用追踪 |
| Semantic Scholar | ~25/词 | 影响力引用 + 作者机构 |
| RSS (OpenReview) | 动态 | 机器人学领域直连 |

### 排序流水线

```
采集 450+ 篇 → 标题去重 → 主题评分（45 个中英文关键词加权）
  → 多样化筛选 Top 18 → 社交热度评分 → 最终 Top 3
```

**社交热度评分（100 分制）**：
- GitHub（40 分）：stars/forks + 7 日增速 + 深度参与度
- X/Twitter（30 分）：KOL 背书（karpathy x2.0, ylecun x2.0 等）+ 互动量
- Reddit（30 分）：subreddit 权重 + 评论深度 + upvote 质量

### 精读分析

对 Top 3 论文：
1. **下载 PDF**（arXiv 优先，3 次重试 + 指数退避，论文间 3s 间隔防限流）
2. **提取全文**（PyMuPDF，最多 60K 字符）
3. **LLM 深度解读**（Gemini 3.0 Flash，65K output tokens），输出 6 个字段：
   - **为什么值得关注** — 一句话说明这篇论文的核心看点
   - 问题与背景
   - 核心方法与创新（用通俗语言解释）
   - 关键结论
   - 增量价值与影响
   - 局限与开放问题

### 质量检查 Excel

每次运行会导出 `papers/paper_quality_checkpoint.xlsx`，包含所有抓取到的论文：

| 列 | 说明 |
|----|------|
| 排名 | 综合排序名次 |
| 标题 | 论文标题 |
| 作者 | 第一作者等 |
| 原文链接 | arXiv/DOI 链接 |
| 主题相关分 | 关键词匹配得分 |
| 社交热度分 | GitHub/X/Reddit 综合 |
| 质量评估分 | 可复现性/实验强度等 |
| 综合排序分 | 最终排名依据 |

---

## Part 2: Official Monitor — AI 行业信号图谱

### 监控源（45 个通道，覆盖 30+ 机构）

**AI 大厂 — News/Blog + Engineering/Research 双通道**：

| 机构 | Blog / News | Engineering / Research |
|------|------------|----------------------|
| OpenAI | openai.com/news, developers.openai.com/blog | — (via news) |
| Anthropic | anthropic.com/news | anthropic.com/engineering, anthropic.com/research |
| Google DeepMind | deepmind.google/blog | deepmind.google/research |
| Meta AI | ai.meta.com/blog | — (research via blog) |
| xAI | x.ai/news | — |
| Microsoft | news.microsoft.com/topics/ai | microsoft.com/research/blog |
| NVIDIA | blogs.nvidia.com, developer.nvidia.com/blog | nvidia.com/research |
| AWS | aws.amazon.com/blogs/machine-learning | — |
| Google Cloud | cloud.google.com/blog/ai-machine-learning | — |
| Apple | — | machinelearning.apple.com |
| Mistral | mistral.ai/news | — |
| Cohere | cohere.com/blog | cohere.com/research |
| Stability AI | stability.ai/news | stability.ai/research |
| Hugging Face | huggingface.co/blog | — |
| Together AI | together.ai/blog | together.ai/research |
| Scale AI | scale.com/blog | labs.scale.com/papers |
| Databricks | databricks.com/blog | — |
| Replit | blog.replit.com | — |
| AMD | amd.com/newsroom | — |

**投资机构（10）**：a16z, Sequoia Capital, Accel, Greylock, Index Ventures, Bessemer, General Catalyst, Menlo Ventures, Atomico, Sapphire Ventures

### 筛选策略

采用**宽进严出**的轻量级过滤，目标是捕获所有有价值的内容类型：

```
原始文章 (全量抓取，7 天窗口)
    ↓
[三层去重] canonical URL / 标题相似度 / content hash
    ↓
[噪声过滤] 仅剔除：bug fix / changelog / maintenance / cookie policy / 招聘页
    ↓
[内容过滤] 仅剔除：空白页 / 404 / 内容不足 100 字且无摘要
    ↓
清洗后文章
    ↓
[Token 聚类] Jaccard 相似度 ≥ 0.42
    ↓
[合并小聚类] 相似度 ≥ 0.22
    ↓
[再平衡] 保证 2-4 个主题
    ↓
最终主题聚类 (2-4)
    ↓
[LLM 自反思] 审核筛选质量
```

保留的内容类型包括但不限于：产品发布、技术博客、播客、深度分析、研究论文、合作公告、融资动态。

### 全量 Excel 导出

每次运行导出 `papers/official_monitor_raw_articles.xlsx`，包含该周抓取到的**所有文章**，并标注是否入选周报（绿色高亮）。

### 自反思机制

每次运行后，LLM 自动回顾筛选结果：

| 评估维度 | 说明 |
|----------|------|
| `overall_score` | 1-10 筛选质量评分 |
| `potentially_missed` | 被错误过滤的重要文章 + 原因 |
| `potentially_bad` | 不该保留但被保留的文章 + 原因 |
| `filter_suggestions` | 具体参数调整建议 |
| `coverage_gaps` | 筛选盲区分析 |

---

## 自我迭代机制

Agent 通过三个维度实现每次运行都比上次更好：

### 1. 外置参数（scoring.yaml）

所有评分/聚类参数外置为 `agent/config/scoring.yaml`（100+ 参数），无需改代码即可调参：

```yaml
cluster:
  initial_threshold: 0.42
  max_cluster_size: 4

social_scoring:
  x_twitter:
    kol_weights:
      karpathy: 2.0
      ylecun: 2.0
```

代码中通过点路径访问：
```python
from config import cfg
threshold = cfg("cluster.initial_threshold", 0.42)
```

自定义路径：`export SCORING_YAML=/path/to/custom.yaml`

### 2. 运行指标持久化（run_history.jsonl）

每次运行后追加到 `papers/run_history.jsonl`：

```json
{
  "timestamp": "2026-03-24T10:30:00+00:00",
  "paper_digest": {
    "fetched": 180, "top3_titles": ["..."],
    "fulltext_hit_rate": 0.89, "pdf_downloaded": 3
  },
  "official_monitor": {
    "fetched": 450, "deduped": 380, "kept": 42, "clusters": 3
  },
  "reflection": {
    "overall_score": 8, "potentially_missed": [], "filter_suggestions": []
  }
}
```

### 3. LLM 自反思

每次运行结束后自动对比"原始抓取 vs 最终入选"，输出改进建议，写入 `run_history.jsonl` 供下次参考。

---

## CI/CD

通过 GitHub Actions 手动触发（`.github/workflows/daily-paper-digest.yml`）：

**Secrets 配置**：
```
GOOGLE_API_KEY, REPORT_EMAIL_TO, SMTP_PASS
GEMINI_MODEL, SMTP_HOST, SMTP_PORT, SMTP_USER, REPORT_EMAIL_FROM
```

**Artifacts 输出**（保留 30 天）：
- `papers/*.pdf` — Top 3 论文 PDF 原文
- `papers/*.xlsx` — 质量检查 Excel + 全量抓取 Excel
- `papers/run_history.jsonl` — 运行指标 + 自反思结果

---

## 文件结构

```
agent/
├── daily_paper_agent.py          # 主入口：论文采集/排序/精读/邮件发送
├── requirements.txt              # 依赖
├── run_history.py                # 运行指标持久化
├── config/
│   ├── __init__.py               # 配置加载器（dot-path 访问）
│   └── scoring.yaml              # 100+ 可调参数
└── official_monitor/
    ├── pipeline.py               # 核心流水线：采集→筛选→聚类→反思
    ├── sources.py                # 45 个监控通道注册表
    ├── models.py                 # 数据模型（NormalizedArticle, TopicCluster 等）
    ├── cluster.py                # Token 相似度聚类
    ├── extract.py                # 文章结构化提取
    ├── fetch.py                  # HTTP 抓取
    ├── discover.py               # 列表页/文章链接发现
    ├── dedupe.py                 # 内容哈希去重
    ├── summarize.py              # LLM 摘要生成
    ├── render.py                 # Markdown + HTML 渲染
    ├── reflection.py             # 筛选质量自反思
    ├── export.py                 # Excel 导出
    └── dates.py                  # 时间工具
```

---

## 环境变量速查

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `GOOGLE_API_KEY` | 是 | — | Gemini API Key |
| `REPORT_EMAIL_TO` | 是 | — | 收件人（多个用逗号分隔） |
| `SMTP_PASS` | 是 | — | SMTP 密码 |
| `GEMINI_MODEL` | 否 | `gemini-3.0-flash-preview` | LLM 模型 |
| `AGENT_MODE` | 否 | `once` | `once` / `schedule` |
| `REPORT_TIME` | 否 | `10:00` | 定时发送时间 |
| `TZ` | 否 | `Asia/Shanghai` | 时区 |
| `MAX_PAPERS` | 否 | `18` | 候选论文池大小 |
| `PAPERS_DIR` | 否 | `papers` | PDF/Excel 输出目录 |
| `OFFICIAL_MONITOR_ENABLED` | 否 | `1` | 是否启用信号图谱 |
| `OFFICIAL_MONITOR_LOOKBACK_DAYS` | 否 | `7` | 信号回溯天数 |
| `GITHUB_TOKEN` | 否 | — | GitHub API（提升社交评分精度） |
| `X_BEARER_TOKEN` | 否 | — | X/Twitter API |
| `SCORING_YAML` | 否 | `agent/config/scoring.yaml` | 自定义评分配置路径 |
