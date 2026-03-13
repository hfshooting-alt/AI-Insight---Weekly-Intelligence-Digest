from __future__ import annotations

import json
import os
from urllib.parse import urlparse

from .models import SourceConfig

# Initial production registry (official sources only)
TRUSTED_SOURCE_REGISTRY = [
  {"source_name":"OpenAI Newsroom","source_type":"ai_company","region":"global","official_domain":"openai.com","landing_url":"https://openai.com/news/","allowed_domains":["openai.com"],"candidate_paths":["/news/","/index/","/research/"],"parser_hint":"listing_page","language":"en","priority":1,"exclude_url_patterns":["/careers","/stories/"],"notes":"Primary corporate newsroom"},
  {"source_name":"OpenAI Developer Blog","source_type":"ai_company","region":"global","official_domain":"developers.openai.com","landing_url":"https://developers.openai.com/blog/","allowed_domains":["developers.openai.com"],"candidate_paths":["/blog/"],"parser_hint":"listing_page","language":"en","priority":1,"exclude_url_patterns":["/docs/","/examples/"],"notes":"Developer-facing product and platform announcements"},
  {"source_name":"Anthropic Newsroom","source_type":"ai_company","region":"global","official_domain":"anthropic.com","landing_url":"https://www.anthropic.com/news","allowed_domains":["www.anthropic.com","anthropic.com"],"candidate_paths":["/news","/research"],"parser_hint":"listing_page","language":"en","priority":1,"exclude_url_patterns":["/careers"],"notes":"Corporate announcements and research/news"},
  {"source_name":"Google DeepMind News","source_type":"ai_company","region":"global","official_domain":"deepmind.google","landing_url":"https://deepmind.google/blog/","allowed_domains":["deepmind.google"],"candidate_paths":["/blog/"],"parser_hint":"listing_page","language":"en","priority":1,"exclude_url_patterns":["/careers"],"notes":"Primary DeepMind news hub"},
  {"source_name":"Meta AI Blog","source_type":"ai_company","region":"global","official_domain":"ai.meta.com","landing_url":"https://ai.meta.com/blog/","allowed_domains":["ai.meta.com"],"candidate_paths":["/blog/","/research/"],"parser_hint":"listing_page","language":"en","priority":1,"exclude_url_patterns":["/research/"],"notes":"Use blog for announcements; research index is optional"},
  {"source_name":"xAI News","source_type":"ai_company","region":"global","official_domain":"x.ai","landing_url":"https://x.ai/news","allowed_domains":["x.ai"],"candidate_paths":["/news"],"parser_hint":"listing_page","language":"en","priority":1,"exclude_url_patterns":["/careers","/shop"],"notes":"Official xAI news feed"},
  {"source_name":"Microsoft AI Blog","source_type":"ai_company","region":"global","official_domain":"news.microsoft.com","landing_url":"https://news.microsoft.com/source/topics/ai/","allowed_domains":["news.microsoft.com"],"candidate_paths":["/source/topics/ai/","/source/topics/"],"parser_hint":"category_archive","language":"en","priority":2,"exclude_url_patterns":["/careers"],"notes":"Official Microsoft AI news topic page"},
  {"source_name":"NVIDIA Blog","source_type":"ai_company","region":"global","official_domain":"blogs.nvidia.com","landing_url":"https://blogs.nvidia.com/","allowed_domains":["blogs.nvidia.com"],"candidate_paths":["/","/blog/tag/artificial-intelligence/"],"parser_hint":"listing_page","language":"en","priority":1,"exclude_url_patterns":[],"notes":"Corporate NVIDIA blog"},
  {"source_name":"NVIDIA Technical Blog","source_type":"ai_company","region":"global","official_domain":"developer.nvidia.com","landing_url":"https://developer.nvidia.com/blog/","allowed_domains":["developer.nvidia.com"],"candidate_paths":["/blog/"],"parser_hint":"listing_page","language":"en","priority":2,"exclude_url_patterns":["/forums/"],"notes":"Technical AI/developer content"},
  {"source_name":"AWS Machine Learning Blog","source_type":"ai_company","region":"global","official_domain":"aws.amazon.com","landing_url":"https://aws.amazon.com/blogs/machine-learning/","allowed_domains":["aws.amazon.com"],"candidate_paths":["/blogs/machine-learning/","/blogs/aws/category/artificial-intelligence/amazon-machine-learning/"],"parser_hint":"listing_page","language":"en","priority":2,"exclude_url_patterns":["/careers"],"notes":"Official AWS ML / GenAI blog"},
  {"source_name":"Google Cloud AI & ML Blog","source_type":"ai_company","region":"global","official_domain":"cloud.google.com","landing_url":"https://cloud.google.com/blog/products/ai-machine-learning","allowed_domains":["cloud.google.com"],"candidate_paths":["/blog/products/ai-machine-learning","/blog"],"parser_hint":"listing_page","language":"en","priority":2,"exclude_url_patterns":["/docs/"],"notes":"Official Google Cloud AI/ML updates"},
  {"source_name":"Mistral AI News","source_type":"ai_company","region":"global","official_domain":"mistral.ai","landing_url":"https://mistral.ai/news","allowed_domains":["mistral.ai"],"candidate_paths":["/news"],"parser_hint":"listing_page","language":"en","priority":1,"exclude_url_patterns":["/careers"],"notes":"Official Mistral updates"},
  {"source_name":"Cohere Blog","source_type":"ai_company","region":"global","official_domain":"cohere.com","landing_url":"https://cohere.com/blog","allowed_domains":["cohere.com"],"candidate_paths":["/blog"],"parser_hint":"listing_page","language":"en","priority":2,"exclude_url_patterns":["/events","/careers"],"notes":"Official Cohere blog"},
  {"source_name":"Stability AI News","source_type":"ai_company","region":"global","official_domain":"stability.ai","landing_url":"https://stability.ai/news","allowed_domains":["stability.ai"],"candidate_paths":["/news"],"parser_hint":"listing_page","language":"en","priority":2,"exclude_url_patterns":[],"notes":"Official Stability AI news"},
  {"source_name":"Qwen Blog","source_type":"ai_company","region":"cn","official_domain":"qwen.ai","landing_url":"https://qwen.ai/blog/","allowed_domains":["qwen.ai"],"candidate_paths":["/blog/"],"parser_hint":"listing_page","language":"en","priority":1,"exclude_url_patterns":["/docs/"],"notes":"Official Qwen blog"},
  {"source_name":"Zhipu News","source_type":"ai_company","region":"cn","official_domain":"zhipuai.cn","landing_url":"https://www.zhipuai.cn/zh/news","allowed_domains":["www.zhipuai.cn","zhipuai.cn"],"candidate_paths":["/zh/news","/news"],"parser_hint":"listing_page","language":"zh","priority":1,"exclude_url_patterns":["/careers"],"notes":"Official Zhipu news center"},
  {"source_name":"MiniMax News","source_type":"ai_company","region":"cn","official_domain":"minimaxi.com","landing_url":"https://www.minimaxi.com/en/news","allowed_domains":["www.minimaxi.com","minimaxi.com"],"candidate_paths":["/en/news"],"parser_hint":"listing_page","language":"en","priority":1,"exclude_url_patterns":[],"notes":"Official MiniMax news page"},
  {"source_name":"Baidu AI Official News","source_type":"ai_company","region":"cn","official_domain":"ai.baidu.com","landing_url":"https://ai.baidu.com/support/news","allowed_domains":["ai.baidu.com"],"candidate_paths":["/support/news"],"parser_hint":"listing_page","language":"zh","priority":2,"exclude_url_patterns":["/ai-doc/","/industry/"],"notes":"Official Baidu AI platform news"},
  {"source_name":"SenseTime News","source_type":"ai_company","region":"cn","official_domain":"sensetime.com","landing_url":"https://www.sensetime.com/cn/news-press-release","allowed_domains":["www.sensetime.com","sensetime.com"],"candidate_paths":["/cn/news-press-release","/cn/news-index"],"parser_hint":"listing_page","language":"zh","priority":2,"exclude_url_patterns":["/investor"],"notes":"Official SenseTime news page"},
  {"source_name":"Tencent Newsroom","source_type":"ai_company","region":"cn","official_domain":"tencent.com","landing_url":"https://www.tencent.com/zh-cn/media/news.html?type=media","allowed_domains":["www.tencent.com","tencent.com"],"candidate_paths":["/zh-cn/media/news.html"],"parser_hint":"listing_page","language":"zh","priority":2,"exclude_url_patterns":["/careers"],"notes":"Official Tencent media/news page"},
  {"source_name":"DeepSeek API News","source_type":"ai_company","region":"cn","official_domain":"api-docs.deepseek.com","landing_url":"https://api-docs.deepseek.com/news/","allowed_domains":["api-docs.deepseek.com"],"candidate_paths":["/news/","/updates"],"parser_hint":"docs_news_index","language":"en","priority":2,"exclude_url_patterns":["/status"],"notes":"Official DeepSeek developer/news announcements"},
  {"source_name":"a16z News & Content","source_type":"investment_firm","region":"global","official_domain":"a16z.com","landing_url":"https://a16z.com/news-content/","allowed_domains":["a16z.com"],"candidate_paths":["/news-content/","/category/general/a16z-news/"],"parser_hint":"listing_page","language":"en","priority":1,"exclude_url_patterns":["/podcasts/"],"notes":"Official a16z content hub"},
  {"source_name":"Sequoia Capital","source_type":"investment_firm","region":"global","official_domain":"sequoiacap.com","landing_url":"https://sequoiacap.com/","allowed_domains":["sequoiacap.com","articles.sequoiacap.com"],"candidate_paths":["/","/article/"],"parser_hint":"homepage_story_cards_and_article_pattern","language":"en","priority":1,"exclude_url_patterns":["/people/","/arc/","/podcast/"],"notes":"Homepage surfaces latest stories"},
  {"source_name":"Accel News","source_type":"investment_firm","region":"global","official_domain":"accel.com","landing_url":"https://www.accel.com/news","allowed_domains":["www.accel.com","accel.com","atoms.accel.com"],"candidate_paths":["/news","/noteworthies/"],"parser_hint":"listing_page","language":"en","priority":1,"exclude_url_patterns":["/team/","/companies/"],"notes":"Official Accel news and insights"},
  {"source_name":"Greylock Blog","source_type":"investment_firm","region":"global","official_domain":"greylock.com","landing_url":"https://greylock.com/blog/","allowed_domains":["greylock.com"],"candidate_paths":["/blog/","/greymatter/"],"parser_hint":"listing_page","language":"en","priority":1,"exclude_url_patterns":["/jobs/","/portfolio/"],"notes":"Official Greylock News & Insights"},
  {"source_name":"Index Ventures Perspectives","source_type":"investment_firm","region":"global","official_domain":"indexventures.com","landing_url":"https://www.indexventures.com/perspectives/","allowed_domains":["www.indexventures.com","indexventures.com"],"candidate_paths":["/perspectives/"],"parser_hint":"listing_page","language":"en","priority":1,"exclude_url_patterns":["/team/","/jobs/"],"notes":"Official Index content hub"},
  {"source_name":"Bessemer Atlas","source_type":"investment_firm","region":"global","official_domain":"bvp.com","landing_url":"https://www.bvp.com/atlas","allowed_domains":["www.bvp.com","bvp.com"],"candidate_paths":["/atlas"],"parser_hint":"listing_page","language":"en","priority":1,"exclude_url_patterns":["/team/","/portfolio/"],"notes":"Official Bessemer insights hub"},
  {"source_name":"General Catalyst Stories","source_type":"investment_firm","region":"global","official_domain":"generalcatalyst.com","landing_url":"https://www.generalcatalyst.com/stories","allowed_domains":["www.generalcatalyst.com","generalcatalyst.com"],"candidate_paths":["/stories","/worldview"],"parser_hint":"sectioned_listing_page","language":"en","priority":1,"exclude_url_patterns":["/portfolio","/team"],"notes":"News & content"},
  {"source_name":"Menlo Ventures Perspective","source_type":"investment_firm","region":"global","official_domain":"menlovc.com","landing_url":"https://menlovc.com/perspective/","allowed_domains":["menlovc.com"],"candidate_paths":["/perspective/"],"parser_hint":"listing_page","language":"en","priority":1,"exclude_url_patterns":["/portfolio/"],"notes":"Official Menlo perspective hub"},
  {"source_name":"Atomico Insights","source_type":"investment_firm","region":"global","official_domain":"atomico.com","landing_url":"https://atomico.com/insights","allowed_domains":["atomico.com"],"candidate_paths":["/insights"],"parser_hint":"listing_page","language":"en","priority":2,"exclude_url_patterns":["/team/","/portfolio/"],"notes":"Official Atomico insights"},
  {"source_name":"Sapphire Ventures Blog","source_type":"investment_firm","region":"global","official_domain":"sapphireventures.com","landing_url":"https://sapphireventures.com/perspectives/","allowed_domains":["sapphireventures.com"],"candidate_paths":["/blog/","/perspectives/"],"parser_hint":"listing_page","language":"en","priority":2,"exclude_url_patterns":["/portfolio/"],"notes":"Official Sapphire content hub"},
  {"source_name":"Hillhouse News","source_type":"investment_firm","region":"cn","official_domain":"hillhouseinvestment.com","landing_url":"https://www.hillhouseinvestment.com/news/","allowed_domains":["www.hillhouseinvestment.com","hillhouseinvestment.com"],"candidate_paths":["/news/"],"parser_hint":"listing_page","language":"en","priority":1,"exclude_url_patterns":["/team/","/our-heritage/"],"notes":"Official Hillhouse News"},
  {"source_name":"Qiming Newsroom","source_type":"investment_firm","region":"cn","official_domain":"qimingvc.com","landing_url":"https://www.qimingvc.com/cn/newsroom","allowed_domains":["www.qimingvc.com","qimingvc.com"],"candidate_paths":["/cn/newsroom"],"parser_hint":"listing_page_with_pagination","language":"zh","priority":1,"exclude_url_patterns":["/team/","/portfolio/"],"notes":"Official Qiming newsroom"},
  {"source_name":"HSG News & Insights","source_type":"investment_firm","region":"cn","official_domain":"hsgcap.com","landing_url":"https://www.hsgcap.com/insights-and-news/","allowed_domains":["www.hsgcap.com","hsgcap.com","hongshan.com"],"candidate_paths":["/insights-and-news/","/"],"parser_hint":"homepage_story_cards","language":"en","priority":1,"exclude_url_patterns":["/jobs/","/team/"],"notes":"Official HSG insights and news"}
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

    return [SourceConfig(**item) for item in registry]
