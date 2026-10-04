"""
Hugging Face Daily Papers API 수집 어댑터
- https://huggingface.co/api/daily_papers 파싱
"""

from typing import List, Optional, Dict, Any
import httpx
from adapters.sources.base import BaseSourceAdapter, RawCollectedItem
from services.source_validator import test_source_url


class HuggingFacePapersAdapter(BaseSourceAdapter):
    async def fetch_items(self, url: str, config: Optional[Dict[str, Any]] = None) -> List[RawCollectedItem]:
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

            data = resp.json()
            if not isinstance(data, list):
                return []

            for row in data[:limit]:
                paper = row.get("paper", {}) if isinstance(row, dict) else {}
                paper_id = paper.get("id") or row.get("id", "")
                title = paper.get("title") or row.get("title", "")
                summary = paper.get("summary") or row.get("summary", "")
                published = row.get("publishedAt") or paper.get("publishedAt", "")
                paper_url = f"https://huggingface.co/papers/{paper_id}" if paper_id else ""

                if title and paper_url:
                    items.append(
                        RawCollectedItem(
                            title=title.strip(),
                            url=paper_url,
                            summary=summary[:1000].strip(),
                            source_name="Hugging Face Daily Papers",
                            source_kind="HUGGINGFACE_PAPERS",
                            published_at=published,
                            extra_metadata={"paper_id": paper_id}
                        )
                    )

        return items
