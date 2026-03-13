from __future__ import annotations

from html import escape
from typing import Any, Dict, List

from .models import NormalizedArticle, RunSummary, TopicCluster


def source_link_markdown(inst_name: str, url: str) -> str:
    return f"[@{inst_name}（原文链接）]({url})"


def render_json(run_summary: RunSummary, articles: List[NormalizedArticle], clusters: List[TopicCluster]) -> Dict[str, Any]:
    return {
        "run_summary": run_summary.__dict__,
        "normalized_articles": [a.to_dict() for a in articles],
        "topic_clusters": [c.__dict__ for c in clusters],
    }


def _brief_intro(clusters: List[TopicCluster]) -> str:
    if not clusters:
        return "本期暂无高置信主题，建议关注下一周期官方发布节奏。"
    top = max(clusters, key=lambda c: (c.topic_priority_score, c.article_count))
    return f"本期重点围绕“{top.topic_title}”展开，建议优先阅读高优先级主题并跟踪其后续落地。"


def _summary_cards(run_summary: RunSummary, clusters: List[TopicCluster]) -> List[Dict[str, str]]:
    top_titles = "；".join([c.topic_title for c in clusters[:3]]) if clusters else "无"
    trend = "；".join(["产品化与平台化信号增强", "多方官方信息同题共振", "事件聚类更利于管理层快速决策"])
    return [
        {"title": "本期主题数", "value": str(run_summary.topic_clusters), "desc": "事件优先聚类后可直接用于决策阅读顺序"},
        {"title": "覆盖来源", "value": str(run_summary.covered_sources), "desc": f"共追踪 {run_summary.trusted_sources} 个官方信源"},
        {"title": "去重后文章", "value": str(run_summary.deduped_articles), "desc": f"原始抓取 {run_summary.fetched_articles} 篇，已去重清洗"},
        {"title": "Top 3 主题", "value": top_titles or "无", "desc": "建议作为管理层先读模块"},
        {"title": "本期趋势", "value": trend, "desc": "由主题聚类结果归纳，不新增业务推断"},
    ]


def _source_link(url: str, markdown_text: str) -> str:
    return (
        f"<a class='source-link' href='{escape(url)}' target='_blank' rel='noopener'>{escape(markdown_text)}</a>"
        if url
        else f"<span class='source-link muted'>{escape(markdown_text)}</span>"
    )


def _report_hero(run_summary: RunSummary, clusters: List[TopicCluster]) -> str:
    intro = _brief_intro(clusters)
    return f"""
    <section class='hero'>
      <div class='hero-eyebrow'>Official Source Monitor · Weekly Research Brief</div>
      <h1>过去一周 AI 官方动态聚类周报</h1>
      <p class='hero-subtitle'>{escape(intro)}</p>
      <div class='hero-meta'>
        <span>统计时间范围：过去{run_summary.lookback_days}天（滚动）</span>
        <span>主题数：{run_summary.topic_clusters}</span>
        <span>去重文章：{run_summary.deduped_articles}</span>
      </div>
    </section>
    """.strip()


def _summary_stats(run_summary: RunSummary, clusters: List[TopicCluster]) -> str:
    cards = []
    for c in _summary_cards(run_summary, clusters):
        cards.append(
            f"""
            <article class='summary-card'>
              <div class='summary-title'>{escape(c['title'])}</div>
              <div class='summary-value'>{escape(c['value'])}</div>
              <div class='summary-desc'>{escape(c['desc'])}</div>
            </article>
            """.strip()
        )
    return "<section class='summary-grid'>" + "".join(cards) + "</section>"


def _meta_info_row(cluster: TopicCluster) -> str:
    sources = "、".join(cluster.sources) if cluster.sources else "未披露"
    return (
        "<div class='meta-row'>"
        f"<span>文章数：{cluster.article_count}</span>"
        f"<span>置信度：{cluster.cluster_confidence_score:.2f}</span>"
        f"<span>优先级：{cluster.topic_priority_score:.1f}</span>"
        f"<span>涉及机构：{escape(sources)}</span>"
        "</div>"
    )


def _insight_block(label: str, content: str, tone: str = "normal") -> str:
    cls = "insight-block"
    if tone == "highlight":
        cls += " highlight"
    return (
        f"<section class='{cls}'>"
        f"<h4>{escape(label)}</h4>"
        f"<p>{escape(content)}</p>"
        "</section>"
    )


def _article_card(item: Dict[str, Any]) -> str:
    title = str(item.get("title", "未命名文章"))
    summary = str(item.get("article_summary_zh", ""))
    institution = str(item.get("institution_name", "未披露"))
    published = str(item.get("published_at", "未披露"))
    source_markdown = str(item.get("source_link_markdown", ""))
    url = str(item.get("url", ""))

    return f"""
    <article class='event-card'>
      <header class='event-header'>
        <h5>{escape(title)}</h5>
        <div class='event-meta'>
          <span>机构：{escape(institution)}</span>
          <span>发布时间：{escape(published[:10]) if published else '未披露'}</span>
        </div>
      </header>
      <div class='event-body'>
        {_insight_block('摘要', summary)}
      </div>
      <footer class='event-footer'>
        <span class='label'>来源</span>
        {_source_link(url, source_markdown)}
      </footer>
    </article>
    """.strip()


def _report_section(idx: int, cluster: TopicCluster) -> str:
    chips = "".join([f"<span class='chip'>{escape(k)}</span>" for k in cluster.topic_keywords[:8]])
    articles = "".join([_article_card(a) for a in cluster.supporting_articles])

    return f"""
    <section class='report-section'>
      <header class='section-header'>
        <div class='section-kicker'>Topic {idx:02d}</div>
        <h3>{escape(cluster.topic_title)}</h3>
        {_meta_info_row(cluster)}
      </header>

      <div class='section-summary'>
        {_insight_block('事件总结', cluster.event_summary)}
        {_insight_block('战略信号', cluster.strategic_signal, tone='highlight')}
      </div>

      <div class='chip-group'>{chips}</div>

      <div class='event-list'>
        {articles}
      </div>
    </section>
    """.strip()


def render_markdown(run_summary: RunSummary, clusters: List[TopicCluster]) -> str:
    lines = [
        "# 过去一周 AI 官方动态聚类",
        "",
        f"- 统计时间范围：过去{run_summary.lookback_days}天（滚动）",
        f"- 覆盖来源数：{run_summary.covered_sources}",
        f"- 抓取文章数：{run_summary.fetched_articles}",
        f"- 去重后文章数：{run_summary.deduped_articles}",
        f"- 聚类主题数：{run_summary.topic_clusters}",
        "",
    ]
    for idx, c in enumerate(clusters, start=1):
        lines.append(f"## Topic {idx}｜{c.topic_title}")
        lines.append(f"**事件总结：** {c.event_summary}  ")
        lines.append(f"**战略信号：** {c.strategic_signal}")
        lines.append("")
        lines.append("### 相关文章")
        for a in c.supporting_articles:
            lines.append(f"- **{a['title']}**")
            lines.append(f"  - **摘要：** {a['article_summary_zh']}")
            lines.append(f"  - **来源：** {a['source_link_markdown']}")
            lines.append("")
    return "\n".join(lines).strip() + "\n"




def merge_same_title_topics(clusters: List[TopicCluster]) -> List[TopicCluster]:
    merged: List[TopicCluster] = []
    by_title: dict[str, TopicCluster] = {}
    for c in clusters:
        key = (c.topic_title or "").strip().lower()
        if not key:
            merged.append(c)
            continue
        if key not in by_title:
            by_title[key] = c
            merged.append(c)
            continue
        base = by_title[key]
        base.article_count += c.article_count
        base.sources = sorted(list(set(base.sources + c.sources)))
        base.topic_keywords = list(dict.fromkeys(base.topic_keywords + c.topic_keywords))[:8]
        base.supporting_articles = (base.supporting_articles + c.supporting_articles)
        if c.topic_priority_score > base.topic_priority_score:
            base.topic_priority_score = c.topic_priority_score
        if c.cluster_confidence_score > base.cluster_confidence_score:
            base.cluster_confidence_score = c.cluster_confidence_score
        if c.event_summary and c.event_summary not in (base.event_summary or ""):
            base.event_summary = (base.event_summary + "；" + c.event_summary).strip("；")
        if c.strategic_signal and c.strategic_signal not in (base.strategic_signal or ""):
            base.strategic_signal = (base.strategic_signal + "；" + c.strategic_signal).strip("；")
    return merged


def render_html_fragment(run_summary: RunSummary, clusters: List[TopicCluster]) -> str:
    selected = sorted(clusters, key=lambda c: (c.topic_priority_score, c.article_count), reverse=True)
    selected = merge_same_title_topics(selected)
    selected = sorted(selected, key=lambda c: (c.topic_priority_score, c.article_count), reverse=True)[:4]
    if not selected:
        return (
            "<table role='presentation' width='100%' cellspacing='0' cellpadding='0' style='margin-top:28px'>"
            "<tr><td style='background:#FFFFFF;border:1px solid #E5E7EB;border-radius:16px;padding:24px;box-shadow:0 8px 28px rgba(15,23,42,0.06)'>"
            "<div style='font-size:24px;font-weight:700;color:#111827;margin-bottom:8px'>本周 AI 官方信号图谱</div>"
            "<div style='font-size:16px;line-height:1.7;color:#4B5563'>过去7天未形成可用于管理层判断的稳定主题。</div>"
            "</td></tr></table>"
        )

    weekly_judgment = selected[0].event_summary

    def theme_lead(c: TopicCluster) -> str:
        return c.strategic_signal or ""

    def format_summary_lines(text: str) -> str:
        t = escape((text or "").strip())
        t = t.replace("核心内容：", "<strong>核心内容：</strong>")
        t = t.replace(" 关键信号：", "<br/><strong>关键信号：</strong>")
        t = t.replace("  涉及主体：", "<br/><strong>涉及主体：</strong>")
        t = t.replace(" 涉及主体：", "<br/><strong>涉及主体：</strong>")
        return t

    def pick_supporting_articles(items: list[dict], limit: int = 6) -> list[dict]:
        picked: list[dict] = []
        used: set[str] = set()
        for a in items:
            inst = str(a.get("institution_name", "")).strip().lower()
            if inst and inst not in used:
                picked.append(a)
                used.add(inst)
            if len(picked) >= limit:
                return picked
        for a in items:
            if a not in picked:
                picked.append(a)
            if len(picked) >= limit:
                break
        return picked

    # target total news cards in weekly section: 7-12 when enough data
    total_available = sum(len(c.supporting_articles) for c in selected)
    target_total = min(12, max(7, total_available)) if total_available >= 7 else total_available
    per_theme_quota = {i: 1 for i in range(len(selected))}
    remaining = max(0, target_total - len(selected))
    idx = 0
    while remaining > 0 and selected:
        i = idx % len(selected)
        if per_theme_quota[i] < len(selected[i].supporting_articles):
            per_theme_quota[i] += 1
            remaining -= 1
        idx += 1
        if idx > 400:
            break

    theme_blocks = []
    for i, c in enumerate(selected):
        article_cards = []
        for a in pick_supporting_articles(c.supporting_articles, limit=per_theme_quota.get(i, 1)):
            article_cards.append(
                f"""
                <tr><td style='padding:0 0 10px 0'>
                  <table role='presentation' width='100%' cellspacing='0' cellpadding='0' style='background:#FFFFFF;border:1px solid #E5E7EB;border-radius:12px;box-shadow:0 1px 6px rgba(15,23,42,0.03)'>
                    <tr><td style='padding:14px 14px 12px'>
                      <div style='font-size:19px;line-height:1.45;font-weight:700;color:#111827;margin-bottom:6px'>{escape(a.get('title',''))}</div>
                      <div style='font-size:16px;line-height:1.7;color:#111827;margin-bottom:8px'>{format_summary_lines(a.get('article_summary_zh',''))}</div>
                      <div style='font-size:13px;line-height:1.6;color:#4B5563'>来源：<a href='{escape(a.get('url',''))}' style='color:#2563EB;text-decoration:none'>@{escape(a.get('institution_name','官方来源'))}（原文链接）</a></div>
                    </td></tr>
                  </table>
                </td></tr>
                """
            )

        theme_blocks.append(
            f"""
            <tr><td style='padding:0 0 14px 0'>
              <table role='presentation' width='100%' cellspacing='0' cellpadding='0' style='background:#F8FAFC;border:1px solid #E5E7EB;border-radius:14px;box-shadow:0 2px 10px rgba(15,23,42,0.03)'>
                <tr><td style='padding:16px 16px 10px'>
                  <div style='font-size:19px;line-height:1.4;font-weight:700;color:#111827;margin-bottom:4px'>{escape(c.topic_title)}</div>
                  <div style='font-size:16px;line-height:1.7;color:#4B5563;margin-bottom:10px'>{escape(theme_lead(c))}</div>
                  <table role='presentation' width='100%' cellspacing='0' cellpadding='0'>
                    {''.join(article_cards)}
                  </table>
                </td></tr>
              </table>
            </td></tr>
            """
        )

    return f"""
    <table role='presentation' width='100%' cellspacing='0' cellpadding='0' style='margin-top:32px'>
      <tr><td style='background:#FFFFFF;border:1px solid #E5E7EB;border-radius:16px;padding:24px'>
        <div style='font-size:13px;font-weight:600;color:#2563EB;letter-spacing:.06em;text-transform:uppercase;margin-bottom:8px;text-align:center'>Weekly Brief</div>
        <div style='font-size:28px;line-height:1.25;font-weight:700;color:#111827;margin-bottom:10px;text-align:center'>本周 AI 官方信号图谱</div>
        <div style='font-size:17px;line-height:1.7;color:#4B5563;margin-bottom:14px;text-align:center'>来自 AI 大厂与投资机构官网的主题归纳</div>
        <div style='background:#EFF6FF;border:1px solid #DBEAFE;border-radius:12px;padding:12px 14px;margin-bottom:16px'>
          <div style='font-size:18px;font-weight:700;color:#111827;margin-bottom:6px'>本周判断</div>
          <div style='font-size:16px;line-height:1.8;color:#111827'>{escape(weekly_judgment)}</div>
        </div>
        <table role='presentation' width='100%' cellspacing='0' cellpadding='0'>
          {''.join(theme_blocks)}
        </table>
      </td></tr>
    </table>
    """.strip()


def render_html(run_summary: RunSummary, clusters: List[TopicCluster]) -> str:
    hero = _report_hero(run_summary, clusters)
    summary = _summary_stats(run_summary, clusters)
    sections = "".join([_report_section(i, c) for i, c in enumerate(clusters, start=1)])

    return f"""
<!doctype html>
<html lang='zh-CN'>
<head>
  <meta charset='utf-8' />
  <meta name='viewport' content='width=device-width, initial-scale=1' />
  <title>过去一周 AI 官方动态聚类周报</title>
  <style>
    :root {{
      --bg: #f4f6fa;
      --panel: #ffffff;
      --panel-soft: #f8faff;
      --text: #0f172a;
      --text-2: #334155;
      --text-3: #64748b;
      --line: #d9e2ef;
      --brand: #243b70;
      --brand-soft: #e9eef9;
      --highlight-bg: #eef3ff;
      --highlight-line: #c9d8ff;
      --shadow: 0 8px 28px rgba(15, 23, 42, 0.06);
    }}

    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: "Inter", "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      line-height: 1.7;
      -webkit-font-smoothing: antialiased;
    }}

    .container {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 26px 20px 48px;
    }}

    .hero {{
      background: linear-gradient(180deg, #f9fbff 0%, #f2f6ff 100%);
      border: 1px solid #d7e1f2;
      border-radius: 16px;
      padding: 24px 26px 22px;
      box-shadow: var(--shadow);
      margin-bottom: 16px;
    }}

    .hero-eyebrow {{
      color: var(--brand);
      font-weight: 600;
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      margin-bottom: 8px;
    }}

    .hero h1 {{
      margin: 0;
      font-size: 34px;
      font-weight: 720;
      line-height: 1.25;
      color: #101a2d;
    }}

    .hero-subtitle {{
      margin: 12px 0 0;
      color: var(--text-2);
      font-size: 16px;
      max-width: 900px;
    }}

    .hero-meta {{
      margin-top: 14px;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}

    .hero-meta span {{
      font-size: 12px;
      color: var(--text-3);
      background: rgba(255, 255, 255, 0.9);
      border: 1px solid #dde6f6;
      border-radius: 999px;
      padding: 5px 10px;
    }}

    .summary-grid {{
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 20px;
    }}

    .summary-card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 14px 14px 12px;
      box-shadow: 0 2px 10px rgba(15, 23, 42, 0.03);
      min-height: 130px;
    }}

    .summary-title {{
      font-size: 12px;
      color: var(--text-3);
      margin-bottom: 6px;
      font-weight: 600;
    }}

    .summary-value {{
      font-size: 20px;
      line-height: 1.35;
      color: #0b1a3a;
      font-weight: 700;
      margin-bottom: 7px;
      word-break: break-word;
    }}

    .summary-desc {{
      font-size: 12px;
      color: var(--text-3);
      line-height: 1.5;
    }}

    .report-section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 16px;
      box-shadow: var(--shadow);
      padding: 20px 20px 18px;
      margin-bottom: 16px;
    }}

    .section-header {{
      border-bottom: 1px solid #e4ebf7;
      padding-bottom: 12px;
      margin-bottom: 14px;
    }}

    .section-kicker {{
      font-size: 12px;
      color: var(--brand);
      font-weight: 700;
      margin-bottom: 4px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }}

    .section-header h3 {{
      margin: 0;
      font-size: 27px;
      line-height: 1.32;
      font-weight: 700;
      color: #0f1f3e;
    }}

    .meta-row {{
      margin-top: 10px;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}

    .meta-row span {{
      font-size: 12px;
      color: #4b607f;
      background: var(--panel-soft);
      border: 1px solid #dfe8f6;
      border-radius: 999px;
      padding: 5px 10px;
    }}

    .section-summary {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 10px;
      margin-bottom: 12px;
    }}

    .insight-block {{
      background: #fbfdff;
      border: 1px solid #e1eaf7;
      border-radius: 12px;
      padding: 12px 14px;
    }}

    .insight-block.highlight {{
      background: var(--highlight-bg);
      border-color: var(--highlight-line);
    }}

    .insight-block h4 {{
      margin: 0 0 5px;
      font-size: 14px;
      color: #20345e;
      font-weight: 700;
    }}

    .insight-block p {{
      margin: 0;
      font-size: 15px;
      line-height: 1.82;
      color: #1f304d;
    }}

    .chip-group {{
      margin-bottom: 12px;
    }}

    .chip {{
      display: inline-block;
      font-size: 12px;
      color: #35548b;
      background: #edf3ff;
      border: 1px solid #d5e2fb;
      border-radius: 999px;
      padding: 4px 10px;
      margin: 0 7px 7px 0;
    }}

    .event-list {{
      display: grid;
      gap: 10px;
    }}

    .event-card {{
      background: #ffffff;
      border: 1px solid #e3ebf8;
      border-radius: 12px;
      padding: 14px 14px 12px;
    }}

    .event-header h5 {{
      margin: 0;
      font-size: 19px;
      line-height: 1.45;
      color: #0f203f;
      font-weight: 680;
    }}

    .event-meta {{
      margin-top: 6px;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      color: #576b8a;
      font-size: 12px;
    }}

    .event-body {{ margin-top: 10px; }}

    .event-footer {{
      margin-top: 10px;
      display: flex;
      gap: 8px;
      align-items: center;
      font-size: 13px;
      color: #5f7394;
      border-top: 1px dashed #dbe4f3;
      padding-top: 8px;
    }}

    .event-footer .label {{
      color: #355483;
      font-weight: 600;
    }}

    .source-link {{
      color: #204c9f;
      text-decoration: none;
      word-break: break-all;
    }}

    .source-link:hover {{ text-decoration: underline; }}
    .muted {{ color: #8fa0bc; }}

    @media (max-width: 1120px) {{
      .summary-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}

    @media (max-width: 720px) {{
      .container {{ padding: 16px 12px 32px; }}
      .hero {{ padding: 18px 16px; }}
      .hero h1 {{ font-size: 28px; }}
      .section-header h3 {{ font-size: 22px; }}
      .summary-grid {{ grid-template-columns: 1fr; }}
    }}

    @media print {{
      body {{ background: #fff; }}
      .container {{ max-width: 100%; padding: 0; }}
      .hero, .summary-card, .report-section, .event-card {{ box-shadow: none; }}
      a {{ color: #1e3a8a; text-decoration: underline; }}
    }}
  </style>
</head>
<body>
  <main class='container'>
    {hero}
    {summary}
    {sections}
  </main>
</body>
</html>
""".strip() + "\n"
