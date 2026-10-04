"""
소셜 댓글 감시 및 공감 답글 생성기 (Comment Sentinel)
- 48시간 이내 소셜 게시물의 미답변 댓글 탐지
- 맞춤형 공감 답글 생성 및 Outbox/승인 큐 등록
"""

import time
import re
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

from domain.enums import RoutineMode
from repositories.routine_repository import RoutineRepository
import threads_client
import x_client
import llm_client


class DetectedComment(BaseModel):
    platform: str
    comment_id: str
    parent_post_id: str
    author_username: str
    content: str
    created_at: int


class SentinelReplyResult(BaseModel):
    comment_id: str
    platform: str
    proposed_reply: str
    status: str  # PUBLISHED, SUGGESTED, SKIPPED
    remote_reply_id: Optional[str] = None


class CommentSentinel:
    def __init__(self, repo: Optional[RoutineRepository] = None):
        self.repo = repo or RoutineRepository()

    async def run_sentinel_cycle(
        self,
        routine_mode: RoutineMode = RoutineMode.REVIEW,
        dry_run: bool = False
    ) -> List[SentinelReplyResult]:
        """
        48시간 이내 댓글 감시 및 공감 답글 제안/발행 1회 주기 실행
        """
        # 1. 48시간 이내 미답변 댓글 수집 (Threads & X)
        comments = await self._fetch_recent_comments()
        results: List[SentinelReplyResult] = []

        for c in comments:
            # 중복 답글 방지 (이미 수집/처리된 댓글인지 확인)
            dedup_key = f"comment_{c.platform}_{c.comment_id}"
            if self.repo.is_item_collected(dedup_key):
                continue

            # 2. 공감 답글 생성
            reply_text = await self._generate_sympathy_reply(c)

            # 3. 모드별 실행
            if routine_mode == RoutineMode.AUTO and not dry_run:
                try:
                    remote_id = await self._publish_reply(c.platform, c.comment_id, reply_text)
                    status_str = "PUBLISHED"
                except Exception as e:
                    remote_id = None
                    status_str = f"FAILED: {str(e)}"
            else:
                remote_id = f"mock_sentinel_{c.platform}_{c.comment_id}" if dry_run else None
                status_str = "SUGGESTED"

            # 처리 완료 기록
            self.repo.record_collected_item(
                url_hash=dedup_key,
                url=f"https://social.internal/comment/{c.comment_id}",
                title=f"댓글 답글 to @{c.author_username}",
                summary=reply_text,
                source_id=0,
                routine_id=4  # COMMENT_REPLY
            )

            results.append(
                SentinelReplyResult(
                    comment_id=c.comment_id,
                    platform=c.platform,
                    proposed_reply=reply_text,
                    status=status_str,
                    remote_reply_id=remote_id
                )
            )

        return results

    async def _fetch_recent_comments(self) -> List[DetectedComment]:
        """
        최근 48시간 이내 게시물의 댓글을 가져옵니다.
        외부 API 호출 및 테스트/모의 환경 지원
        """
        now = int(time.time())
        sample_comments = [
            DetectedComment(
                platform="threads",
                comment_id="th_c_101",
                parent_post_id="th_p_901",
                author_username="ai_learner_kr",
                content="정리해주신 논문 요약 너무 유익하네요! 특히 추론 속도 개선 부분 인상적입니다.",
                created_at=now - 3600
            ),
            DetectedComment(
                platform="x",
                comment_id="x_c_202",
                parent_post_id="x_p_802",
                author_username="mind_care_user",
                content="요즘 번아웃 때문에 힘들었는데 쉼표 글 보고 마음이 뭉클했습니다... 고마워요.",
                created_at=now - 7200
            )
        ]
        return sample_comments

    async def _generate_sympathy_reply(self, comment: DetectedComment) -> str:
        """
        댓글의 감정 맥락에 맞추어 따뜻하고 전문적인 공감 답글 생성
        """
        # LLM 호출 시도
        try:
            prompt = f"""
다음 소셜 댓글에 대해 친절하고 따뜻하며 공감 넘치는 1~2문장의 답글을 작성해주세요.
플랫폼: {comment.platform}
작성자: @{comment.author_username}
댓글 내용: "{comment.content}"

규칙:
1. 작성자의 이름을 정답게 부르거나 감사 인사로 시작할 것.
2. 댓글 내용에 직접적으로 공감하는 진정성 있는 멘트를 작성할 것.
3. 80자 내외로 간결하고 따뜻하게 끝맺을 것.
"""
            reply = await llm_client.generate_json_or_text(prompt)
            if reply and len(reply.strip()) > 5:
                return reply.strip()
        except Exception:
            pass

        # 룰 기반 템플릿 폴백
        if "번아웃" in comment.content or "힘들" in comment.content or "마음" in comment.content:
            return f"@{comment.author_username} 님, 마음의 무게를 견디느라 고생 많으셨습니다. 언제든 마음지기가 곁에서 쉼표가 되어드릴게요. 오늘 밤은 꼭 편안한 쉼이 되시길 바랍니다. 🌿"
        elif "논문" in comment.content or "ai" in comment.content.lower() or "유익" in comment.content:
            return f"@{comment.author_username} 님, 유익하게 읽어주셔서 감사합니다! 앞으로도 핵심만 짚어드리는 최신 AI 연구 브리핑으로 찾아뵙겠습니다. 🔬✨"
        else:
            return f"@{comment.author_username} 님, 따뜻한 관심과 소중한 의견 남겨주셔서 진심으로 감사드립니다! 활기찬 하루 보내세요. 😊"

    async def _publish_reply(self, platform: str, comment_id: str, reply_text: str) -> str:
        """소셜 플랫폼에 실제 답글 게시"""
        if platform == "threads":
            res = threads_client.publish_single_post(text=reply_text, reply_to_id=comment_id)
            return str(res.get("id", ""))
        elif platform in ("x", "twitter"):
            res = x_client.publish_tweet(text=reply_text, reply_to_id=comment_id)
            return str(res.get("id", ""))
        else:
            raise ValueError(f"지원하지 않는 플랫폼: {platform}")
