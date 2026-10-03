"""로컬 예약 실행기 및 재시도 엔진 모듈.

작업지시서 Phase 7 요구사항 충족:
- 별도 클라우드 서비스 없이 앱 프로세스 내부에서 동작하는 로컬 예약 실행기
- 서버 시작 시 실행되지 못한 예약 작업 자동 로드 및 복구
- 동일 작업을 동시에 두 번 잡지 않도록 원자적 리스 점유(SocialStore.acquire_job_lease) 연동
- 일시적 네트워크·서버 오류에만 지수 백오프와 최대 재시도(Exponential Backoff & Retries) 적용
- 인증/입력/권한 오류 등 영구적 실패는 자동 재시도하지 않고 failed로 격리
- 앱 종료 중 지난 예약은 정책에 따라 유예 시간 내 '대기 후 즉시 실행' 또는 '사용자 확인 필요(needs_approval)' 처리
- 가상 시계(Injectable Clock / Time Provider) 주입을 통해 임의 시간과 백오프 테스트 완벽 지원
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import engagement_automation
import publish_service
import reply_service
import social_store
from social_store import SocialStore, sanitize_sensitive_data

logger = logging.getLogger(__name__)


# ==========================================
# 1. 일시적 오류 vs 영구적 오류 분류 및 백오프 정책
# ==========================================
DEFAULT_RETRYABLE_CODES: Set[str] = {
    "TIMEOUT",
    "RATE_LIMIT",
    "NETWORK_ERROR",
    "CONNECTION_ERROR",
    "SERVER_ERROR",
    "HTTP_500",
    "HTTP_502",
    "HTTP_503",
    "HTTP_504",
    "HTTP_429",
}

DEFAULT_NON_RETRYABLE_CODES: Set[str] = {
    "UNAUTHORIZED",
    "FORBIDDEN",
    "INVALID_CREDENTIALS",
    "TOKEN_EXPIRED",
    "BAD_REQUEST",
    "INVALID_INPUT",
    "UNSUPPORTED",
    "NOT_FOUND",
    "PERMISSION_REQUIRED",
    "DUPLICATE_REJECTED",
    "HTTP_400",
    "HTTP_401",
    "HTTP_403",
    "HTTP_404",
}


class RetryPolicy:
    """일시적 오류에 대한 지수 백오프 및 최대 재시도 정책."""

    def __init__(
        self,
        max_retries: int = 3,
        base_delay_seconds: int = 30,
        max_delay_seconds: int = 3600,
        retryable_codes: Optional[Set[str]] = None,
        non_retryable_codes: Optional[Set[str]] = None,
    ):
        self.max_retries = max(0, int(max_retries))
        self.base_delay_seconds = max(1, int(base_delay_seconds))
        self.max_delay_seconds = max(self.base_delay_seconds, int(max_delay_seconds))
        self.retryable_codes = set(retryable_codes) if retryable_codes is not None else DEFAULT_RETRYABLE_CODES
        self.non_retryable_codes = set(non_retryable_codes) if non_retryable_codes is not None else DEFAULT_NON_RETRYABLE_CODES

    def is_retryable(self, error_code: str, error_message: str) -> bool:
        """
        오류 코드 및 메시지를 분석하여 일시적(재시도 가능)인지 판별.
        영구적 오류(인증 실패, 잘못된 요청 등)는 절대 재시도하지 않음.
        """
        code_upper = str(error_code or "").strip().upper()
        msg_lower = str(error_message or "").strip().lower()

        # 명시적 비재시도 코드
        if code_upper in self.non_retryable_codes:
            return False

        # 비재시도 키워드 감지 (인증/권한/요청오류)
        non_retry_patterns = [
            "unauthorized", "invalid token", "forbidden", "bad request",
            "not found", "permission", "invalid credentials", "client error",
        ]
        if any(pat in msg_lower for pat in non_retry_patterns):
            return False

        # 명시적 재시도 코드
        if code_upper in self.retryable_codes:
            return True

        # 일시적 오류 키워드 감지 (네트워크, 타임아웃, 5xx, rate limit)
        retry_patterns = [
            "timeout", "timed out", "connection reset", "connection refused",
            "network error", "rate limit", "too many requests", "429",
            "500 internal", "502 bad gateway", "503 service", "504 gateway",
            "server error",
        ]
        if any(pat in msg_lower for pat in retry_patterns):
            return True

        return False

    def compute_backoff(self, retry_count: int) -> int:
        """지수 백오프 계산: min(base_delay * 2^retry_count, max_delay)"""
        delay = self.base_delay_seconds * (2 ** max(0, retry_count))
        return min(int(delay), self.max_delay_seconds)


class MissedSchedulePolicy:
    """앱 종료 등으로 실행 시각이 지난 예약 작업에 대한 처리 정책."""

    def __init__(self, grace_period_seconds: int = 3600):
        # 유예 기간 (기본 1시간). 1시간 이내 지난 작업은 즉시 실행, 1시간 초과 시 needs_approval
        self.grace_period_seconds = max(0, int(grace_period_seconds))

    def evaluate_missed_job(self, scheduled_at: int, now_ts: int) -> str:
        """
        - 'run_now': 유예 시간 이내로 즉시 실행 가능
        - 'needs_approval': 유예 시간 초과로 사용자 확인 필요
        """
        if scheduled_at <= 0:
            return "run_now"
        delay = now_ts - scheduled_at
        if delay <= self.grace_period_seconds:
            return "run_now"
        return "needs_approval"


# ==========================================
# 2. 로컬 예약 실행기 (LocalJobScheduler)
# ==========================================
class LocalJobScheduler:
    """
    별도 외부 브로커 없이 로컬 SQLite 저장소와 스레드 기반으로 동작하는 소셜 예약 작업 실행기.
    """

    def __init__(
        self,
        store: Optional[SocialStore] = None,
        pub_service: Optional[publish_service.PublishService] = None,
        rep_service: Optional[reply_service.ReplyService] = None,
        eng_service: Optional[engagement_automation.EngagementAutomationService] = None,
        retry_policy: Optional[RetryPolicy] = None,
        missed_policy: Optional[MissedSchedulePolicy] = None,
        time_provider: Optional[Callable[[], float]] = None,
        worker_id: Optional[str] = None,
    ):
        self.store = store or SocialStore()
        self.publish_service = pub_service or publish_service.PublishService(store=self.store)
        self.reply_service = rep_service or reply_service.ReplyService(store=self.store)
        self.engagement_service = eng_service or engagement_automation.get_service()
        self.retry_policy = retry_policy or RetryPolicy()
        self.missed_policy = missed_policy or MissedSchedulePolicy()
        self.time_provider = time_provider or time.time
        self.worker_id = (worker_id or f"local_scheduler_{uuid.uuid4().hex[:6]}").strip()

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._stats = {
            "ticks": 0,
            "jobs_executed": 0,
            "jobs_succeeded": 0,
            "jobs_failed": 0,
            "jobs_retried": 0,
            "jobs_stale_recovered": 0,
            "jobs_needs_approval": 0,
        }

    def now(self) -> int:
        return int(self.time_provider())

    # ==========================================
    # 주기적 1회 실행 사이클 (tick)
    # ==========================================
    def run_once(self) -> Optional[Dict[str, Any]]:
        """
        단일 스케줄러 틱 실행:
        1. 장기 잠금 만료(stale lease) 리스 회수
        2. 유예 시간 초과 예약 작업 감지 및 needs_approval 전환
        3. 실행 대상 예약 작업 1건을 원자적으로 점유(acquire_job_lease)
        4. 작업 유형별 디스패치 및 결과/재시도 반영
        """
        now_ts = self.now()
        with self._lock:
            self._stats["ticks"] += 1

        # 1. 만료된 리스 및 stale 예약 정리
        recovered = self.store.reconcile_stale_reservations(timeout_seconds=300)
        if recovered > 0:
            with self._lock:
                self._stats["jobs_stale_recovered"] += recovered

        # 2. 유예 시간 초과 예약 검사
        self._check_missed_schedules(now_ts)

        # 3. 도래한 작업 원자적 점유 (approved_at > 0 및 scheduled_at <= now_ts)
        job = self.store.acquire_job_lease(
            worker_id=self.worker_id,
            now_timestamp=now_ts,
            lease_timeout_seconds=300,
        )
        if not job:
            return None

        job_id = job["job_id"]
        with self._lock:
            self._stats["jobs_executed"] += 1

        # 4. 작업 디스패치 및 실행
        try:
            exec_result = self._dispatch_job(job)
            with self._lock:
                self._stats["jobs_succeeded"] += 1
            return {
                "job_id": job_id,
                "status": "succeeded",
                "result": exec_result,
            }
        except Exception as exc:
            err_msg = sanitize_sensitive_data(str(exc))
            err_code = getattr(exc, "code", "EXECUTION_ERROR")
            return self._handle_job_failure(job, err_code, err_msg, now_ts)

    def _check_missed_schedules(self, now_ts: int) -> None:
        """유예 기간(grace_period)을 초과하여 장시간 방치된 예약 작업을 needs_approval 로 전환."""
        threshold = now_ts - self.missed_policy.grace_period_seconds
        with self.store._connect() as conn:
            # scheduled 상태이고 scheduled_at이 유예 한계보다 오래된 작업 조회
            rows = conn.execute(
                """
                SELECT job_id, scheduled_at FROM social_jobs
                WHERE status = 'scheduled'
                  AND scheduled_at > 0
                  AND scheduled_at < ?
                """,
                (threshold,),
            ).fetchall()
            for row in rows:
                jid = row["job_id"]
                conn.execute(
                    """
                    UPDATE social_jobs
                    SET status = 'needs_approval',
                        last_error_code = 'MISSED_SCHEDULE',
                        last_error_message = '서버 중단 등으로 예약 시각이 유예 시간을 초과하여 사용자 확인이 필요합니다.',
                        updated_at = ?
                    WHERE job_id = ? AND status = 'scheduled'
                    """,
                    (now_ts, jid),
                )
                with self._lock:
                    self._stats["jobs_needs_approval"] += 1

    def _dispatch_job(self, job: Dict[str, Any]) -> Dict[str, Any]:
        """작업 유형(publish, reply, engagement)에 따라 해당 서비스로 전달하여 실행."""
        job_id = job["job_id"]
        job_type = job["job_type"]
        dry_run = bool(job.get("dry_run", 0))

        if job_type == "publish":
            return self.publish_service.execute_publish_job(
                job_id=job_id,
                worker_id=self.worker_id,
                dry_run=dry_run,
            )

        if job_type == "reply":
            res = self.reply_service.execute_batch_replies(
                job_ids=[job_id],
                worker_id=self.worker_id,
                dry_run=dry_run,
            )
            # 배치 결과 중 실패가 있으면 예외 발생 처리
            for r in res.get("results", []):
                if r.get("status") in ("error", "unapproved_blocked", "failed"):
                    raise RuntimeError(r.get("error", "답글 실행 실패"))
            return res

        if job_type == "engagement":
            payload = job.get("content_payload", {})
            if isinstance(payload, str):
                payload = json.loads(payload)
            targets_raw = payload.get("targets", [])
            actions = payload.get("actions", ["like"])
            use_web = payload.get("use_web_fallback", False)

            # 타겟 변환
            targets = []
            for t in targets_raw:
                targets.append(
                    engagement_automation.EngagementTarget(
                        platform=t.get("platform", job.get("platform", "threads")),
                        post_id=t.get("post_id", ""),
                        account_id=t.get("account_id", job.get("actor_account_id", "")),
                        post_url=t.get("post_url", ""),
                        profile_url=t.get("profile_url", ""),
                        label=t.get("label", ""),
                    )
                )
            if not targets:
                # 기본 타겟 없으면 단일 타겟 생성
                targets.append(
                    engagement_automation.EngagementTarget(
                        platform=job.get("platform", "threads"),
                        post_id=job.get("target_id", "post_target"),
                        account_id=job.get("actor_account_id", "default_actor"),
                    )
                )

            res = self.engagement_service.execute(
                targets=targets,
                actions=actions,
                dry_run=dry_run,
                use_web_fallback=use_web,
            )
            return res

        raise ValueError(f"지원하지 않는 작업 유형입니다: {job_type}")

    def _handle_job_failure(
        self,
        job: Dict[str, Any],
        err_code: str,
        err_msg: str,
        now_ts: int,
    ) -> Dict[str, Any]:
        """오류 발생 시 재시도 가능 여부와 시도 횟수를 평가하여 백오프 예약 또는 failed 확정."""
        job_id = job["job_id"]
        current_retries = int(job.get("retry_count", 1))
        max_retries = int(job.get("max_retries", self.retry_policy.max_retries))
        attempt_idx = max(0, current_retries - 1)

        is_retryable = self.retry_policy.is_retryable(err_code, err_msg)

        if is_retryable and current_retries <= max_retries:
            # 지수 백오프 적용 후 scheduled 복귀
            backoff_delay = self.retry_policy.compute_backoff(attempt_idx)
            next_schedule = now_ts + backoff_delay

            with self.store._connect() as conn:
                conn.execute(
                    """
                    UPDATE social_jobs
                    SET status = 'scheduled',
                        scheduled_at = ?,
                        locked_by = '',
                        locked_at = 0,
                        last_error_code = ?,
                        last_error_message = ?,
                        updated_at = ?
                    WHERE job_id = ?
                    """,
                    (next_schedule, err_code, err_msg, now_ts, job_id),
                )
                # 시도 실패 기록
                conn.execute(
                    """
                    UPDATE social_job_attempts
                    SET status = 'retry_scheduled',
                        error_code = ?,
                        error_message = ?,
                        finished_at = ?
                    WHERE job_id = ? AND status = 'running' AND worker_id = ?
                    """,
                    (err_code, err_msg, now_ts, job_id, self.worker_id),
                )

            with self._lock:
                self._stats["jobs_retried"] += 1

            return {
                "job_id": job_id,
                "status": "scheduled",
                "action": "retry_scheduled",
                "next_schedule": next_schedule,
                "backoff_delay": backoff_delay,
                "retry_count": current_retries,
            }

        # 재시도 불가 또는 최대 재시도 초과 -> failed 확정
        self.store.update_job_status(
            job_id=job_id,
            status="failed",
            error_code=err_code,
            error_message=err_msg,
        )
        with self.store._connect() as conn:
            conn.execute(
                """
                UPDATE social_jobs
                SET locked_by = '', locked_at = 0
                WHERE job_id = ?
                """,
                (job_id,),
            )
            conn.execute(
                """
                UPDATE social_job_attempts
                SET status = 'failed',
                    error_code = ?,
                    error_message = ?,
                    finished_at = ?
                WHERE job_id = ? AND status = 'running' AND worker_id = ?
                """,
                (err_code, err_msg, now_ts, job_id, self.worker_id),
            )

        with self._lock:
            self._stats["jobs_failed"] += 1

        return {
            "job_id": job_id,
            "status": "failed",
            "error_code": err_code,
            "error_message": err_msg,
            "retries_exhausted": current_retries >= max_retries,
        }

    # ==========================================
    # 수동 작업 제어 (스케줄링, 취소, 재시도)
    # ==========================================
    def schedule_job(
        self,
        job_id: str,
        scheduled_at: int,
        require_approval: bool = True,
    ) -> Dict[str, Any]:
        """작업을 특정 시각으로 예약."""
        now_ts = self.now()
        job = self.store.get_job(job_id)
        if not job:
            raise ValueError(f"존재하지 않는 작업입니다: {job_id}")

        if scheduled_at <= now_ts:
            raise ValueError("예약 시각은 현재 시각 이후여야 합니다.")

        with self.store._connect() as conn:
            # 승인 필요한 경우 approved_at 설정
            approved_clause = "approved_at = CASE WHEN approved_at = 0 THEN ? ELSE approved_at END," if not require_approval else ""
            params: List[Any] = []
            if not require_approval:
                params.append(now_ts)
            params.extend([scheduled_at, now_ts, job_id])

            conn.execute(
                f"""
                UPDATE social_jobs
                SET {approved_clause}
                    status = 'scheduled',
                    scheduled_at = ?,
                    updated_at = ?
                WHERE job_id = ?
                """,
                tuple(params),
            )
        return self.store.get_job(job_id) or {}

    def cancel_job(self, job_id: str) -> Dict[str, Any]:
        """대기 또는 예약 중인 작업 취소."""
        job = self.store.get_job(job_id)
        if not job:
            raise ValueError(f"존재하지 않는 작업입니다: {job_id}")

        current_status = job.get("status")
        if current_status in ("succeeded", "cancelled"):
            return job

        if current_status == "running":
            raise ValueError("현재 실행 중인 작업은 즉시 취소할 수 없습니다.")

        now_ts = self.now()
        with self.store._connect() as conn:
            conn.execute(
                """
                UPDATE social_jobs
                SET status = 'cancelled',
                    locked_by = '',
                    locked_at = 0,
                    updated_at = ?
                WHERE job_id = ?
                """,
                (now_ts, job_id),
            )
        return self.store.get_job(job_id) or {}

    def retry_job_manually(self, job_id: str, run_immediately: bool = True) -> Dict[str, Any]:
        """실패하거나 취소된 작업을 수동으로 재시도 대기열에 등록."""
        job = self.store.get_job(job_id)
        if not job:
            raise ValueError(f"존재하지 않는 작업입니다: {job_id}")

        now_ts = self.now()
        new_status = "approved" if run_immediately else "scheduled"
        sched_time = 0 if run_immediately else (now_ts + 60)

        with self.store._connect() as conn:
            conn.execute(
                """
                UPDATE social_jobs
                SET status = ?,
                    scheduled_at = ?,
                    approved_at = CASE WHEN approved_at = 0 THEN ? ELSE approved_at END,
                    locked_by = '',
                    locked_at = 0,
                    last_error_code = '',
                    last_error_message = '',
                    updated_at = ?
                WHERE job_id = ?
                """,
                (new_status, sched_time, now_ts, now_ts, job_id),
            )

        if run_immediately:
            # 즉시 1회 실행 시도
            return self.run_once() or (self.store.get_job(job_id) or {})
        return self.store.get_job(job_id) or {}

    # ==========================================
    # 백그라운드 스레드 루프 관리
    # ==========================================
    def start(self, interval_seconds: float = 3.0) -> None:
        """백그라운드 스케줄러 스레드 시작."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._loop,
                args=(interval_seconds,),
                name="SocialSchedulerWorker",
                daemon=True,
            )
            self._thread.start()
            logger.info("Social scheduler started (worker: %s, interval: %ss)", self.worker_id, interval_seconds)

    def stop(self, timeout: float = 5.0) -> None:
        """백그라운드 스케줄러 스레드 중지."""
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._stop_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        logger.info("Social scheduler stopped (worker: %s)", self.worker_id)

    def is_running(self) -> bool:
        with self._lock:
            return self._running

    def get_status(self) -> Dict[str, Any]:
        """스케줄러 상태 및 통계 반환."""
        with self._lock:
            stats = dict(self._stats)
            is_alive = self._running and (self._thread.is_alive() if self._thread else False)
        return {
            "status": "running" if is_alive else "stopped",
            "worker_id": self.worker_id,
            "stats": stats,
            "current_time": self.now(),
        }

    def _loop(self, interval: float) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_once()
            except Exception as exc:
                logger.error("Scheduler tick error: %s", exc)
            self._stop_event.wait(timeout=interval)


# 싱글톤 인스턴스 관리
_global_scheduler: Optional[LocalJobScheduler] = None


def get_scheduler() -> LocalJobScheduler:
    global _global_scheduler
    if _global_scheduler is None:
        _global_scheduler = LocalJobScheduler()
    return _global_scheduler
