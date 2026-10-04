"""
마음지기 서비스 웹사이트 및 프로모션 앵글 연계 어댑터
- https://maumjigi.com 메타 정보 및 힐링 케어 콘텐츠 결합
"""

from typing import List, Optional, Dict, Any
import httpx
from adapters.sources.base import BaseSourceAdapter, RawCollectedItem
from services.source_validator import test_source_url


class MaumSiteAdapter(BaseSourceAdapter):
    async def fetch_items(self, url: str, config: Optional[Dict[str, Any]] = None) -> List[RawCollectedItem]:
        target_url = url or "https://maumjigi.com"
        title = "마음지기 — 내 손안의 24시간 AI 마음케어 친구"
        summary = "언제 어디서나 익명으로 안전하게, 전문 심리상담사의 통찰이 담긴 감정 일기와 공감 피드백으로 마음의 온도를 돌보세요."

        # 웹사이트 라이브 접속 시도 (WAF/보안 체크포인트 방지 헤더 적용)
        try:
            import urllib.request
            req = urllib.request.Request(target_url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            })
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                if resp.status == 200:
                    text = resp.read().decode("utf-8", errors="ignore")
                    import re
                    title_match = re.search(r"<title>(.*?)</title>", text, re.IGNORECASE)
                    if title_match:
                        title = title_match.group(1).strip()
        except Exception:
            pass

        angle_title = (config or {}).get("angle_title") or (config or {}).get("title")
        hook = (config or {}).get("hook_template")
        body = (config or {}).get("body_template")

        item_title = f"[마음지기 힐링 레터] {angle_title}" if angle_title else title
        item_summary = f"{hook} {body}" if (hook and body) else summary

        return [
            RawCollectedItem(
                title=item_title,
                url=target_url,
                summary=item_summary,
                source_name="마음지기 (Maumjigi)",
                source_kind="SITE_ADAPTER",
                extra_metadata={
                    "angle_title": angle_title,
                    "service_url": target_url,
                    "angle_dict": config
                }
            )
        ]
