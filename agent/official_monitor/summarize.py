from __future__ import annotations

import re
from collections import Counter
from typing import List

from .models import NormalizedArticle


def _clip_zh(text: str, limit: int) -> str:
    t = re.sub(r"\s+", " ", text).strip()
    return t if len(t) <= limit else t[: limit - 1] + "…"


def summarize_article_zh(article: NormalizedArticle) -> str:
    core = _clip_zh(article.title, 72)
    signal = "；".join(article.tags[:3]) if article.tags else article.signal_type
    entity = article.company_or_firm_name
    out = f"核心内容：{core}。关键信号：{signal or '原文未明确标签'}。涉及主体：{entity}。"
    return _clip_zh(out, 300)


def summarize_cluster_event_zh(cluster: List[NormalizedArticle], topic_keywords: List[str]) -> tuple[str, str]:
    titles = "；".join(a.title for a in cluster[:4])
    key = "、".join(topic_keywords[:4]) if topic_keywords else "AI产品与投资动态"
    summary = (
        f"过去一周内，该主题下多条官方内容围绕“{key}”持续更新，"
        f"集中体现为产品发布、平台能力完善或投资观点同步发声。"
        f"这些动态共同反映行业竞争重点正在从单点能力转向可落地的商业与生态推进。"
    )
    summary = _clip_zh(summary, 220)

    strategic = "信号显示行业正在加速从技术能力展示转向平台化与商业化执行。"
    if any("融资" in (a.content_text + a.title) for a in cluster):
        strategic = "投资与产业方叙事开始同频，资金与产品路线联动信号增强。"
    if any(k in key for k in ["推理", "reasoning", "多模态"]):
        strategic = "模型竞争正转向推理质量、效率和可用性，而非单纯参数规模。"
    return summary, strategic


def infer_entities(article: NormalizedArticle) -> List[str]:
    txt = article.title + " " + article.content_text[:1200]
    cands = []
    for ent in ["OpenAI", "Anthropic", "Google", "Microsoft", "NVIDIA", "AWS", "Meta", "腾讯", "百度", "红杉", "高瓴", "启明"]:
        if ent.lower() in txt.lower():
            cands.append(ent)
    if not cands:
        cands = [article.company_or_firm_name]
    return cands[:6]
