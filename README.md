# ljg-skill-paper

论文深读器。给它一篇论文，它告诉你：填了什么缺口，增量站不站得住，一个带了二十年研究生的博导怎么评。

## 安装

将此仓库克隆到 Claude Code skills 目录：

```bash
git clone https://github.com/lijigang/ljg-skill-paper.git /tmp/ljg-skill-paper && \
  cp -r /tmp/ljg-skill-paper/skills/ljg-paper ~/.claude/skills/ && \
  rm -rf /tmp/ljg-skill-paper
```

## 使用

```
/ljg-paper https://arxiv.org/abs/2401.xxxxx
/ljg-paper ~/Downloads/some-paper.pdf
/ljg-paper Attention Is All You Need
```

支持 arxiv URL、PDF、本地文件、论文名称搜索。

## 输出

一篇连贯的 Org-mode 分析（Denote 规范），存入 `~/Documents/notes/`。包含：

1. **缺口与增量** — 已有研究的边界在哪，这篇论文往前推了多远
2. **核心机制** — ASCII 结构图 + 承重类比，看完能复述方法逻辑
3. **关键概念** — 1-3 个钥匙概念，费曼技巧从零讲透
4. **餐巾纸速写** — 一张图看清新旧框架的结构位移
5. **博导审稿** — 选题、方法、实验、写作，最后一句判决
6. **启发** — 迁移、混搭、反转：对我有什么用？

## License

MIT

---

## 新增：北京时间昨日与今日论文情报 Agent（World Engine + 数据Infra）

已新增一个可运行的 Agent：`agent/daily_paper_agent.py`。

它会：

1. 自动抓取严格限定在“北京时间昨天与今天”的论文（多来源，不局限单站）
   - `arXiv`（预印本）
   - `Crossref`（聚合 Science/AAAS、Elsevier、Springer、ACM、IEEE 等大量出版方索引）
   - `OpenAlex`（跨学科开放索引）
2. 过滤主题：`World Engine / World Model / 合成数据 / 数据采集生产处理基础设施`。
3. 调用 LLM 生成每篇论文报告：
   - 一句话核心
   - 若干 bullet points
   - 全文精读（缺口、增量、证据，不含审稿判决板块）
4. 每天上午10点自动发送日报到指定邮箱。

### 你要求的两个变量

- `REPORT_EMAIL_TO`：邮件发送目标地址（必填）
- `OPENAI_API_KEY`：ChatGPT API（必填）

### 快速开始

```bash
cd /workspace/-AI-Infra-/agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env，至少填 OPENAI_API_KEY 和 REPORT_EMAIL_TO
set -a && source .env && set +a
python daily_paper_agent.py
```

### 每天10点自动发送

方式 A：脚本内置调度（推荐先验证）

```bash
set -a && source .env && set +a
export AGENT_MODE=schedule
python daily_paper_agent.py
```

方式 B：系统 cron（如果你更习惯）

```cron
0 10 * * * cd /workspace/-AI-Infra-/agent && /usr/bin/bash -lc 'source .env && .venv/bin/python daily_paper_agent.py >> agent.log 2>&1'
```

### 163 邮箱

脚本默认 `SMTP_HOST=smtp.163.com` + `SMTP_PORT=465`，并支持你已有163发送配置：

- `SMTP_USER`
- `SMTP_PASS`（163客户端授权码）

你也可以把 `send_email()` 替换为你现有发送函数，其他逻辑无需改动。


### GitHub Actions 定时（北京时间早上10点）

仓库已提供工作流：`.github/workflows/daily-paper-digest.yml`。

- 已固定按 *北京时间 10:00* 触发（对应 UTC `02:00`）。
- 也支持手动触发（`workflow_dispatch`）先试跑。

你需要在 GitHub 仓库 `Settings -> Secrets and variables -> Actions -> Secrets` 中配置：

**必填**
- `OPENAI_API_KEY`
- `OPENAI_MODEL`（例如你可用的 GPT-5.x 模型ID）
- `REPORT_EMAIL_TO`
- `SMTP_PASS`（163客户端授权码）

**建议填写（不填会自动回退）**
- `REPORT_EMAIL_FROM`（默认回退到 `REPORT_EMAIL_TO`）
- `SMTP_USER`（默认回退到 `REPORT_EMAIL_FROM` 或 `REPORT_EMAIL_TO`）
- `SMTP_HOST`（默认 `smtp.163.com`）
- `SMTP_PORT`（默认 `465`）


### 检索与时间范围（严格北京时间昨天与今天）

Agent 现在采用以下策略：

- *搜索引擎式多关键词检索*：对每个关键词分别请求多个索引源，而非单次宽泛请求。
- *多源覆盖*：`arXiv + Crossref + OpenAlex + Semantic Scholar`。
- *时间戳优先*：优先用 `indexed/updated/created` 的时间戳，而不是只有日期粒度的字段。
- *严格日期边界*：只保留北京时间昨天与今天的论文，不做跨周回退。

可通过环境变量调优：

- `MAX_PAPERS`（默认 `12`）
- `OPENAI_MODEL`（默认 `gpt-4o-mini`）


### 日报展示优化（更美观）

- 邮件改为 *HTML + 纯文本双格式*（兼容客户端），支持更清晰的标题、分节、分隔线和项目符号。
- 每篇论文保留「序号 + 标题 + 来源 + 链接 + 精读内容」，并按你的要求去掉了论文时间字段。
- 支持在日报顶部显示“来源命中统计 + 入选篇数”，便于快速判断覆盖质量。

### 检索来源扩展（不再局限少数平台）

当前检索层已覆盖：

- `arXiv`
- `Crossref`（聚合大量出版社与期刊索引）
- `OpenAlex`
- `Semantic Scholar`
- `期刊 RSS`：Nature、Science、PNAS、PLOS ONE、bioRxiv、medRxiv

严格按北京时间昨天与今天筛选；如果没有命中会明确输出“未检索到符合条件的论文”。


### 输出格式约束更新

- 日报正文不使用 `#`、`*` 等符号。
- 每篇论文保留序号、标题、发布时间、链接和精读内容（不再显示来源条目）。
- 已移除“博导审稿判决”板块。


### 日报内容规则补充

- 严格筛选北京时间昨天与今天的论文；没有命中就显示没有，不补旧论文。
- 每篇论文会标注发布时间（北京时间，基于发布字段，不使用更新字段）。
- 日报正文仅保留标题与论文条目，不再输出前置概述。
- 精读正文不再包含“45字以内”这类说明性标签。
- 每篇论文之间使用分割线和高亮块分隔。


### 本轮格式修复

- 每篇论文正文与标题保持在同一高亮块内，避免内容脱离。
- 删除每篇论文的“来源”条目。
- 在精读前新增“一句话核心”并高亮展示。
- 精读统一为三段结构：背景与现状、方法与结果、意义与局限。


### 每日分类与发布概览

- 日报最前面新增“今日发布概览”，一句话概括当天论文发布情况。
- 论文按两类分组展示：World Engine 与 Data Infra。
- 分类大标题使用更大的字号和加粗样式，且每篇论文仍用分割线与高亮块分隔。


### 视觉优化补充

- 分类大标题（World Engine / Data Infra）独立显示，不再包在论文高亮卡片内。
- 增加标题层级字号、段落间距与行高，降低文本拥挤感。
- 论文卡片改为白底+柔和阴影，阅读更聚焦。
