from __future__ import annotations

import json
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
