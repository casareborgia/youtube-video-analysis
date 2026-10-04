"""소셜 관계 판정 및 관계 캐시 관리 서비스 (SocialRelationshipService).

Threads & X 플랫폼에서 본인 계정, 기존 팔로워, 기존 상호작용자(스하리 이력), 댓글/답글 작성자 등을
단일화된 우선순위 정책에 따라 판정하여 신규 발굴 큐 및 실행 직전 검증 단계에서 제외합니다.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from social_store import (
    RELATIONSHIP_PRIORITY_ORDER,
    VALID_RELATIONSHIP_TYPES,
    SocialStore,
    normalize_account_key,
)

logger = logging.getLogger("SocialRelationshipService")


@dataclass
class RelationshipEvaluationResult:
    excluded: bool
    reason: Optional[str] = None
    evidence: List[str] = field(default_factory=list)
    last_seen_at: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SocialRelationshipService:
    """계정 식별자 정규화, 관계 신호 조회/등록 및 우선순위 기반 배제 판정 서비스."""

    def __init__(self, store: Optional[SocialStore] = None):
        self.store = store or SocialStore()

    @staticmethod
    def normalize_key(raw_key: str) -> str:
        """계정 식별자 정규화 (@ 제거, 공백 제거, 소문자화)."""
        return normalize_account_key(raw_key)

    def evaluate_target(
        self,
        platform: str,
        actor_account_id: str,
        target_username: str = "",
        target_user_id: str = "",
        target_post_id: str = "",
        self_usernames: Optional[Set[str]] = None,
        self_user_ids: Optional[Set[str]] = None,
        now_ts: Optional[int] = None,
    ) -> RelationshipEvaluationResult:
        """단일 타겟에 대해 신규 발굴 모드 배제 여부를 우선순위에 따라 평가."""
        now = int(now_ts or time.time())
        norm_platform = platform.lower()
        norm_actor = (actor_account_id or "").strip()
        norm_target_user = self.normalize_key(target_username)
        norm_target_id = (target_user_id or "").strip()

        # 1. 실행 계정 본인 여부 판정 (우선순위 1: self_account)
        self_names = {self.normalize_key(u) for u in (self_usernames or set()) if u}
        self_ids = {(i or "").strip() for i in (self_user_ids or set()) if i}
        if norm_actor:
            self_names.add(self.normalize_key(norm_actor))
            self_ids.add(norm_actor)

        if (norm_target_user and norm_target_user in self_names) or (
            norm_target_id and norm_target_id in self_ids
        ):
            return RelationshipEvaluationResult(
                excluded=True,
                reason="self_account",
                evidence=["target_matches_actor_identity"],
                last_seen_at=now,
            )

        # 2. 계정 식별 키 목록 도출 (username 우선, user_id 보조, post_id 폴백)
        candidate_keys: List[str] = []
        if norm_target_user:
            candidate_keys.append(norm_target_user)
        if norm_target_id and norm_target_id != norm_target_user:
            candidate_keys.append(norm_target_id)
        if not candidate_keys and target_post_id:
            candidate_keys.append(self.normalize_key(target_post_id))

        if not candidate_keys:
            # 식별자가 아예 없는 경우는 안전을 위해 통과시키지 않거나 알 수 없음 처리
            return RelationshipEvaluationResult(
                excluded=False,
                reason=None,
                evidence=[],
                last_seen_at=None,
            )

        # 3. 저장소에서 관계 증거 수집
        all_evidence: List[Dict[str, Any]] = []
        for key in candidate_keys:
            ev_list = self.store.get_relationship_evidence(
                platform=norm_platform,
                actor_account_id=norm_actor,
                target_account_key=key,
                now_ts=now,
            )
            all_evidence.extend(ev_list)

        if not all_evidence:
            return RelationshipEvaluationResult(
                excluded=False,
                reason=None,
                evidence=[],
                last_seen_at=None,
            )

        # 4. 우선순위 순서대로 최고 순위 배제 사유 결정
        type_to_item = {item["relationship_type"]: item for item in all_evidence}
        evidence_descriptions = [
            f"{item['relationship_type']}:{item['source']}" for item in all_evidence
        ]

        for prio in RELATIONSHIP_PRIORITY_ORDER:
            if prio in type_to_item:
                primary = type_to_item[prio]
                return RelationshipEvaluationResult(
                    excluded=True,
                    reason=prio,
                    evidence=evidence_descriptions,
                    last_seen_at=primary.get("last_seen_at"),
                )

        first = all_evidence[0]
        return RelationshipEvaluationResult(
            excluded=True,
            reason=first.get("relationship_type") or "engaged_before",
            evidence=evidence_descriptions,
            last_seen_at=first.get("last_seen_at"),
        )

    # ==========================================
    # 관계 신호 등록 (댓글, 답글, 스하리, 팔로워 등)
    # ==========================================
    def record_commenter(
        self,
        platform: str,
        actor_account_id: str,
        commenter_username: str,
        commenter_user_id: Optional[str] = None,
        post_id: Optional[str] = None,
        expires_in_days: int = 180,
        now_ts: Optional[int] = None,
    ) -> int:
        """내 게시물에 댓글/답글을 단 작성자를 commented_on_my_content 관계로 기록 (기본 180일 보존)."""
        norm_user = self.normalize_key(commenter_username)
        if not norm_user:
            return 0
        now = int(now_ts or time.time())
        expires_at = now + (expires_in_days * 86400) if expires_in_days > 0 else None
        meta = {"post_id": post_id} if post_id else {}
        return self.store.upsert_relationship(
            platform=platform.lower(),
            actor_account_id=actor_account_id,
            target_account_key=norm_user,
            relationship_type="commented_on_my_content",
            source="comment_sync",
            target_user_id=commenter_user_id,
            target_username=commenter_username,
            confidence="observed",
            metadata=meta,
            expires_at=expires_at,
            now_ts=now,
        )

    def record_reply_sent(
        self,
        platform: str,
        actor_account_id: str,
        target_username: str,
        target_user_id: Optional[str] = None,
        post_id: Optional[str] = None,
        now_ts: Optional[int] = None,
    ) -> int:
        """내가 상대방 댓글에 답글을 성공적으로 발송한 이력을 replied_by_me 관계로 기록."""
        norm_user = self.normalize_key(target_username)
        if not norm_user:
            return 0
        now = int(now_ts or time.time())
        meta = {"post_id": post_id} if post_id else {}
        return self.store.upsert_relationship(
            platform=platform.lower(),
            actor_account_id=actor_account_id,
            target_account_key=norm_user,
            relationship_type="replied_by_me",
            source="reply_sent",
            target_user_id=target_user_id,
            target_username=target_username,
            confidence="confirmed",
            metadata=meta,
            expires_at=None,
            now_ts=now,
        )

    def record_engagement_success(
        self,
        platform: str,
        actor_account_id: str,
        action: str,
        target_username: Optional[str] = None,
        target_post_id: Optional[str] = None,
        now_ts: Optional[int] = None,
    ) -> int:
        """스하리(좋아요, 리포스트, 팔로우) 실제 성공 이력을 관계 캐시에 기록."""
        key = self.normalize_key(target_username or target_post_id or "")
        if not key:
            return 0
        now = int(now_ts or time.time())
        act = action.lower()
        if act == "follow":
            rel_type = "followed_or_following"
        else:
            rel_type = "engaged_before"

        meta = {"action": act, "target_post_id": target_post_id}
        return self.store.upsert_relationship(
            platform=platform.lower(),
            actor_account_id=actor_account_id,
            target_account_key=key,
            relationship_type=rel_type,
            source="engagement_success",
            target_username=target_username,
            confidence="confirmed",
            metadata=meta,
            expires_at=None,
            now_ts=now,
        )

    def record_known_follower(
        self,
        platform: str,
        actor_account_id: str,
        follower_username: str,
        follower_user_id: Optional[str] = None,
        expires_in_days: int = 30,
        now_ts: Optional[int] = None,
    ) -> int:
        """공식 API 또는 신뢰 가능한 목록에서 확인된 팔로워 기록 (기본 30일 보존 후 재동기화)."""
        norm_user = self.normalize_key(follower_username)
        if not norm_user:
            return 0
        now = int(now_ts or time.time())
        expires_at = now + (expires_in_days * 86400) if expires_in_days > 0 else None
        return self.store.upsert_relationship(
            platform=platform.lower(),
            actor_account_id=actor_account_id,
            target_account_key=norm_user,
            relationship_type="known_follower",
            source="api_sync",
            target_user_id=follower_user_id,
            target_username=follower_username,
            confidence="confirmed",
            expires_at=expires_at,
            now_ts=now,
        )

    def suppress_account(
        self,
        platform: str,
        actor_account_id: str,
        target_account_key: str,
        reason: str = "",
        target_username: Optional[str] = None,
        now_ts: Optional[int] = None,
    ) -> int:
        """운영자 수동 제외 또는 차단 등록."""
        return self.store.suppress_account(
            platform=platform.lower(),
            actor_account_id=actor_account_id,
            target_account_key=target_account_key,
            reason=reason,
            target_username=target_username,
            now_ts=now_ts,
        )

    def unsuppress_account(
        self,
        platform: str,
        actor_account_id: str,
        target_account_key: str,
    ) -> bool:
        """수동 제외 해제."""
        return self.store.unsuppress_account(
            platform=platform.lower(),
            actor_account_id=actor_account_id,
            target_account_key=target_account_key,
        )

    def expire_old_relationships(self, now_ts: Optional[int] = None) -> int:
        """만료된 관찰 신호 정리."""
        return self.store.expire_relationships(now_ts=now_ts)

    def get_status(self, platform: str, actor_account_id: str) -> Dict[str, Any]:
        """관계 캐시 통계 및 상태 반환."""
        now = int(time.time())
        rels = self.store.list_relationships(
            platform=platform.lower(),
            actor_account_id=actor_account_id,
            active_only=True,
            now_ts=now,
        )
        counts_by_type: Dict[str, int] = {}
        most_recent_ts = 0
        for r in rels:
            rtype = r.get("relationship_type", "unknown")
            counts_by_type[rtype] = counts_by_type.get(rtype, 0) + 1
            seen = int(r.get("last_seen_at") or 0)
            if seen > most_recent_ts:
                most_recent_ts = seen

        return {
            "platform": platform,
            "actor_account_id": actor_account_id,
            "total_active_relationships": len(rels),
            "counts_by_type": counts_by_type,
            "latest_relationship_at": most_recent_ts,
        }
