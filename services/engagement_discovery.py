"""불특정 다수 스레드(Threads) & X 실운영 키워드 검색 및 후보 발굴 엔진 (Engagement Discovery).

Threads 팔로워 성장 시스템 실운영 전환 반영:
1. 공식 Threads 키워드 검색 API (GET /keyword_search, RECENT/TOP) 기반 실제 최신 게시물 수집.
2. 운영 모드에서 데모 데이터 자동 삽입 차단 (allow_demo_seeds=False 기본값).
3. 후보 품질 점수 시스템 (candidate_score: 0~100, score_reasons) 산출 및 정렬.
4. 계정 단위 중복 제거 (동일 계정의 복수 게시물 중 최고 점수 게시물만 선발).
5. 계정 본인 및 기존 관계(팔로워, 상호작용자, 댓글 작성자) 완벽 제외.
"""

from __future__ import annotations

import datetime
import logging
import random
import time
from typing import Any, Dict, List, Optional, Set, Tuple

import content_service
import social_store
import threads_client
import x_client
from services.social_relationship_service import SocialRelationshipService

logger = logging.getLogger("EngagementDiscoveryService")

# 주제별 검색 키워드 확장 풀
DEFAULT_TOPIC_QUERIES: Dict[str, List[str]] = {
    "AI": ["AI", "인공지능", "생성형 AI", "AI 자동화"],
    "개발자": ["개발자", "파이썬", "코딩", "소프트웨어 개발"],
    "스타트업": ["스타트업", "창업", "SaaS", "비즈니스"],
    "일상": ["일상", "직장인", "기록", "생각"],
    "스하리": ["스하리", "스레드", "소통", "맞팔"],
    "소통": ["소통", "스하리", "인사이트"],
    "전체": ["AI", "개발자", "스타트업", "일상"],
}

# 후보 품질 점수 평가 상수 (가산/감점 정책)
SCORE_BASE = 50
SCORE_TOPIC_KEYWORD_MATCH = 25
SCORE_FRESH_30M = 25
SCORE_FRESH_2H = 15
SCORE_FRESH_24H = 5
SCORE_CONTENT_RICH = 15
SCORE_CONTENT_SHORT = -10
SCORE_ENGAGEMENT_SIGNAL = 15
SCORE_SPAM_PENALTY = -35

# 스팸/도배 감점 키워드
SPAM_KEYWORDS = ["맞팔해요", "선팔", "광고", "수익인증", "부업", "무료증정", "텔레그램", "카톡방"]

# 데모 및 개발/테스트용 시드 타겟 풀 (명시적 allow_demo_seeds=True 일 때만 격리 사용)
DEMO_THREADS_SEED_TARGETS = [
    {
        "account_id": "itemcurator_threads",
        "username": "itemcurator_threads",
        "post_id": "th_ext_301",
        "text": "오늘 하루도 다들 고생 많으셨어요! 자기 전에 스하리 한 바퀴 돌고 잡니다 ㅎㅎ 맞팔 소통해요 ✨",
        "post_url": "https://www.threads.net/@itemcurator_threads/post/th_ext_301",
        "topic": "스하리",
    },
    {
        "account_id": "mola_mola02",
        "username": "mola_mola02",
        "post_id": "th_ext_302",
        "text": "스레드 시작한 지 얼마 안 된 뉴비입니다! 좋은 글 공유하고 서로 힘이 되는 소통 스레더 분들 환영해요 😊",
        "post_url": "https://www.threads.net/@mola_mola02/post/th_ext_302",
        "topic": "소통",
    },
    {
        "account_id": "where_naecha",
        "username": "where_naecha",
        "post_id": "th_ext_303",
        "text": "AI 툴들이 하루가 다르게 쏟아지네요. 실무에 바로 써먹을 수 있는 자동화 파이프라인 연구 중입니다!",
        "post_url": "https://www.threads.net/@where_naecha/post/th_ext_303",
        "topic": "AI",
    },
    {
        "account_id": "richardlee0202",
        "username": "richardlee0202",
        "post_id": "th_ext_304",
        "text": "주말에도 코딩하고 인사이트 나누는 열정 스레더 분들 리스펙합니다. 다 같이 성장해요! 🚀",
        "post_url": "https://www.threads.net/@richardlee0202/post/th_ext_304",
        "topic": "개발자",
    },
    {
        "account_id": "bonu_vibe276",
        "username": "bonu_vibe276",
        "post_id": "th_ext_305",
        "text": "오늘 마신 커피 한 잔의 여유 ☕ 조용히 스하리 남기고 갑니다. 다들 편안한 밤 되세요~",
        "post_url": "https://www.threads.net/@bonu_vibe276/post/th_ext_305",
        "topic": "일상",
    },
]


def calculate_candidate_score(
    cand: Dict[str, Any],
    topic: str,
    search_query: str,
    now_ts: int,
) -> Tuple[int, List[str]]:
    """후보 게시물의 품질 점수(0~100) 및 점수 사유 도출."""
    score = SCORE_BASE
    reasons: List[str] = []

    text = cand.get("post_text") or cand.get("text") or ""
    timestamp = int(cand.get("timestamp") or 0)
    has_replies = bool(cand.get("has_replies"))

    # 1. 키워드 일치도
    check_words = [w for w in (search_query.split() + [topic]) if len(w) >= 2]
    matched_word = next((w for w in check_words if w.lower() in text.lower()), None)
    if matched_word:
        score += SCORE_TOPIC_KEYWORD_MATCH
        reasons.append(f"주제 키워드 일치 ('{matched_word}', +{SCORE_TOPIC_KEYWORD_MATCH})")

    # 2. 게시물 최신성
    if timestamp > 0:
        age_seconds = max(0, now_ts - timestamp)
        if age_seconds <= 1800:
            score += SCORE_FRESH_30M
            reasons.append(f"최근 30분 이내 게시물 (+{SCORE_FRESH_30M})")
        elif age_seconds <= 7200:
            score += SCORE_FRESH_2H
            reasons.append(f"최근 2시간 이내 게시물 (+{SCORE_FRESH_2H})")
        elif age_seconds <= 86400:
            score += SCORE_FRESH_24H
            reasons.append(f"24시간 이내 게시물 (+{SCORE_FRESH_24H})")

    # 3. 본문 길이 및 정보량
    text_len = len(text.strip())
    if text_len >= 40:
        score += SCORE_CONTENT_RICH
        reasons.append(f"충분한 본문 정보량 ({text_len}자, +{SCORE_CONTENT_RICH})")
    elif text_len < 15:
        score += SCORE_CONTENT_SHORT
        reasons.append(f"단문 게시물 감점 ({text_len}자, {SCORE_CONTENT_SHORT})")

    # 4. 소통 신호 (has_replies 또는 질문/의견 구하는 문장)
    if has_replies or any(q in text for q in ("?", "어떻게", "추천", "궁금", "의견")):
        score += SCORE_ENGAGEMENT_SIGNAL
        reasons.append(f"소통 및 피드백 가능 신호 (+{SCORE_ENGAGEMENT_SIGNAL})")

    # 5. 스팸/도배/반복 감점
    found_spam = [w for w in SPAM_KEYWORDS if w in text]
    if found_spam:
        score += SCORE_SPAM_PENALTY
        reasons.append(f"도배/맞팔 유도 키워드 감점 ({', '.join(found_spam)}, {SCORE_SPAM_PENALTY})")

    final_score = max(0, min(100, score))
    return final_score, reasons


class EngagementDiscoveryService:
    """공식 검색 기반 불특정 다수 활성 사용자 발굴 및 품질 평가 서비스"""

    def __init__(
        self,
        store: Optional[social_store.SocialStore] = None,
        relationship_service: Optional[SocialRelationshipService] = None,
    ):
        self.store = store or social_store.SocialStore()
        self.relationship_service = (
            relationship_service or SocialRelationshipService(store=self.store)
        )

    def discover_targets(
        self,
        platform: str = "threads",
        topic: str = "스하리",
        limit: int = 10,
        exclude_existing_relationships: bool = True,
        actor_account_id: str = "",
        allow_demo_seeds: bool = False,
        search_type: str = "RECENT",
        now_ts: Optional[int] = None,
    ) -> Dict[str, Any]:
        """공식 키워드 검색을 통해 실제 최신 게시물을 수집하고 품질 평가 및 관계 필터링을 거쳐 반환."""
        plat = content_service.normalize_platform(platform)
        safe_limit = max(1, min(int(limit), 50))
        now = int(now_ts or time.time())

        # 1. 실행 계정 본인 정보 식별 (공통 식별자 리졸버 활용)
        actor_res = self.relationship_service.resolve_actor_identities(platform=plat, actor_account_id=actor_account_id)
        self_names = actor_res["self_usernames"]
        self_ids = actor_res["self_user_ids"]
        actor = actor_res["primary_actor"]

        # 2. 공식 검색 API 호출을 통한 후보 수집
        raw_candidates: List[Dict[str, Any]] = []
        fetch_error: Optional[str] = None

        if plat == "threads":
            raw_candidates, fetch_error = self._fetch_threads_candidates(
                topic=topic,
                allow_demo_seeds=allow_demo_seeds,
                search_type=search_type,
                limit=safe_limit * 3,
                now_ts=now,
            )
        elif plat == "x":
            raw_candidates, fetch_error = self._fetch_x_candidates(
                topic=topic,
                allow_demo_seeds=allow_demo_seeds,
                limit=safe_limit * 3,
                now_ts=now,
            )

        # 3. 단일 공통 필터 및 품질 점수 파이프라인
        scanned_count = len(raw_candidates)
        candidates_by_account: Dict[str, Dict[str, Any]] = {}
        excluded_by_reason: Dict[str, int] = {
            "self_account": 0,
            "known_follower": 0,
            "followed_or_following": 0,
            "engaged_before": 0,
            "commented_on_my_content": 0,
            "replied_by_me": 0,
            "suppressed": 0,
            "action_already_done": 0,
            "duplicate_candidate": 0,
        }

        for cand in raw_candidates:
            raw_uname = cand.get("username") or cand.get("account_id") or ""
            target_key = SocialRelationshipService.normalize_key(raw_uname)
            post_id = str(cand.get("post_id") or "").strip()

            # 3-1. 본인 계정 배제
            if target_key in self_names or cand.get("account_id") in self_ids:
                excluded_by_reason["self_account"] += 1
                continue

            # 3-2. 기존 관계 배제 (신규 발굴 모드)
            if exclude_existing_relationships:
                eval_res = self.relationship_service.evaluate_target(
                    platform=plat,
                    actor_account_id=actor,
                    target_username=raw_uname,
                    target_user_id=cand.get("account_id") or "",
                    target_post_id=post_id,
                    self_usernames=self_names,
                    self_user_ids=self_ids,
                    now_ts=now,
                )
                if eval_res.excluded:
                    r_code = eval_res.reason or "engaged_before"
                    excluded_by_reason[r_code] = excluded_by_reason.get(r_code, 0) + 1
                    continue

            # 3-3. 게시물 단위 멱등성 검사 (social_dedup_keys)
            if post_id:
                is_done = self.store.is_action_already_done(
                    platform=plat,
                    actor_account_id=actor,
                    action="like",
                    target_id=post_id,
                    dry_run=False,
                )
                if is_done:
                    excluded_by_reason["action_already_done"] += 1
                    continue

            # 3-4. 후보 품질 점수 산출
            q = cand.get("search_query") or topic
            score, reasons = calculate_candidate_score(cand=cand, topic=topic, search_query=q, now_ts=now)
            cand_scored = dict(cand)
            cand_scored["candidate_score"] = score
            cand_scored["score_reasons"] = reasons
            cand_scored["platform"] = plat
            cand_scored["is_new_candidate"] = True
            cand_scored["relationship_signal"] = "신규 후보"

            # 3-5. 계정 단위 중복 제거 (한 계정당 가장 점수가 높은 1개 게시물만 유지)
            if target_key in candidates_by_account:
                excluded_by_reason["duplicate_candidate"] += 1
                if score > candidates_by_account[target_key]["candidate_score"]:
                    candidates_by_account[target_key] = cand_scored
            else:
                candidates_by_account[target_key] = cand_scored

        # 4. 품질 점수 기준 내림차순 정렬 및 최종 limit 선발
        sorted_candidates = sorted(
            candidates_by_account.values(),
            key=lambda c: c.get("candidate_score", 0),
            reverse=True,
        )
        final_targets = sorted_candidates[:safe_limit]

        clean_excluded_by_reason = {k: v for k, v in excluded_by_reason.items() if v > 0}
        total_excluded = sum(excluded_by_reason.values())

        return {
            "targets": final_targets,
            "count": len(final_targets),
            "platform": plat,
            "topic": topic,
            "api_status": "error" if fetch_error else "success",
            "error_message": fetch_error,
            "is_real_search": any(not c.get("is_demo", False) for c in final_targets),
            "summary": {
                "scanned": scanned_count,
                "included": len(final_targets),
                "excluded": total_excluded,
                "excluded_by_reason": clean_excluded_by_reason,
            },
        }

    def _fetch_threads_candidates(
        self,
        topic: str,
        allow_demo_seeds: bool = False,
        search_type: str = "RECENT",
        limit: int = 30,
        now_ts: Optional[int] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Threads 공식 키워드 검색 API를 호출하여 최신 게시물 수집."""
        candidates: List[Dict[str, Any]] = []
        queries = DEFAULT_TOPIC_QUERIES.get(topic) or [topic]
        now = int(now_ts or time.time())
        fetch_error: Optional[str] = None

        # 1. 공식 키워드 검색 API 호출
        for q in queries[:2]:  # 쿼리당 균형 수집
            try:
                res = threads_client.search_threads_posts(
                    query=q,
                    search_type=search_type,
                    limit=max(10, limit // len(queries[:2])),
                )
                items = res.get("data", [])
                for item in items:
                    p_id = str(item.get("id") or "").strip()
                    username = (item.get("username") or "").strip()
                    if not p_id or not username:
                        continue

                    # 타임스탬프 파싱
                    ts_raw = item.get("timestamp")
                    parsed_ts = self._parse_iso_timestamp(ts_raw, fallback=now)
                    permalink = item.get("permalink") or f"https://www.threads.net/@{username}/post/{p_id}"

                    # 계정 식별자는 게시물 ID(p_id)가 아닌 작성자 식별자(owner_id 또는 username)여야 함
                    owner_id = str(item.get("owner", {}).get("id") if isinstance(item.get("owner"), dict) else "").strip()
                    account_identifier = owner_id or username

                    candidates.append({
                        "platform": "threads",
                        "account_id": account_identifier,
                        "username": username,
                        "post_id": p_id,
                        "post_text": item.get("text") or "",
                        "post_url": permalink,
                        "profile_url": f"https://www.threads.net/@{username}",
                        "discovered_via": f"Threads 공식 키워드 검색 ('{q}')",
                        "search_query": q,
                        "timestamp": parsed_ts,
                        "has_replies": bool(item.get("has_replies")),
                        "is_demo": False,
                    })
            except Exception as exc:
                fetch_error = str(exc)
                logger.warning("Threads 공식 검색 실패 ('%s'): %s", q, exc)

        # 2. 공식 검색 실패 또는 결과 0건일 때 데모 시드 fallback (명시적 allow_demo_seeds=True 일 때만!)
        if not candidates and allow_demo_seeds:
            logger.info("공식 검색 결과가 없어 데모 시드 풀을 로드합니다. (allow_demo_seeds=True)")
            for s in DEMO_THREADS_SEED_TARGETS:
                if topic and topic != "전체" and topic not in s["topic"]:
                    continue
                candidates.append({
                    "platform": "threads",
                    "account_id": s["account_id"],
                    "username": s["username"],
                    "post_id": s["post_id"],
                    "post_text": s["text"],
                    "post_url": s["post_url"],
                    "profile_url": f"https://www.threads.net/@{s['username']}",
                    "discovered_via": f"데모 시드 탐색 ({s['topic']})",
                    "search_query": s["topic"],
                    "timestamp": now - random.randint(600, 3600),
                    "has_replies": True,
                    "is_demo": True,
                })

        return candidates, fetch_error

    def _fetch_x_candidates(
        self,
        topic: str = "",
        allow_demo_seeds: bool = False,
        limit: int = 30,
        now_ts: Optional[int] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """X(트위터) 활성 후보군 수집."""
        candidates: List[Dict[str, Any]] = []
        now = int(now_ts or time.time())
        fetch_error: Optional[str] = None

        if allow_demo_seeds:
            x_seeds = [
                {"account_id": "ai_trend_kr", "username": "ai_trend_kr", "post_id": "189012345678901", "text": "최신 오픈소스 AI 에이전트 소식 공유합니다. AI 관심 있는 분들 소통해요!", "topic": "AI"},
                {"account_id": "dev_feed_kr", "username": "dev_feed_kr", "post_id": "189012345678902", "text": "생산성을 10배 올려주는 파이썬 자동화 스크립트 모음. 맞팔 환영합니다.", "topic": "개발자"},
                {"account_id": "startup_daily", "username": "startup_daily", "post_id": "189012345678903", "text": "초기 창업팀이 겪는 3가지 실수와 극복 과정. 소통하는 스타트업 빌더 환영!", "topic": "스타트업"},
                {"account_id": "growth_hacker", "username": "growth_hacker", "post_id": "189012345678904", "text": "SNS 채널 트래픽 오가닉하게 모으는 방법. 스하리/소통 좋아합니다.", "topic": "스하리"},
            ]
            for s in x_seeds:
                if topic and topic != "전체" and topic not in s["topic"]:
                    continue
                candidates.append({
                    "platform": "x",
                    "account_id": s["account_id"],
                    "username": s["username"],
                    "post_id": s["post_id"],
                    "post_text": s["text"],
                    "post_url": f"https://x.com/{s['username']}/status/{s['post_id']}",
                    "profile_url": f"https://x.com/{s['username']}",
                    "discovered_via": f"X 트렌드 피드 ({s['topic']})",
                    "search_query": s["topic"],
                    "timestamp": now - random.randint(300, 3600),
                    "has_replies": True,
                    "is_demo": True,
                })
        return candidates, fetch_error

    @staticmethod
    def _parse_iso_timestamp(ts_str: Any, fallback: int) -> int:
        """ISO-8601 타임스탬프 문자열을 정수 유닉스 타임으로 변환."""
        if not ts_str:
            return fallback
        if isinstance(ts_str, (int, float)):
            return int(ts_str)
        try:
            # e.g., 2026-10-04T02:40:00+0000 or Z
            clean = str(ts_str).replace("Z", "+00:00")
            dt = datetime.datetime.fromisoformat(clean)
            return int(dt.timestamp())
        except Exception:
            return fallback
