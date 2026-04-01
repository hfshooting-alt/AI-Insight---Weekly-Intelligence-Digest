from __future__ import annotations

import logging
import os
import re
from typing import List, Tuple

from .models import NormalizedArticle

logger = logging.getLogger(__name__)


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


GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEFAULT_MODEL = "gemini-3.0-flash-preview"


def _llm_client():
    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from openai import OpenAI
        return OpenAI(api_key=api_key, base_url=GEMINI_BASE_URL)
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
    model = os.environ.get("OFFICIAL_MONITOR_SUMMARY_MODEL", os.environ.get("GEMINI_MODEL", DEFAULT_MODEL))
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
        resp = client.chat.completions.create(model=model, max_tokens=65536, messages=[{"role": "user", "content": prompt}])
        text = (resp.choices[0].message.content or "") if resp.choices else ""
    except Exception:
        logger.warning("summarize_with_llm failed", exc_info=True)
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


def summarize_article_with_llm(article: NormalizedArticle) -> Tuple[str, bool] | None:
    """Summarise an article and judge its relevance in a single LLM call.

    Returns ``(summary_text, keep)`` where *keep* is True when the article
    passes the relevance bar, or ``None`` on failure.
    """
    client = _llm_client()
    if client is None:
        return None
    model = os.environ.get("OFFICIAL_MONITOR_SUMMARY_MODEL", os.environ.get("GEMINI_MODEL", DEFAULT_MODEL))
    body = _excerpt(article.content_text, 1200)
    prompt = (
        "你是一位资深 AI 产业投研分析师。请阅读下面这篇来自官方信源的文章，完成两件事：\n\n"
        "## 1. 判断是否值得收录（输出 VERDICT 行）\n"
        "我们追踪的是 AI 行业真正有份量的一手动态，包括：\n"
        "  ✅ 新模型 / 新产品发布（如 GPT-5、Claude 4、Llama 4 等）\n"
        "  ✅ 重大功能上线或平台能力升级（如新 API、新 SDK、重大架构变更）\n"
        "  ✅ 深度技术博客或研究论文（有原创方法论、实验数据、技术细节）\n"
        "  ✅ 战略性收购、合作或生态整合\n"
        "  ✅ 实质性融资（含企业名称、金额、赛道）\n"
        "  ✅ 高管 / 合伙人级别人事变动\n"
        "  ✅ 长篇深度播客、对谈（有实质性技术或战略讨论内容）\n\n"
        "以下内容不收录：\n"
        "  ❌ 入门教程、名词科普（如'什么是 RAG''什么是关系数据模型'）\n"
        "  ❌ 行业趋势展望、愿景演讲、年度回顾（没有具体事件或数据）\n"
        "  ❌ 客户案例、应用故事、营销软文\n"
        "  ❌ 日常运营公告、维护通知、招聘信息\n"
        "  ❌ 转载、聚合或纯链接页面\n\n"
        "如果文章符合收录标准，输出：VERDICT: KEEP\n"
        "如果不符合，输出：VERDICT: SKIP\n\n"
        "## 2. 生成中文摘要（不超过 250 字）\n"
        "格式：’核心内容：... 关键信号：... 涉及主体：...’\n"
        "如果判断为 SKIP，关键信号写’无’即可。\n"
        "不要省略号，不要编造。\n\n"
        f"标题：{article.title}\n机构：{article.company_or_firm_name}\n正文：{body}"
    )
    try:
        resp = client.chat.completions.create(model=model, max_tokens=65536, messages=[{"role": "user", "content": prompt}])
        text = _normalize_text((resp.choices[0].message.content or "") if resp.choices else "")
    except Exception:
        logger.warning("summarize_article_with_llm failed for %s", article.title, exc_info=True)
        return None
    if not text:
        return None

    # Parse verdict
    keep = True
    if "VERDICT: SKIP" in text or "VERDICT:SKIP" in text:
        keep = False
    # Strip the VERDICT line from the summary text
    summary = re.sub(r"VERDICT:\s*(?:KEEP|SKIP)\s*", "", text).strip()
    return _clip_zh(summary, 300), keep


def infer_entities(article: NormalizedArticle) -> List[str]:
    txt = article.title + " " + article.content_text[:1200]
    cands = []
    for ent in ["OpenAI", "Anthropic", "Google", "Microsoft", "NVIDIA", "AWS", "Meta", "腾讯", "百度", "红杉", "高瓴", "启明"]:
        if ent.lower() in txt.lower():
            cands.append(ent)
    if not cands:
        cands = [article.company_or_firm_name]
    return cands[:6]



def summarize_cluster_bundle_with_llm(cluster: List[NormalizedArticle], topic_keywords: List[str]) -> Tuple[str, str, str] | None:
    """Use LLM to generate trend-level topic title + intro summary + strategic signal."""
    client = _llm_client()
    if client is None:
        return None
    model = os.environ.get("OFFICIAL_MONITOR_SUMMARY_MODEL", os.environ.get("GEMINI_MODEL", DEFAULT_MODEL))
    bullets = []
    for a in cluster[:10]:
        body = _excerpt(a.article_summary_zh or a.content_text, 220)
        bullets.append(f"- 机构：{a.company_or_firm_name}\n  标题：{a.title}\n  结构化：{body}")
    prompt = (
        "你是投行研究总监。请基于以下事件输出三行中文，务必客观、精炼、可决策：\n"
        "第一行：以’话题标题：’开头（<=24字），必须是行业趋势，不要写某家公司名称。\n"
        "第二行：以’事件引言：’开头（<=120字），总结本周跨机构共同动作。\n"
        "第三行：以’战略信号：’开头（<=70字），给出商业含义。\n"
        "严格过滤标准：只保留新模型/新产品发布、重大功能上线、战略收购与合作、实质性融资、"
        "合伙人级人事变动。排除行业展望、应用案例、技术教程、愿景演讲、日常运营。"
        "如果事件不符合上述标准，在事件引言中注明’本周无核心异动’。\n"
        "禁止空话，禁止编造。\n\n"
        f"关键词：{','.join(topic_keywords[:8])}\n" + "\n".join(bullets)
    )
    try:
        resp = client.chat.completions.create(model=model, max_tokens=65536, messages=[{"role": "user", "content": prompt}])
        text = (resp.choices[0].message.content or "") if resp.choices else ""
    except Exception:
        logger.warning("summarize_cluster_bundle_with_llm failed", exc_info=True)
        return None

    title = intro = signal = ""
    for ln in [x.strip() for x in text.splitlines() if x.strip()]:
        if ln.startswith("话题标题："):
            title = ln.split("：", 1)[1].strip()
        elif ln.startswith("事件引言："):
            intro = ln.split("：", 1)[1].strip()
        elif ln.startswith("战略信号："):
            signal = ln.split("：", 1)[1].strip()
    if title and intro:
        return _clip_zh(title, 30), _clip_zh(intro, 140), _clip_zh(signal or "资本、产品与生态动作正在同步加速。", 90)
    return None
