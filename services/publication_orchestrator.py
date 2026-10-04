"""
스마트 체인 발행 오케스트레이터 (Publication Orchestrator)
- Threads 및 X(Twitter) 2-Step 체인 연쇄 발행:
  Step 1 (PARENT): 외부 링크가 없는 본문(body) 발행 -> remote_id 획득
  Step 2 (FIRST_REPLY): 획득한 remote_id에 첫 번째 답글(first_reply, 원문/서비스 링크) 연결
- DRY_RUN (모의 실행), REVIEW (검토 후 승인), AUTO (즉시 자동 발행) 모드 완벽 지원
- 부분 실패(Partial Failure) 분리 격리 및 멱등키(Idempotency Key) 보호
"""

import hashlib
import json
import time
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

from domain.enums import RoutineMode, JobStatus, StepType
from domain.models import StructuredDraft
from repositories.routine_repository import RoutineRepository
import threads_client
import x_client


class StepExecutionResult(BaseModel):
    step_id: int
    platform: str
    step_type: StepType
    remote_id: Optional[str] = None
    status: str
    error_message: Optional[str] = None


class JobExecutionResult(BaseModel):
    job_id: int
    idempotency_key: str
    status: str
    dry_run: bool
    platform_results: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    error_summary: Optional[str] = None


class PublicationOrchestrator:
    def __init__(self, repo: Optional[RoutineRepository] = None):
        self.repo = repo or RoutineRepository()

    def create_chain_job(
        self,
        routine_id: int,
        draft: StructuredDraft,
        platforms: Optional[List[str]] = None,
        scheduled_at: Optional[int] = None,
        mode: RoutineMode = RoutineMode.REVIEW
    ) -> int:
        """
        초안을 바탕으로 Outbox Job과 플랫폼별 2-Step Publication Steps를 생성합니다.
        """
        target_platforms = [p.lower() for p in (platforms or ["threads", "x"])]
        now = int(time.time())
        sched_time = scheduled_at or now

        # 멱등키: 루틴ID + 토픽키 + 시간(분 단위)
        idempotency_source = f"{routine_id}_{draft.topic_key}_{sched_time // 60}"
        idempotency_key = hashlib.sha256(idempotency_source.encode("utf-8")).hexdigest()

        # outbox_job 생성 (이미 존재하는 경우 기존 job_id 반환)
        job_id = self.repo.create_outbox_job(
            routine_id=routine_id,
            idempotency_key=idempotency_key,
            topic_key=draft.topic_key,
            platforms=target_platforms,
            scheduled_at=sched_time
        )

        # 기존 Job에 이미 Steps가 등록되어 있는지 확인
        existing_job = self.repo.get_outbox_job_by_id(job_id)
        if existing_job and existing_job.get("steps"):
            return job_id

        # 각 플랫폼별 2-Step 사전 등록
        for platform in target_platforms:
            # Step 1: 본문 (PARENT)
            parent_step_id = self.repo.add_publication_step(
                job_id=job_id,
                platform=platform,
                step_type=StepType.PARENT,
                content=draft.body,
                parent_step_id=None
            )
            # Step 2: 첫 답글 (FIRST_REPLY)
            self.repo.add_publication_step(
                job_id=job_id,
                platform=platform,
                step_type=StepType.FIRST_REPLY,
                content=draft.first_reply,
                parent_step_id=parent_step_id
            )

        return job_id

    async def execute_job(
        self,
        job_id: int,
        dry_run: bool = False
    ) -> JobExecutionResult:
        """
        Outbox Job의 플랫폼별 2-Step 체인 연쇄 발행을 실행합니다.
        """
        # DB에서 job 정보 및 steps 조회
        with self.repo._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM outbox_jobs WHERE id = ?", (job_id,))
            job_row = cursor.fetchone()
            if not job_row:
                raise ValueError(f"존재하지 않는 Job ID입니다: {job_id}")

            cursor.execute("SELECT * FROM publication_steps WHERE job_id = ? ORDER BY id ASC", (job_id,))
            step_rows = cursor.fetchall()

        platforms = json.loads(job_row["platforms"]) if job_row["platforms"] else ["threads", "x"]
        idempotency_key = job_row["idempotency_key"]

        platform_results: Dict[str, Dict[str, Any]] = {}
        has_success = False
        has_failure = False

        # 플랫폼별 독립 실행 (부분 실패 격리)
        for platform in platforms:
            platform_lower = platform.lower()
            platform_steps = [s for s in step_rows if s["platform"].lower() == platform_lower]
            parent_step = next((s for s in platform_steps if s["step_type"] == StepType.PARENT.value), None)
            reply_step = next((s for s in platform_steps if s["step_type"] == StepType.FIRST_REPLY.value), None)

            if not parent_step or not reply_step:
                continue

            platform_summary = {
                "parent_id": None,
                "reply_id": None,
                "status": "PENDING",
                "error": None
            }

            try:
                # --- Step 1: 본문 (PARENT) 발행 ---
                if dry_run:
                    parent_remote_id = f"mock_{platform_lower}_parent_{job_id}_{int(time.time())}"
                else:
                    parent_remote_id = await self._publish_platform_post(
                        platform=platform_lower,
                        text=parent_step["content"],
                        reply_to_id=None
                    )

                self.repo.update_publication_step(
                    step_id=parent_step["id"],
                    status="SUCCEEDED",
                    remote_id=parent_remote_id
                )
                platform_summary["parent_id"] = parent_remote_id

                # --- Step 2: 첫 번째 답글 (FIRST_REPLY) 체인 발행 ---
                if dry_run:
                    reply_remote_id = f"mock_{platform_lower}_reply_{job_id}_{int(time.time())}"
                else:
                    reply_remote_id = await self._publish_platform_post(
                        platform=platform_lower,
                        text=reply_step["content"],
                        reply_to_id=parent_remote_id
                    )

                self.repo.update_publication_step(
                    step_id=reply_step["id"],
                    status="SUCCEEDED",
                    remote_id=reply_remote_id
                )
                platform_summary["reply_id"] = reply_remote_id
                platform_summary["status"] = "SUCCEEDED"
                has_success = True

            except Exception as e:
                err_msg = str(e)
                has_failure = True
                platform_summary["status"] = "FAILED"
                platform_summary["error"] = err_msg

                # 실패한 step 업데이트
                if not platform_summary["parent_id"]:
                    self.repo.update_publication_step(
                        step_id=parent_step["id"],
                        status="FAILED",
                        error_message=err_msg
                    )
                else:
                    self.repo.update_publication_step(
                        step_id=reply_step["id"],
                        status="FAILED",
                        error_message=err_msg
                    )

            platform_results[platform_lower] = platform_summary

        # 전체 Job 상태 산출
        if has_success and not has_failure:
            overall_status = JobStatus.SUCCEEDED.value
        elif has_success and has_failure:
            overall_status = "PARTIAL"
        else:
            overall_status = JobStatus.FAILED.value

        # DB에 Job 최종 상태 업데이트
        now = int(time.time())
        with self.repo._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE outbox_jobs SET status = ?, updated_at = ? WHERE id = ?",
                (overall_status, now, job_id)
            )
            conn.commit()

        return JobExecutionResult(
            job_id=job_id,
            idempotency_key=idempotency_key,
            status=overall_status,
            dry_run=dry_run,
            platform_results=platform_results
        )

    async def _publish_platform_post(
        self,
        platform: str,
        text: str,
        reply_to_id: Optional[str] = None
    ) -> str:
        """실제 외부 소셜 플랫폼 API 호출 브리지"""
        if platform == "threads":
            res = threads_client.publish_single_post(text=text, reply_to_id=reply_to_id)
            remote_id = str(res.get("id", ""))
            if not remote_id:
                raise RuntimeError(f"Threads 발행 응답에 ID가 없습니다: {res}")
            return remote_id

        elif platform in ("x", "twitter"):
            res = x_client.publish_tweet(text=text, reply_to_id=reply_to_id)
            remote_id = str(res.get("id", ""))
            if not remote_id:
                raise RuntimeError(f"X 발행 응답에 ID가 없습니다: {res}")
            return remote_id

        else:
            raise ValueError(f"지원하지 않는 소셜 플랫폼입니다: {platform}")
