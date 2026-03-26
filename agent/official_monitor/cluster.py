from __future__ import annotations

import datetime as dt
from collections import Counter
from typing import Dict, List

from .models import NormalizedArticle

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from config import cfg

CLUSTER_KEYWORDS = [
    "reasoning", "multimodal", "agent", "inference", "compute", "gpu", "api", "enterprise", "robotics",
    "人工智能", "大模型", "智能体", "推理", "多模态", "算力", "芯片", "云", "开发者平台", "融资", "并购",
]


def _token_set(article: NormalizedArticle) -> set[str]:
    pivot = article.summary or ""
    txt = (pivot + " " + article.title + " " + article.content_text[:1200]).lower()
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
    time_bonus = cfg("cluster.time_bonus", 0.08) if days <= 2 else 0.0
    same_signal = cfg("cluster.same_signal_bonus", 0.05) if a.signal_type == b.signal_type else 0.0
    return j + time_bonus + same_signal


def cluster_articles(items: List[NormalizedArticle]) -> List[List[NormalizedArticle]]:
    threshold = cfg("cluster.initial_threshold", 0.42)
    max_size = cfg("cluster.max_cluster_size", 4)
    strict_sim = cfg("cluster.strict_threshold", 0.48)

    clusters: List[List[NormalizedArticle]] = []
    for it in sorted(items, key=lambda x: x.importance_score, reverse=True):
        placed = False
        for c in clusters:
            sim = max(_similar(it, e) for e in c)
            if sim >= threshold:
                c.append(it)
                placed = True
                break
        if not placed:
            clusters.append([it])

    refined: List[List[NormalizedArticle]] = []
    for c in clusters:
        refined.extend(_split_oversized_cluster(c, max_cluster_size=max_size, strict_sim=strict_sim))

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

    max_kw = cfg("cluster.max_keywords", 8)
    top_keywords = [k for k, _ in tokens.most_common(max_kw)]
    trend_buckets = {
        "产品化与企业落地": ["platform", "api", "enterprise", "deployment", "产品", "发布", "platform"],
        "算力基础设施升级": ["gpu", "compute", "cloud", "芯片", "算力", "inference"],
        "资本与并购整合": ["capital", "investment", "financing", "融资", "投资", "并购", "acquisition"],
        "生态合作与渠道扩展": ["ecosystem", "partnership", "collaboration", "合作", "生态"],
        "具身智能与机器人应用": ["robotics", "robot", "具身", "机器人", "simulation"],
    }
    bucket_score = Counter()
    token_blob = " ".join(top_keywords)
    for k, kws in trend_buckets.items():
        for kw in kws:
            if kw.lower() in token_blob.lower():
                bucket_score[k] += 1
    dominant_signal = signal_counter.most_common(1)[0][0] if signal_counter else "other"

    if bucket_score:
        title = bucket_score.most_common(1)[0][0]
    elif dominant_signal in {"investment_signal", "m&a"}:
        title = "资本与并购整合"
    elif dominant_signal == "partnership":
        title = "生态合作与渠道扩展"
    else:
        title = "AI行业产品化与落地进展"

    generic = {
        "agent", "api", "platform", "enterprise", "capital", "ecosystem", "compute", "robotics",
        "投资", "融资", "并购", "合作", "算力", "平台", "发布", "sig:product_release", "sig:investment_signal", "sig:partnership",
    }
    dis = [k for k in top_keywords if k and k.lower() not in generic][:2]
    if dis:
        title = f"{title}｜{'/'.join(dis)}"

    org_count = len(institutions)
    multi_org = cfg("cluster.multi_org_threshold", 3)
    if org_count >= multi_org:
        title = f"{title}（多机构共振）"

    conf_base = cfg("cluster.confidence_base", 0.45)
    conf_per = cfg("cluster.confidence_per_article", 0.08)
    conf_cap = cfg("cluster.confidence_cap", 0.95)

    return {
        "topic_cluster_id": f"topic_{idx:03d}",
        "topic_title": title,
        "topic_keywords": top_keywords[:max_kw],
        "cluster_confidence_score": round(min(conf_cap, conf_base + conf_per * len(cluster)), 2),
        "topic_priority_score": round(min(100.0, sum(a.importance_score for a in cluster) / max(len(cluster), 1)), 1),
    }
