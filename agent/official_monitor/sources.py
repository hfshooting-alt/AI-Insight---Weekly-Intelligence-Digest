from __future__ import annotations

import json
import os
from urllib.parse import urlparse

from .models import SourceConfig

# Production registry — international sources only (AI companies + VCs)
TRUSTED_SOURCE_REGISTRY = [
  # ── OpenAI ──
  # Newsroom & /research return 403 for automated fetches; use RSS instead.
  {"source_name":"OpenAI Blog RSS","source_type":"ai_company","region":"global","official_domain":"openai.com","landing_url":"https://openai.com/blog/rss.xml","allowed_domains":["openai.com"],"candidate_paths":[],"parser_hint":"rss_feed","language":"en","priority":1,"exclude_url_patterns":["/careers"],"notes":"RSS feed — bypasses 403, captures blog+research posts"},

  # ── Anthropic ──
  {"source_name":"Anthropic Newsroom","source_type":"ai_company","region":"global","official_domain":"anthropic.com","landing_url":"https://www.anthropic.com/news","allowed_domains":["www.anthropic.com","anthropic.com"],"candidate_paths":["/news"],"parser_hint":"listing_page","language":"en","priority":1,"exclude_url_patterns":["/careers"],"notes":"Corporate announcements"},
  {"source_name":"Anthropic Engineering","source_type":"ai_company","region":"global","official_domain":"anthropic.com","landing_url":"https://www.anthropic.com/engineering","allowed_domains":["www.anthropic.com","anthropic.com"],"candidate_paths":["/engineering"],"parser_hint":"listing_page","language":"en","priority":1,"exclude_url_patterns":["/careers"],"notes":"Engineering blog — infra, evals, agent design, product features"},
  {"source_name":"Anthropic Research","source_type":"ai_company","region":"global","official_domain":"anthropic.com","landing_url":"https://www.anthropic.com/research","allowed_domains":["www.anthropic.com","anthropic.com"],"candidate_paths":["/research"],"parser_hint":"listing_page","language":"en","priority":1,"exclude_url_patterns":["/careers"],"notes":"Safety, interpretability, alignment research"},

  # ── Google DeepMind ──
  {"source_name":"Google DeepMind Blog","source_type":"ai_company","region":"global","official_domain":"deepmind.google","landing_url":"https://deepmind.google/blog/","allowed_domains":["deepmind.google"],"candidate_paths":["/blog/"],"parser_hint":"listing_page","language":"en","priority":1,"exclude_url_patterns":["/careers"],"notes":"Primary DeepMind news hub"},
  {"source_name":"Google DeepMind Research","source_type":"ai_company","region":"global","official_domain":"deepmind.google","landing_url":"https://deepmind.google/research/","allowed_domains":["deepmind.google"],"candidate_paths":["/research/"],"parser_hint":"listing_page","language":"en","priority":1,"exclude_url_patterns":["/careers"],"notes":"Research publications, breakthroughs, and model releases"},

  # ── Meta ──
  # ai.meta.com is JS-rendered; use Meta Engineering RSS which covers AI/ML.
  {"source_name":"Meta Engineering Blog","source_type":"ai_company","region":"global","official_domain":"engineering.fb.com","landing_url":"https://engineering.fb.com/feed/","allowed_domains":["engineering.fb.com","code.fb.com"],"candidate_paths":[],"parser_hint":"rss_feed","language":"en","priority":1,"exclude_url_patterns":[],"notes":"RSS feed — Meta engineering (AI agents, infra, ML systems)"},

  # ── Microsoft ──
  # news.microsoft.com HTML scraping produces junk ("Comments for Source"); use RSS.
  {"source_name":"Microsoft AI Blog RSS","source_type":"ai_company","region":"global","official_domain":"news.microsoft.com","landing_url":"https://news.microsoft.com/source/topics/ai/feed/","allowed_domains":["news.microsoft.com"],"candidate_paths":[],"parser_hint":"rss_feed","language":"en","priority":2,"exclude_url_patterns":["/careers"],"notes":"RSS feed — Microsoft AI news topic page"},
  {"source_name":"Microsoft Research Blog","source_type":"ai_company","region":"global","official_domain":"microsoft.com","landing_url":"https://www.microsoft.com/en-us/research/blog/","allowed_domains":["www.microsoft.com"],"candidate_paths":["/en-us/research/blog/"],"parser_hint":"listing_page","language":"en","priority":1,"exclude_url_patterns":["/careers","/events/"],"notes":"MSR research — Phi models, agents, robotics, reasoning"},

  # ── NVIDIA ──
  {"source_name":"NVIDIA Blog","source_type":"ai_company","region":"global","official_domain":"blogs.nvidia.com","landing_url":"https://blogs.nvidia.com/","allowed_domains":["blogs.nvidia.com"],"candidate_paths":["/","/blog/tag/artificial-intelligence/"],"parser_hint":"listing_page","language":"en","priority":1,"exclude_url_patterns":[],"notes":"Corporate NVIDIA blog"},
  {"source_name":"NVIDIA Technical Blog","source_type":"ai_company","region":"global","official_domain":"developer.nvidia.com","landing_url":"https://developer.nvidia.com/blog/","allowed_domains":["developer.nvidia.com"],"candidate_paths":["/blog/"],"parser_hint":"listing_page","language":"en","priority":2,"exclude_url_patterns":["/forums/"],"notes":"Technical AI/developer content"},

  # ── Cloud providers ──
  {"source_name":"AWS Machine Learning Blog","source_type":"ai_company","region":"global","official_domain":"aws.amazon.com","landing_url":"https://aws.amazon.com/blogs/machine-learning/","allowed_domains":["aws.amazon.com"],"candidate_paths":["/blogs/machine-learning/"],"parser_hint":"listing_page","language":"en","priority":2,"exclude_url_patterns":["/careers"],"notes":"Official AWS ML / GenAI blog"},
  {"source_name":"Google Cloud AI Blog","source_type":"ai_company","region":"global","official_domain":"cloud.google.com","landing_url":"https://cloud.google.com/blog/products/ai-machine-learning","allowed_domains":["cloud.google.com"],"candidate_paths":["/blog/products/ai-machine-learning"],"parser_hint":"listing_page","language":"en","priority":2,"exclude_url_patterns":["/docs/"],"notes":"Official Google Cloud AI/ML updates"},

  # ── Startups & labs ──
  {"source_name":"Mistral AI News","source_type":"ai_company","region":"global","official_domain":"mistral.ai","landing_url":"https://mistral.ai/news","allowed_domains":["mistral.ai"],"candidate_paths":["/news"],"parser_hint":"listing_page","language":"en","priority":1,"exclude_url_patterns":["/careers"],"notes":"Official Mistral updates — model releases, product launches"},
  {"source_name":"Cohere Blog","source_type":"ai_company","region":"global","official_domain":"cohere.com","landing_url":"https://cohere.com/blog","allowed_domains":["cohere.com"],"candidate_paths":["/blog"],"parser_hint":"listing_page","language":"en","priority":2,"exclude_url_patterns":["/events","/careers"],"notes":"Official Cohere blog"},
  {"source_name":"Cohere Research","source_type":"ai_company","region":"global","official_domain":"cohere.com","landing_url":"https://cohere.com/research","allowed_domains":["cohere.com"],"candidate_paths":["/research"],"parser_hint":"listing_page","language":"en","priority":2,"exclude_url_patterns":["/events","/careers"],"notes":"Cohere Labs — Aya multilingual, model merging, open science"},
  {"source_name":"Stability AI News","source_type":"ai_company","region":"global","official_domain":"stability.ai","landing_url":"https://stability.ai/news-updates","allowed_domains":["stability.ai"],"candidate_paths":["/news-updates","/news"],"parser_hint":"listing_page","language":"en","priority":2,"exclude_url_patterns":[],"notes":"Official Stability AI news (redirects from /news)"},
  {"source_name":"Stability AI Research","source_type":"ai_company","region":"global","official_domain":"stability.ai","landing_url":"https://stability.ai/research","allowed_domains":["stability.ai"],"candidate_paths":["/research"],"parser_hint":"listing_page","language":"en","priority":2,"exclude_url_patterns":[],"notes":"Stability research — SD3, video diffusion, audio generation"},
  {"source_name":"Replit Blog","source_type":"ai_company","region":"global","official_domain":"blog.replit.com","landing_url":"https://blog.replit.com/","allowed_domains":["blog.replit.com","replit.com"],"candidate_paths":["/"],"parser_hint":"listing_page","language":"en","priority":2,"exclude_url_patterns":["/careers"],"notes":"Official Replit blog"},
  {"source_name":"Hugging Face Blog","source_type":"ai_company","region":"global","official_domain":"huggingface.co","landing_url":"https://huggingface.co/blog","allowed_domains":["huggingface.co"],"candidate_paths":["/blog"],"parser_hint":"listing_page","language":"en","priority":1,"exclude_url_patterns":["/docs/","/models/","/datasets/"],"notes":"Official Hugging Face blog"},
  {"source_name":"Together AI Blog","source_type":"ai_company","region":"global","official_domain":"together.ai","landing_url":"https://www.together.ai/blog","allowed_domains":["www.together.ai","together.ai"],"candidate_paths":["/blog"],"parser_hint":"listing_page","language":"en","priority":2,"exclude_url_patterns":["/docs/","/careers"],"notes":"Official Together AI blog"},
  {"source_name":"Together AI Research","source_type":"ai_company","region":"global","official_domain":"together.ai","landing_url":"https://together.ai/research","allowed_domains":["www.together.ai","together.ai"],"candidate_paths":["/research"],"parser_hint":"listing_page","language":"en","priority":1,"exclude_url_patterns":["/docs/","/careers"],"notes":"FlashAttention, Mamba, Red Pajama — inference & kernel research"},
  {"source_name":"Scale AI Blog","source_type":"ai_company","region":"global","official_domain":"scale.com","landing_url":"https://scale.com/blog","allowed_domains":["scale.com"],"candidate_paths":["/blog"],"parser_hint":"listing_page","language":"en","priority":2,"exclude_url_patterns":["/careers","/demo"],"notes":"Official Scale AI blog"},
  {"source_name":"Databricks Blog RSS","source_type":"ai_company","region":"global","official_domain":"databricks.com","landing_url":"https://www.databricks.com/feed","allowed_domains":["www.databricks.com","databricks.com"],"candidate_paths":[],"parser_hint":"rss_feed","language":"en","priority":2,"exclude_url_patterns":["/careers","/customers"],"notes":"RSS feed — bypasses JS rendering on databricks.com/blog"},
  {"source_name":"Apple Machine Learning Research","source_type":"ai_company","region":"global","official_domain":"machinelearning.apple.com","landing_url":"https://machinelearning.apple.com/","allowed_domains":["machinelearning.apple.com"],"candidate_paths":["/"],"parser_hint":"listing_page","language":"en","priority":1,"exclude_url_patterns":[],"notes":"Apple ML research — on-device models, MLX, vision, NLP"},

  # ── Investment firms ──
  {"source_name":"a16z News & Content","source_type":"investment_firm","region":"global","official_domain":"a16z.com","landing_url":"https://a16z.com/news-content/","allowed_domains":["a16z.com"],"candidate_paths":["/news-content/","/category/general/a16z-news/"],"parser_hint":"listing_page","language":"en","priority":1,"exclude_url_patterns":[],"notes":"Official a16z content hub"},
  {"source_name":"Sequoia Capital RSS","source_type":"investment_firm","region":"global","official_domain":"sequoiacap.com","landing_url":"https://www.sequoiacap.com/feed/","allowed_domains":["www.sequoiacap.com","sequoiacap.com","articles.sequoiacap.com"],"candidate_paths":[],"parser_hint":"rss_feed","language":"en","priority":1,"exclude_url_patterns":["/people/","/arc/"],"notes":"RSS feed — Sequoia insights and articles"},
  {"source_name":"Accel News","source_type":"investment_firm","region":"global","official_domain":"accel.com","landing_url":"https://www.accel.com/news","allowed_domains":["www.accel.com","accel.com","atoms.accel.com"],"candidate_paths":["/news","/noteworthies/"],"parser_hint":"listing_page","language":"en","priority":1,"exclude_url_patterns":["/team/","/companies/"],"notes":"Official Accel news and insights"},
  {"source_name":"Index Ventures Perspectives","source_type":"investment_firm","region":"global","official_domain":"indexventures.com","landing_url":"https://www.indexventures.com/perspectives/","allowed_domains":["www.indexventures.com","indexventures.com"],"candidate_paths":["/perspectives/"],"parser_hint":"listing_page","language":"en","priority":1,"exclude_url_patterns":["/team/","/jobs/"],"notes":"Official Index content hub"},
  {"source_name":"General Catalyst Stories","source_type":"investment_firm","region":"global","official_domain":"generalcatalyst.com","landing_url":"https://www.generalcatalyst.com/stories","allowed_domains":["www.generalcatalyst.com","generalcatalyst.com"],"candidate_paths":["/stories","/worldview"],"parser_hint":"sectioned_listing_page","language":"en","priority":1,"exclude_url_patterns":["/portfolio","/team"],"notes":"News & content"},
  {"source_name":"Menlo Ventures RSS","source_type":"investment_firm","region":"global","official_domain":"menlovc.com","landing_url":"https://menlovc.com/feed/","allowed_domains":["menlovc.com"],"candidate_paths":[],"parser_hint":"rss_feed","language":"en","priority":1,"exclude_url_patterns":["/portfolio/"],"notes":"RSS feed — Menlo perspective articles"},
  {"source_name":"Sapphire Ventures Blog","source_type":"investment_firm","region":"global","official_domain":"sapphireventures.com","landing_url":"https://sapphireventures.com/perspectives/","allowed_domains":["sapphireventures.com"],"candidate_paths":["/blog/","/perspectives/"],"parser_hint":"listing_page","language":"en","priority":2,"exclude_url_patterns":["/portfolio/"],"notes":"Official Sapphire content hub"},
]


def load_sources() -> list[SourceConfig]:
    override_raw = os.environ.get("OFFICIAL_SOURCE_REGISTRY_JSON", "").strip()
    registry = [dict(item) for item in TRUSTED_SOURCE_REGISTRY]

    if override_raw:
        try:
            override_items = json.loads(override_raw)
            if isinstance(override_items, list):
                override_map = {
                    str(item.get("name", "")).strip(): str(item.get("url", "")).strip()
                    for item in override_items
                    if isinstance(item, dict)
                }
                for item in registry:
                    source_name = item.get("source_name", "")
                    if source_name in override_map and override_map[source_name]:
                        new_url = override_map[source_name]
                        parsed = urlparse(new_url)
                        host = parsed.netloc.lower()
                        item["landing_url"] = new_url
                        if host:
                            item["official_domain"] = host
                            allowed = set(item.get("allowed_domains") or [])
                            allowed.add(host)
                            item["allowed_domains"] = sorted(allowed)
        except json.JSONDecodeError:
            pass

    # Global exclusions to avoid non-article/company pages leaking into results.
    global_excludes = [
        "/careers", "/career", "/jobs", "/job/", "/hiring", "/work-with-us",
        "/team", "/people", "/about", "/contact", "/support", "/legal", "/privacy",
        "/events", "/webinar", "/podcast", "/tag/", "/category/",
    ]
    for item in registry:
        merged = list(item.get("exclude_url_patterns") or [])
        for pat in global_excludes:
            if pat not in merged:
                merged.append(pat)
        item["exclude_url_patterns"] = merged

    return [SourceConfig(**item) for item in registry]
