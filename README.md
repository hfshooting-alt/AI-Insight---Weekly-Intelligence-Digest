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

## 新增：24h论文情报 Agent（World Engine + 数据Infra）

已新增一个可运行的 Agent：`agent/daily_paper_agent.py`。

它会：

1. 自动抓取最近24小时论文（多来源，不局限单站）
   - `arXiv`（预印本）
   - `Crossref`（聚合 Science/AAAS、Elsevier、Springer、ACM、IEEE 等大量出版方索引）
   - `OpenAlex`（跨学科开放索引）
2. 过滤主题：`World Engine / World Model / 合成数据 / 数据采集生产处理基础设施`。
3. 调用 LLM 生成每篇论文报告：
   - 一句话核心
   - 若干 bullet points
   - 全文精读（缺口、增量、证据、博导判决）
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
- `REPORT_EMAIL_TO`
- `SMTP_PASS`（163客户端授权码）

**建议填写（不填会自动回退）**
- `REPORT_EMAIL_FROM`（默认回退到 `REPORT_EMAIL_TO`）
- `SMTP_USER`（默认回退到 `REPORT_EMAIL_FROM` 或 `REPORT_EMAIL_TO`）
- `SMTP_HOST`（默认 `smtp.163.com`）
- `SMTP_PORT`（默认 `465`）
