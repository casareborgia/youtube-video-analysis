"""
수집 항목 중복 방지 및 큐레이션 서비스
- URL 정규화 (UTM, fbclid 등 추적 파라미터 제거)
- SHA-256 해시 기반 30일 이내 중복 필터링
- 콘텐츠 품질 및 신선도 기반 큐레이션 랭킹
"""

import hashlib
from typing import List, Optional
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
from adapters.sources.base import RawCollectedItem
from repositories.routine_repository import RoutineRepository

STRIP_QUERY_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "ref", "source", "feature"
}


def normalize_url(raw_url: str) -> str:
    """
    URL에서 불필요한 추적 파라미터를 제거하고 정규화합니다.
    """
    if not raw_url:
        return ""

    parsed = urlparse(raw_url.strip())
    # 쿼리스트링 파싱 및 추적 파라미터 필터링
    query_params = parse_qsl(parsed.query, keep_blank_values=False)
    filtered_params = [
        (k, v) for k, v in query_params if k.lower() not in STRIP_QUERY_PARAMS
    ]
    # 알파벳 순 정렬하여 일관성 유지
    filtered_params.sort(key=lambda x: x[0])
    clean_query = urlencode(filtered_params)

    # 경로 끝의 불필요한 슬래시 정리 (루트 제외)
    path = parsed.path
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    normalized = urlunparse((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        path,
        parsed.params,
        clean_query,
        ""  # fragment 제거
    ))
    return normalized


def compute_url_hash(raw_url: str) -> str:
    """정규화된 URL의 SHA-256 해시값 반환"""
    clean_url = normalize_url(raw_url)
    return hashlib.sha256(clean_url.encode("utf-8")).hexdigest()


class DeduplicationService:
    def __init__(self, repo: Optional[RoutineRepository] = None):
        self.repo = repo or RoutineRepository()

    def filter_unseen_items(self, items: List[RawCollectedItem], routine_id: int) -> List[RawCollectedItem]:
        """
        이미 수집되거나 발행된 이력이 있는 항목을 배제합니다.
        """
        unseen: List[RawCollectedItem] = []
        for item in items:
            url_hash = compute_url_hash(item.url)
            if not self.repo.is_item_collected(url_hash):
                unseen.append(item)
        return unseen

    def mark_item_as_collected(self, item: RawCollectedItem, routine_id: int, source_id: int = 0):
        """항목을 수집 완료 상태로 DB에 기록"""
        url_hash = compute_url_hash(item.url)
        self.repo.record_collected_item(
            url_hash=url_hash,
            url=normalize_url(item.url),
            title=item.title,
            summary=item.summary,
            source_id=source_id,
            routine_id=routine_id
        )

    def curate_best_items(self, items: List[RawCollectedItem], max_items: int = 3) -> List[RawCollectedItem]:
        """
        신선도, 제목 길이, 요약 충실도를 고려하여 최우선 게시 대상 항목 선정
        """
        if not items:
            return []

        def score_item(item: RawCollectedItem) -> float:
            score = 10.0
            # 1. 제목 충실도 (너무 짧거나 길면 감점)
            t_len = len(item.title)
            if 15 <= t_len <= 80:
                score += 5.0
            elif t_len < 10:
                score -= 3.0

            # 2. 요약 충실도
            s_len = len(item.summary)
            if s_len >= 50:
                score += 5.0
            elif s_len == 0:
                score -= 2.0

            # 3. 중요 키워드 가산점
            text = (item.title + " " + item.summary).lower()
            keywords = ["ai", "llm", "agent", "gpt", "model", "연구", "논문", "마음", "힐링"]
            for kw in keywords:
                if kw in text:
                    score += 1.0

            return score

        sorted_items = sorted(items, key=score_item, reverse=True)
        return sorted_items[:max_items]
