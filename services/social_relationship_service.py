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

    def resolve_actor_identities(
        self,
        platform: str,
        actor_account_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """플랫폼 설정 및 인증 상태로부터 본인 식별자 풀 및 안정적 기본 actor를 도출.

        Returns:
            {
                "primary_actor": str,            # 저장 시 사용할 가장 안정적인 계정 ID (user_id 우선, username 보조, 'me' 폴백)
                "actor_identity_pool": Set[str], # DB 조회 시 사용할 모든 식별자 집합 (user_id, username, 정규화키, 'me')
                "self_usernames": Set[str],      # 정규화된 본인 사용자명 집합
                "self_user_ids": Set[str],       # 본인 고유 계정 ID 집합
            }
        """
        norm_platform = (platform or "threads").strip().lower()
        self_usernames: Set[str] = set()
        self_user_ids: Set[str] = set()

        if norm_platform == "threads":
            try:
                import threads_client
                conf = threads_client.load_config()
                cfg_uname = (conf.get("username") or "").strip()
                cfg_uid = (conf.get("user_id") or "").strip()
                if cfg_uname:
                    self_usernames.add(self.normalize_key(cfg_uname))
                if cfg_uid:
                    self_user_ids.add(cfg_uid)
            except Exception as exc:
                logger.debug("Threads 설정 로드 실패 (무시 가능): %s", exc)
        elif norm_platform == "x":
            try:
                import x_client
                conf = x_client.load_config()
                cfg_uname = (conf.get("username") or "").strip()
                cfg_uid = (conf.get("user_id") or "").strip()
                if cfg_uname:
                    self_usernames.add(self.normalize_key(cfg_uname))
                if cfg_uid:
                    self_user_ids.add(cfg_uid)
            except Exception as exc:
                logger.debug("X 설정 로드 실패 (무시 가능): %s", exc)

        explicit_actor = (actor_account_id or "").strip()
        if explicit_actor:
            self_user_ids.add(explicit_actor)
            self_usernames.add(self.normalize_key(explicit_actor))

        # 1순위: 명시적 actor, 2순위: user_id, 3순위: username, 4순위: "me"
        primary_actor = (
            explicit_actor
            or next((uid for uid in self_user_ids if uid and uid != "me"), None)
            or next((uname for uname in self_usernames if uname and uname != "me"), None)
            or "me"
        )

        actor_identity_pool: Set[str] = set(self_user_ids) | set(self_usernames) | {"me"}
        if primary_actor:
            actor_identity_pool.add(primary_actor)
            actor_identity_pool.add(self.normalize_key(primary_actor))

        return {
            "primary_actor": primary_actor,
            "actor_identity_pool": actor_identity_pool,
            "self_usernames": self_usernames,
            "self_user_ids": self_user_ids,
        }

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

        # 플랫폼 설정 기반 본인 식별자 및 조회 풀 도출
        resolved = self.resolve_actor_identities(platform=norm_platform, actor_account_id=norm_actor)

        # 1. 실행 계정 본인 여부 판정 (우선순위 1: self_account)
        self_names = set(resolved["self_usernames"]) | {self.normalize_key(u) for u in (self_usernames or set()) if u}
        self_ids = set(resolved["self_user_ids"]) | {(i or "").strip() for i in (self_user_ids or set()) if i}
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
            return RelationshipEvaluationResult(
                excluded=False,
                reason=None,
                evidence=[],
                last_seen_at=None,
            )

        # 3. 저장소에서 관계 증거 수집 (식별자 다중 풀 활용: user_id, username, me 모두 매칭)
        actor_identity_pool = set(resolved["actor_identity_pool"]) | set(self_ids) | set(self_names)
        if norm_actor:
            actor_identity_pool.add(norm_actor)
            actor_identity_pool.add(self.normalize_key(norm_actor))
        actor_identity_pool.add("me")

        all_evidence: List[Dict[str, Any]] = []
        for key in candidate_keys:
            ev_list = self.store.get_relationship_evidence(
                platform=norm_platform,
                actor_account_id=actor_identity_pool,
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
        expires_at = (now + (expires_in_days * 86400)) if (expires_in_days is not None and expires_in_days > 0) else None
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

    def batch_register_known_followers(
        self,
        platform: str,
        actor_account_id: Optional[str],
        usernames: List[str],
        expires_in_days: Optional[int] = None,
        now_ts: Optional[int] = None,
    ) -> int:
        """사용자가 직접 입력/가져온 기존 팔로워/맞팔 유저명들을 일괄 등록하여 영구 제외 (기본 expires_at=None)."""
        resolved = self.resolve_actor_identities(platform=platform, actor_account_id=actor_account_id)
        effective_actor = resolved["primary_actor"]

        count = 0
        now = int(now_ts or time.time())
        expires_at = (now + (expires_in_days * 86400)) if (expires_in_days is not None and expires_in_days > 0) else None

        seen_keys: Set[str] = set()
        for u in usernames:
            norm_u = self.normalize_key(u)
            if norm_u and norm_u not in seen_keys:
                seen_keys.add(norm_u)
                self.store.upsert_relationship(
                    platform=platform.lower(),
                    actor_account_id=effective_actor,
                    target_account_key=norm_u,
                    relationship_type="known_follower",
                    source="manual_import",
                    target_user_id=None,
                    target_username=u.strip().lstrip("@"),
                    confidence="confirmed",
                    expires_at=expires_at,
                    now_ts=now,
                )
                count += 1
        return count

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
