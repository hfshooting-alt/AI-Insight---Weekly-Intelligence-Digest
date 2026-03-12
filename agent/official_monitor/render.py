from __future__ import annotations

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


def render_markdown(run_summary: RunSummary, clusters: List[TopicCluster]) -> str:
    lines = [
        "# 过去一周 AI 官方动态聚类",
        "",
        f"- 统计时间范围：过去7天（滚动）",
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


def render_html(run_summary: RunSummary, clusters: List[TopicCluster]) -> str:
    rows = [
        ("统计时间范围", "过去7天（滚动）"),
        ("覆盖来源数", str(run_summary.covered_sources)),
        ("抓取文章数", str(run_summary.fetched_articles)),
        ("去重后文章数", str(run_summary.deduped_articles)),
        ("聚类主题数", str(run_summary.topic_clusters)),
    ]
    stat_html = "".join(
        f"<div class='stat'><div class='k'>{k}</div><div class='v'>{v}</div></div>" for k, v in rows
    )

    topic_blocks = []
    for idx, c in enumerate(clusters, start=1):
        article_cards = []
        for a in c.supporting_articles:
            article_cards.append(
                """
                <div class='article'>
                  <div class='article-title'>{title}</div>
                  <div class='article-summary'>{summary}</div>
                  <div class='article-source'>来源：<a href='{url}' target='_blank' rel='noopener'>{source}</a></div>
                </div>
                """.format(title=a["title"], summary=a["article_summary_zh"], url=a.get('url') or '#', source=a["source_link_markdown"])
            )

        topic_blocks.append(
            """
            <section class='topic'>
              <div class='topic-head'>
                <div class='topic-index'>Topic {idx}</div>
                <h2>{title}</h2>
              </div>
              <div class='chip-row'>
                {chips}
              </div>
              <div class='event-summary'><b>事件总结：</b>{event_summary}</div>
              <div class='strategic'><b>战略信号：</b>{strategic_signal}</div>
              <div class='articles'>{articles}</div>
            </section>
            """.format(
                idx=idx,
                title=c.topic_title,
                chips="".join(f"<span class='chip'>{kw}</span>" for kw in c.topic_keywords[:6]),
                event_summary=c.event_summary,
                strategic_signal=c.strategic_signal,
                articles="".join(article_cards),
            )
        )

    return f"""
<!doctype html>
<html lang='zh-CN'>
<head>
  <meta charset='utf-8' />
  <meta name='viewport' content='width=device-width, initial-scale=1' />
  <title>过去一周 AI 官方动态聚类</title>
  <style>
    :root {{
      --bg:#060b16; --panel:#0d1528; --text:#dbe7ff; --muted:#9eb2d8; --line:#1e3159;
      --accent:#56b6ff; --accent2:#7c5cff;
    }}
    body {{ margin:0; font-family:Inter,Segoe UI,PingFang SC,Arial,sans-serif; color:var(--text);
      background:radial-gradient(900px 420px at 8% -5%, rgba(86,182,255,.25), transparent 42%),
                 radial-gradient(800px 380px at 95% -10%, rgba(124,92,255,.2), transparent 40%), var(--bg);
      line-height:1.72; }}
    .wrap {{ max-width:1080px; margin:0 auto; padding:28px 18px 42px; }}
    h1 {{ margin:0 0 14px; font-size:38px; letter-spacing:.4px; }}
    .subtitle {{ color:var(--muted); margin-bottom:18px; }}
    .stats {{ display:grid; grid-template-columns: repeat(5,minmax(140px,1fr)); gap:10px; margin-bottom:18px; }}
    .stat {{ background:linear-gradient(180deg,#0e1a33,#0b1428); border:1px solid var(--line); border-radius:12px; padding:10px 12px; }}
    .stat .k {{ color:var(--muted); font-size:12px; }}
    .stat .v {{ color:#f2f7ff; font-size:20px; font-weight:800; margin-top:4px; }}
    .topic {{ background:linear-gradient(180deg,rgba(13,21,40,.95),rgba(10,16,30,.95)); border:1px solid var(--line); border-radius:16px; padding:16px 16px 14px; margin:14px 0 18px; box-shadow:0 10px 30px rgba(0,0,0,.3); }}
    .topic-head {{ display:flex; align-items:baseline; gap:12px; }}
    .topic-index {{ color:var(--accent); font-weight:700; font-size:14px; }}
    .topic h2 {{ margin:0; font-size:24px; line-height:1.35; }}
    .chip-row {{ margin:10px 0 10px; }}
    .chip {{ display:inline-block; margin:0 8px 8px 0; padding:4px 10px; border-radius:999px; background:#102242; border:1px solid #234070; color:#b9d6ff; font-size:12px; }}
    .event-summary, .strategic {{ margin-top:8px; color:#d8e6ff; }}
    .strategic {{ padding:10px 12px; border-radius:10px; background:#0c203f; border:1px solid #20406f; }}
    .articles {{ margin-top:12px; display:grid; gap:10px; }}
    .article {{ border:1px solid #223b67; border-radius:12px; padding:12px; background:#0a1730; }}
    .article-title {{ font-size:17px; font-weight:750; color:#ecf4ff; margin-bottom:6px; }}
    .article-summary {{ color:#d5e4ff; }}
    .article-source {{ margin-top:7px; color:#9fb7dd; font-size:14px; }}
    a {{ color:#83ccff; text-decoration:none; }}
    a:hover {{ text-decoration:underline; }}
    @media (max-width:960px) {{ .stats {{ grid-template-columns: repeat(2,minmax(140px,1fr)); }} h1 {{font-size:30px;}} }}
  </style>
</head>
<body>
  <div class='wrap'>
    <h1>过去一周 AI 官方动态聚类</h1>
    <div class='subtitle'>事件优先聚类 · 官方信源 · 高信息密度周报</div>
    <div class='stats'>{stat_html}</div>
    {''.join(topic_blocks)}
  </div>
</body>
</html>
""".strip() + "\n"
