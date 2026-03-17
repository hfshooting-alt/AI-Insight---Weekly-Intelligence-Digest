from __future__ import annotations

import datetime as dt
from collections import Counter
from typing import Dict, List

from .models import NormalizedArticle

CLUSTER_KEYWORDS = [
    "reasoning", "multimodal", "agent", "inference", "compute", "gpu", "api", "enterprise", "robotics",
    "人工智能", "大模型", "智能体", "推理", "多模态", "算力", "芯片", "云", "开发者平台", "融资", "并购",
]


def _token_set(article: NormalizedArticle) -> set[str]:
    txt = (article.title + " " + article.content_text[:1500]).lower()
    toks = {k for k in CLUSTER_KEYWORDS if k.lower() in txt}
    toks.update({t.lower() for t in article.tags})
    return toks


def _date(article: NormalizedArticle) -> dt.datetime:
    return dt.datetime.fromisoformat(article.published_at.replace('Z', '+00:00'))


def _similar(a: NormalizedArticle, b: NormalizedArticle) -> float:
    ta, tb = _token_set(a), _token_set(b)
    inter = len(ta & tb)
    union = len(ta | tb) or 1
    j = inter / union
    days = abs((_date(a) - _date(b)).days)
    time_bonus = 0.08 if days <= 2 else 0.0
    same_signal = 0.05 if a.signal_type == b.signal_type else 0.0
    return j + time_bonus + same_signal


def cluster_articles(items: List[NormalizedArticle]) -> List[List[NormalizedArticle]]:
    clusters: List[List[NormalizedArticle]] = []
    for it in sorted(items, key=lambda x: x.importance_score, reverse=True):
        placed = False
        for c in clusters:
            sim = max(_similar(it, e) for e in c)
            if sim >= 0.42:
                c.append(it)
                placed = True
                break
        if not placed:
            clusters.append([it])

    refined: List[List[NormalizedArticle]] = []
    for c in clusters:
        refined.extend(_split_oversized_cluster(c, max_cluster_size=4, strict_sim=0.48))

    # keep tiny weak clusters separate; do not force-merge unrelated events.
    return [sorted(c, key=lambda x: x.importance_score, reverse=True) for c in refined if c]




def _split_oversized_cluster(cluster: List[NormalizedArticle], max_cluster_size: int = 4, strict_sim: float = 0.48) -> List[List[NormalizedArticle]]:
    if len(cluster) <= max_cluster_size:
        return [cluster]
    parts: List[List[NormalizedArticle]] = []
    for it in sorted(cluster, key=lambda x: x.importance_score, reverse=True):
        placed = False
        for p in parts:
            sim = max(_similar(it, e) for e in p)
            if sim >= strict_sim and len(p) < max_cluster_size:
                p.append(it)
                placed = True
                break
        if not placed:
            parts.append([it])
    return parts

def build_topic_meta(cluster: List[NormalizedArticle], idx: int) -> Dict[str, object]:
    tokens = Counter()
    signal_counter = Counter()
    institutions = Counter()
    for a in cluster:
        for t in _token_set(a):
            tokens[t] += 1
        signal_counter[(a.signal_type or "other").lower()] += 1
        inst = (a.company_or_firm_name or "").strip()
        if inst:
            institutions[inst] += 1

    top_keywords = [k for k, _ in tokens.most_common(8)]
    dominant_signal = signal_counter.most_common(1)[0][0] if signal_counter else "other"

    signal_title_map = {
        "product_release": "产品发布与平台升级",
        "investment_signal": "投资与资本动态",
        "m&a": "并购与资本整合",
        "partnership": "生态合作与商业落地",
        "research_update": "技术能力与研发进展",
    }
    stem = signal_title_map.get(dominant_signal, "AI产业关键动态")

    stop_keywords = {
        "api", "agent", "enterprise", "reasoning", "multimodal", "inference", "compute", "gpu", "cloud",
        "智能体", "推理", "多模态", "算力", "云", "融资", "并购", "product_release", "partnership", "investment_signal",
    }
    detail_kws = [k for k in top_keywords if k and k.lower() not in stop_keywords][:3]
    top_insts = [k for k, _ in institutions.most_common(2)]

    if detail_kws:
        title = f"{stem}：{'、'.join(detail_kws)}"
    elif top_insts:
        title = f"{stem}：{'、'.join(top_insts)}"
    else:
        title = stem

    return {
        "topic_cluster_id": f"topic_{idx:03d}",
        "topic_title": title,
        "topic_keywords": top_keywords[:8],
        "cluster_confidence_score": round(min(0.95, 0.45 + 0.08 * len(cluster)), 2),
        "topic_priority_score": round(min(100.0, sum(a.importance_score for a in cluster) / max(len(cluster), 1)), 1),
    }
