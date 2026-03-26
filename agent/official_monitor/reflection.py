"""Post-pipeline self-reflection.

After official_monitor produces its final output, this module asks the LLM
to compare **raw fetched articles** (pre-cleaning) against **kept articles**
(post-cleaning) and evaluate:

1. Were important articles missed by the filters?
2. Were low-quality / irrelevant articles incorrectly kept?
3. Concrete suggestions for tuning scoring.yaml parameters.

The result is a structured dict stored in ``run_history.jsonl``.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from .models import NormalizedArticle, TopicCluster

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from config import cfg


def _llm_client():
    try:
        from openai import OpenAI
    except ImportError:
        return None
    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if not api_key:
        return None
    base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
    return OpenAI(api_key=api_key, base_url=base_url)


def _summarize_article_brief(a: NormalizedArticle) -> str:
    return f"[{a.company_or_firm_name}] {a.title} | signal={a.signal_type} | importance={a.importance_score:.0f}"


def reflect_on_filtering(
    raw_articles: List[NormalizedArticle],
    kept_articles: List[NormalizedArticle],
    clusters: List[TopicCluster],
) -> Optional[Dict[str, Any]]:
    """Ask the LLM to evaluate filtering quality.

    Returns a structured dict with:
      - potentially_missed: list of article titles that may have been wrongly dropped
      - potentially_bad: list of article titles that may have been wrongly kept
      - suggestions: list of concrete tuning suggestions
      - overall_score: 1-10 rating of filtering quality
    """
    client = _llm_client()
    if client is None:
        print("[REFLECTION] skipped — no LLM client available")
        return None

    kept_titles = {a.title for a in kept_articles}
    dropped = [a for a in raw_articles if a.title not in kept_titles]

    # Build compact summaries
    kept_lines = "\n".join(_summarize_article_brief(a) for a in kept_articles[:30])
    dropped_lines = "\n".join(_summarize_article_brief(a) for a in dropped[:50])
    cluster_lines = "\n".join(
        f"- {c.topic_title}: {c.article_count} articles, priority={c.topic_priority_score:.1f}"
        for c in clusters
    )

    prompt = f"""你是一位AI行业资深分析师，负责审核一个自动化新闻筛选系统的输出质量。

该系统的目标是：从AI大厂官方新闻和投资机构动态中，筛选出具有「行业颠覆性」的硬新闻——
包括：重大产品发布、核心功能上线、战略性收购/合作、大额融资（含被投企业、金额、赛道）、
合伙人级人事变动。排除一切软性内容（行业展望、应用案例、教程、愿景演讲、日常运营）。

本次运行数据：
- 总抓取文章数: {len(raw_articles)}
- 清洗后保留: {len(kept_articles)}
- 被过滤掉: {len(dropped)}

═══ 保留的文章（已通过筛选）═══
{kept_lines}

═══ 被过滤掉的文章（未通过筛选）═══
{dropped_lines}

═══ 最终聚类主题 ═══
{cluster_lines}

请严格按以下JSON格式输出你的评估（不要输出其他内容）：
{{
  "overall_score": <1-10整数，10=筛选完美>,
  "potentially_missed": [
    {{"title": "被漏掉的文章标题", "reason": "为什么这篇应该被保留"}}
  ],
  "potentially_bad": [
    {{"title": "不该保留的文章标题", "reason": "为什么这篇应该被过滤"}}
  ],
  "filter_suggestions": [
    "具体的参数调整建议，例如: 建议在STRONG_SIGNAL_KEYWORDS中增加'xxx'关键词"
  ],
  "coverage_gaps": [
    "筛选覆盖的盲区，例如: 缺少对xxx类型新闻的捕获"
  ]
}}"""

    model = os.environ.get("GEMINI_MODEL", "gemini-3.0-flash-preview")
    try:
        resp = client.chat.completions.create(
            model=model,
            max_tokens=cfg("llm.max_tokens", 65536),
            messages=[{"role": "user", "content": prompt}],
        )
        text = (resp.choices[0].message.content or "").strip()
        # Extract JSON from possible markdown code fences
        if "```" in text:
            import re
            m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.S)
            if m:
                text = m.group(1).strip()
        result = json.loads(text)
        print(f"[REFLECTION] filtering quality score: {result.get('overall_score', '?')}/10")
        print(f"[REFLECTION] potentially missed: {len(result.get('potentially_missed', []))} articles")
        print(f"[REFLECTION] potentially bad: {len(result.get('potentially_bad', []))} articles")
        print(f"[REFLECTION] suggestions: {len(result.get('filter_suggestions', []))}")
        return result
    except Exception as exc:
        print(f"[REFLECTION] LLM reflection failed: {exc}")
        return {"error": str(exc)}
