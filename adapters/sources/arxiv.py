"""
arXiv AI 논문 수집 어댑터
- https://rss.arxiv.org/rss/cs.AI 파싱
- 주말(토/일) skipDays로 인해 피드가 비어있을 경우 Hugging Face Daily Papers로 자동 폴백
"""

from typing import List, Optional, Dict, Any
import feedparser
import httpx
from adapters.sources.base import BaseSourceAdapter, RawCollectedItem
from adapters.sources.huggingface import HuggingFacePapersAdapter
from services.source_validator import test_source_url


class ArxivAdapter(BaseSourceAdapter):
    def __init__(self):
        self.hf_fallback = HuggingFacePapersAdapter()

    async def fetch_items(self, url: str, config: Optional[Dict[str, Any]] = None) -> List[RawCollectedItem]:
        limit = (config or {}).get("limit", 10)
        items: List[RawCollectedItem] = []

        # 1. arXiv RSS 시도
        test_res = await test_source_url(url)
        if test_res.success:
            try:
                headers = {
                    "User-Agent": "Mozilla/5.0 (compatible; TubeInsightAutonomousSocialOperator/1.0; +https://github.com)"
                }
                async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                    resp = await client.get(url, headers=headers)
                    if resp.status_code == 200:
                        feed = feedparser.parse(resp.content)
                        for entry in feed.entries[:limit]:
                            title = entry.get("title", "").strip()
                            link = entry.get("link", "").strip()
                            summary = entry.get("summary", "")
                            published = entry.get("published", "")
                            if title and link:
                                items.append(
                                    RawCollectedItem(
                                        title=title,
                                        url=link,
                                        summary=summary[:1000].strip(),
                                        source_name="arXiv cs.AI",
                                        source_kind="ARXIV",
                                        published_at=published
                                    )
                                )
            except Exception:
                pass

        # 2. 주말 skipDays 등으로 arXiv 결과가 0건인 경우 Hugging Face Daily Papers로 자동 폴백
        if not items:
            hf_url = (config or {}).get(
                "fallback_url",
                "https://huggingface.co/api/daily_papers?limit=10"
            )
            fallback_items = await self.hf_fallback.fetch_items(hf_url, config={"limit": limit})
            for item in fallback_items:
                item.extra_metadata["fallback_from"] = "ARXIV_WEEKEND_SKIPDAYS"
            return fallback_items

        return items
