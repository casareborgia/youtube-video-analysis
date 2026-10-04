"""
출처 유형별 어댑터 팩토리
"""

from typing import Optional
from domain.enums import SourceType
from adapters.sources.base import BaseSourceAdapter
from adapters.sources.rss import RssAdapter
from adapters.sources.arxiv import ArxivAdapter
from adapters.sources.huggingface import HuggingFacePapersAdapter
from adapters.sources.maum_site import MaumSiteAdapter


def get_adapter_for_source_type(source_type: SourceType) -> BaseSourceAdapter:
    if source_type in (SourceType.RSS_ATOM, SourceType.JSON_API):
        # JSON_API도 일반 피드/API 처리이므로 기본 RssAdapter 또는 맞춤형 처리
        return RssAdapter()
    elif source_type == SourceType.ARXIV:
        return ArxivAdapter()
    elif source_type == SourceType.HUGGINGFACE_PAPERS:
        return HuggingFacePapersAdapter()
    elif source_type == SourceType.SITE_ADAPTER:
        return MaumSiteAdapter()
    return RssAdapter()
