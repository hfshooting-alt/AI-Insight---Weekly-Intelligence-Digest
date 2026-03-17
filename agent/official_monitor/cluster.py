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
    toks.add(article.signal_type)
    return toks


def _date(article: NormalizedArticle) -> dt.datetime:
    return dt.datetime.fromisoformat(article.published_at.replace('Z', '+00:00'))


def _similar(a: NormalizedArticle, b: NormalizedArticle) -> float:
    ta, tb = _token_set(a), _token_set(b)
    inter = len(ta & tb)
    union = len(ta | tb) or 1
    j = inter / union
    days = abs((_date(a) - _date(b)).days)
    time_bonus = 0.2 if days <= 2 else 0.0
    same_signal = 0.15 if a.signal_type == b.signal_type else 0.0
    return j + time_bonus + same_signal


def cluster_articles(items: List[NormalizedArticle]) -> List[List[NormalizedArticle]]:
    clusters: List[List[NormalizedArticle]] = []
    for it in sorted(items, key=lambda x: x.importance_score, reverse=True):
        placed = False
        for c in clusters:
            sim = max(_similar(it, e) for e in c)
            if sim >= 0.32:
                c.append(it)
                placed = True
                break
        if not placed:
            clusters.append([it])

    # merge tiny weak clusters
    merged: List[List[NormalizedArticle]] = []
    weak: List[NormalizedArticle] = []
    for c in clusters:
        if len(c) == 1 and c[0].importance_score < 55:
            weak.extend(c)
        else:
            merged.append(c)
    if weak:
        if merged:
            merged[-1].extend(weak)
        else:
            merged.append(weak)
    return merged


def build_topic_meta(cluster: List[NormalizedArticle], idx: int) -> Dict[str, object]:
    tokens = Counter()
    signal_counter = Counter()
    for a in cluster:
        for t in _token_set(a):
            tokens[t] += 1
        signal_counter[(a.signal_type or "other").lower()] += 1
    top_keywords = [k for k, _ in tokens.most_common(8)]
    dominant_signal = signal_counter.most_common(1)[0][0] if signal_counter else "other"

    if dominant_signal in {"investment_signal", "m&a"} or any(k in top_keywords for k in ["融资", "investment", "financing", "并购"]):
        title = "资本与并购主导的AI产业事件"
    elif any(k in top_keywords for k in ["agent", "智能体", "api", "开发者平台"]):
        title = "Agent与平台能力发布密集出现"
    elif any(k in top_keywords for k in ["reasoning", "推理", "multimodal", "多模态"]):
        title = "推理与多模态能力迭代加速"
    elif any(k in top_keywords for k in ["gpu", "芯片", "compute", "云"]):
        title = "算力与云基础设施协同升级"
    elif dominant_signal == "partnership":
        title = "生态合作与商业落地协同推进"
    else:
        title = "AI产品化与商业化进展"

    lead_kw = top_keywords[0] if top_keywords else "综合"
    if lead_kw and lead_kw not in title and len(lead_kw) <= 12:
        title = f"{title}（侧重{lead_kw}）"

    return {
        "topic_cluster_id": f"topic_{idx:03d}",
        "topic_title": title,
        "topic_keywords": top_keywords[:8],
        "cluster_confidence_score": round(min(0.95, 0.45 + 0.08 * len(cluster)), 2),
        "topic_priority_score": round(min(100.0, sum(a.importance_score for a in cluster) / max(len(cluster), 1)), 1),
    }
