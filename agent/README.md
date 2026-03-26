# AI-Infra Weekly Intelligence Agent

> 每周自动生成两份报告：**学术论文深度解读** + **AI 行业官方信号图谱**，通过邮件推送给团队。

---

## 架构总览

```
daily_paper_agent.py (主入口)
│
├── 第一部分：论文周报 (Paper Digest)
│   ├── 数据采集：arXiv / Crossref / OpenAlex / Semantic Scholar / RSS
│   ├── 排序：主题评分 → 多源去重 → 社交热度评分 (GitHub/X/Reddit)
│   ├── 精读：下载 PDF → 提取全文 → LLM 逐篇深度解读
│   └── 输出：Top 3 论文解读 + PDF 原文
│
└── 第二部分：AI 官方信号图谱 (Official Monitor)
    ├── 数据采集：50+ AI 大厂 & VC 官网
    ├── 筛选：信号门控 → 角色门控 → 投资硬约束
    ├── 聚类：Token 相似度聚类 → 合并/再平衡 → LLM 主题生成
    ├── 自反思：LLM 回顾筛选质量，输出遗漏/误选/建议
    └── 输出：2-4 个主题聚类 + 战略信号解读
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

## 第一部分：论文周报

### 数据源

| 来源 | 采集量 | 特点 |
|------|--------|------|
| arXiv | 120 篇 | RSS + API，覆盖 cs.RO / cs.CV / cs.AI |
| Crossref | 30/词 | 期刊元数据，含引用量 |
| OpenAlex | 25/页 | 倒排索引摘要重建，引用追踪 |
| Semantic Scholar | 25/词 | 影响力引用 + 作者机构 |
| RSS (OpenReview) | 动态 | 机器人学领域直连 |

### 排序流水线

```
采集 450+ 篇 → 标题去重 → 主题评分（关键词匹配）
→ 多样化筛选 Top 18 → 社交热度评分 → 最终 Top 3
```

**主题评分**：匹配 45 个中英文关键词，加权计算（infra ×4, physical ×4, focus ×3），对不相关领域施加惩罚。

**社交热度评分（100 分制）**：
- GitHub（40 分）：stars/forks + 7 日增速 + 深度参与度
- X/Twitter（30 分）：KOL 背书（karpathy ×2.0, ylecun ×2.0 等）+ 互动量
- Reddit（30 分）：subreddit 权重 + 评论深度 + upvote 质量

### 精读分析

对 Top 3 论文：
1. **下载 PDF**（arXiv 优先，带 3 次重试 + 指数退避，论文间 3s 间隔防限流）
2. **提取全文**（PyMuPDF，最多 60K 字符）
3. **LLM 深度解读**（Gemini 3.0 Flash，65K output tokens），输出 5 个必答字段：
   - 问题与背景
   - 核心方法与创新（用通俗语言解释）
   - 关键结论
   - 增量价值与影响
   - 局限与开放问题

### 质量评分（100 分制）

| 维度 | 满分 | 评估内容 |
|------|------|----------|
| A. 作者历史命中率 | 30 | 过往论文影响力（待实现） |
| B. 可复现性 | 25 | 代码仓库 / 权重 / 数据集 / 环境文件 |
| C. 社区早期反响 | 20 | GitHub stars/forks + PapersWithCode + HuggingFace |
| D. 实验强度 | 15 | 基线对比 / 消融实验 / 多任务 / 效率分析 |
| E. 新颖性 | 10 | 问题清晰度 / 贡献明确度 / 前沿关联性 |

分级：A (>=85) / B (>=70) / C (>=50) / D (<50)

---

## 第二部分：AI 官方信号图谱

### 监控源（50+）

**AI 大厂**：OpenAI, Anthropic, DeepMind, Meta AI, xAI, Microsoft, NVIDIA, AWS, Google Cloud, Mistral, Cohere, Stability, Qwen, 智谱, MiniMax, 百度, 商汤, 腾讯, DeepSeek, Hugging Face, Together, Scale, Databricks 等

**投资机构**：a16z, Sequoia, Accel, Greylock, Index Ventures, Bessemer, General Catalyst, Menlo, Atomico, Sapphire, 高瓴, 启明, 红杉中国 等

### 筛选流水线

```
原始文章 (450+)
    ↓
[信号门控] 强信号关键词 vs 低信号关键词
    ↓
[角色门控]
  ├─ AI 大厂：拒绝软文模式（how to/tutorial/case study），要求标题含硬发布关键词
  └─ 投资机构：拒绝观点/周报，要求交易信号 + 金额/人事关键词
    ↓
[投资硬约束] 必须提取到：被投企业、金额、赛道
    ↓
清洗后文章 (40-50)
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

### 自反思机制

每次运行后，LLM 自动回顾筛选结果：

| 评估维度 | 说明 |
|----------|------|
| `overall_score` | 1-10 筛选质量评分 |
| `potentially_missed` | 被错误过滤的重要文章 + 原因 |
| `potentially_bad` | 不该保留但被保留的文章 + 原因 |
| `filter_suggestions` | 具体参数调整建议 |
| `coverage_gaps` | 筛选盲区分析 |

结果写入 `run_history.jsonl`，可追踪长期趋势。

---

## 配置系统

### scoring.yaml

所有评分参数外置为 `agent/config/scoring.yaml`，**无需改代码即可调参**：

```yaml
# 聚类阈值
cluster:
  initial_threshold: 0.42     # 加入聚类的最低相似度
  max_cluster_size: 4          # 每个聚类最大文章数

# 质量评分权重
quality_score:
  weights:
    author_historical: 30
    reproducibility: 25
    community_response: 20

# 社交信号系数
social_scoring:
  x_twitter:
    kol_weights:
      karpathy: 2.0
      ylecun: 2.0
```

**代码中使用**：
```python
from config import cfg
threshold = cfg("cluster.initial_threshold", 0.42)  # 点路径访问 + 默认值
```

**自定义配置路径**：`export SCORING_YAML=/path/to/custom.yaml`

---

## 运行指标持久化

每次运行后自动追加到 `papers/run_history.jsonl`：

```jsonl
{
  "timestamp": "2026-03-24T10:30:00+00:00",
  "paper_digest": {
    "fetched": 180,
    "top3_titles": ["...", "...", "..."],
    "top3_early_scores": [85, 78, 71],
    "fulltext_hit_rate": 0.89,
    "pdf_downloaded": 3
  },
  "official_monitor": {
    "fetched": 450,
    "deduped": 380,
    "kept": 42,
    "clusters": 3,
    "drop_reasons": {"low_signal_content": 210, "role_specific_filtered": 128}
  },
  "reflection": {
    "overall_score": 8,
    "potentially_missed": [...],
    "filter_suggestions": [...]
  }
}
```

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
- `papers/*.xlsx` — 清洗前原始文章 Excel（来源厂商/时间/链接）
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
    ├── sources.py                # 50+ 监控源注册表
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
