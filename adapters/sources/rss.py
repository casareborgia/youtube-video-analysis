"""
RSS / Atom 피드 수집 어댑터
- GeekNews, DeepMind Blog 등 표준 피드 파싱
"""

from typing import List, Optional, Dict, Any
import feedparser
import httpx
from adapters.sources.base import BaseSourceAdapter, RawCollectedItem
from services.source_validator import test_source_url


class RssAdapter(BaseSourceAdapter):
    async def fetch_items(self, url: str, config: Optional[Dict[str, Any]] = None) -> List[RawCollectedItem]:
        # 1. SSRF 방어 검증
        test_res = await test_source_url(url)
        if not test_res.success:
            return []

        limit = (config or {}).get("limit", 10)
        items: List[RawCollectedItem] = []

        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; TubeInsightAutonomousSocialOperator/1.0; +https://github.com)"
        }
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                return []

            feed = feedparser.parse(resp.content)
            source_title = feed.feed.get("title", "RSS Feed") if hasattr(feed, "feed") else "RSS Feed"

            for entry in feed.entries[:limit]:
                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                summary = entry.get("summary", "") or entry.get("description", "")
                published = entry.get("published", "") or entry.get("updated", "")

                if title and link:
                    items.append(
                        RawCollectedItem(
                            title=title,
                            url=link,
                            summary=summary[:1000].strip(),
                            source_name=source_title,
                            source_kind="RSS_ATOM",
                            published_at=published,
                            extra_metadata={"author": entry.get("author", "")}
                        )
                    )

        return items
