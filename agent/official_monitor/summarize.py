from __future__ import annotations

import os
import re
from typing import List, Tuple

from .models import NormalizedArticle


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _clip_zh(text: str, limit: int) -> str:
    t = _normalize_text(text)
    if len(t) <= limit:
        return t
    window = t[:limit]
    cut = max(window.rfind("。"), window.rfind("！"), window.rfind("？"), window.rfind("；"))
    if cut >= int(limit * 0.6):
        return window[: cut + 1]
    return window.rstrip("，、；：, ")


def _excerpt(text: str, limit: int) -> str:
    t = _normalize_text(text)
    if not t:
        return ""
    sentences = [x.strip() for x in re.split(r"(?<=[。！？!?])", t) if x.strip()]
    if not sentences:
        return _clip_zh(t, limit)
    out = ""
    for s in sentences:
        if len(out) + len(s) > limit:
            break
        out += s
    return out or _clip_zh(sentences[0], limit)


def _llm_client():
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from openai import OpenAI
        return OpenAI(api_key=api_key)
    except Exception:
        return None


def summarize_article_zh(article: NormalizedArticle) -> str:
    base = (article.summary or "").strip()
    core = base or _excerpt(article.content_text, 150) or _clip_zh(article.title, 100)
    signal = "；".join(article.tags[:3]) if article.tags else (article.signal_type or "event")
    entity = article.company_or_firm_name
    out = f"核心内容：{core} 关键信号：{signal}。涉及主体：{entity}。"
    return _clip_zh(out, 260)


def summarize_cluster_event_zh(cluster: List[NormalizedArticle], topic_keywords: List[str]) -> Tuple[str, str]:
    key = "、".join(topic_keywords[:4]) if topic_keywords else "AI产品与投资动态"
    text_pool = " ".join([(a.title + " " + (a.content_text or "")[:500]) for a in cluster[:8]])
    sampled = _excerpt(text_pool, 200)
    inst_cnt = len({(a.company_or_firm_name or '').strip() for a in cluster if (a.company_or_firm_name or '').strip()})
    event_cnt = len(cluster)
    lead = f"过去一周该话题汇总了{event_cnt}起官方事件（涉及{inst_cnt}家机构），主线聚焦“{key}”。"
    summary = lead + (sampled if sampled else '多家机构在产品发布、平台能力与生态合作上同步动作。')
    summary = _clip_zh(summary, 260)

    strategic = "投行视角：关注可量化的产品上线、资金流向与组织变动，噪音事件权重降至最低。"
    if any("融资" in (a.content_text + a.title) for a in cluster):
        strategic = "投资与产业方叙事开始同频，资金与产品路线联动信号增强。"
    if any(k in key for k in ["推理", "reasoning", "多模态"]):
        strategic = "模型竞争正转向推理质量、效率和可用性，而非单纯参数规模。"
    return summary, strategic


def summarize_with_llm(cluster: List[NormalizedArticle], topic_keywords: List[str]) -> Tuple[str, str] | None:
    client = _llm_client()
    if client is None:
        return None
    model = os.environ.get("OFFICIAL_MONITOR_SUMMARY_MODEL", os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))
    bullets = []
    for a in cluster[:8]:
        body = _excerpt(a.content_text, 280)
        bullets.append(f"- 标题：{a.title}\n  机构：{a.company_or_firm_name}\n  内容：{body}")
    prompt = (
        "请基于以下官方文章，输出中文两行：\n"
        "第一行以‘事件总结：’开头（<=220字）；\n"
        "第二行以‘战略信号：’开头（<=80字）。\n"
        "不要使用省略号，不要编造。\n\n"
        f"关键词：{','.join(topic_keywords[:8])}\n" + "\n".join(bullets)
    )
    try:
        resp = client.responses.create(model=model, input=prompt)
        text = getattr(resp, "output_text", "") or ""
    except Exception:
        return None
    summary, strategic = "", ""
    for ln in [x.strip() for x in text.splitlines() if x.strip()]:
        if ln.startswith("事件总结："):
            summary = ln.split("：", 1)[1].strip()
        elif ln.startswith("战略信号："):
            strategic = ln.split("：", 1)[1].strip()
    if summary:
        return _clip_zh(summary, 260), _clip_zh(strategic or "信号显示平台化与商业化进程持续加速。", 90)
    return None


def summarize_article_with_llm(article: NormalizedArticle) -> str | None:
    client = _llm_client()
    if client is None:
        return None
    model = os.environ.get("OFFICIAL_MONITOR_SUMMARY_MODEL", os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))
    body = _excerpt(article.content_text, 1200)
    prompt = (
        "请将下列官方文章总结为中文，不超过300字，结构为："
        "‘核心内容：... 关键信号：... 涉及主体：...’。"
        "不要省略号，不要编造。\n"
        f"标题：{article.title}\n机构：{article.company_or_firm_name}\n正文：{body}"
    )
    try:
        resp = client.responses.create(model=model, input=prompt)
        text = _normalize_text(getattr(resp, "output_text", "") or "")
        return _clip_zh(text, 300) if text else None
    except Exception:
        return None


def infer_entities(article: NormalizedArticle) -> List[str]:
    txt = article.title + " " + article.content_text[:1200]
    cands = []
    for ent in ["OpenAI", "Anthropic", "Google", "Microsoft", "NVIDIA", "AWS", "Meta", "腾讯", "百度", "红杉", "高瓴", "启明"]:
        if ent.lower() in txt.lower():
            cands.append(ent)
    if not cands:
        cands = [article.company_or_firm_name]
    return cands[:6]
