"""Threads 및 X(Twitter) 게시물 발행 통합 실행 서비스 모듈.

작업지시서 Phase 4 요구사항 충족:
- Threads 기존 단일·타래 발행(threads_client)을 통합 서비스에 연결
- X 단일 게시물 및 연속 타래 발행(x_client)을 공식 API로 연결
- 드라이런(dry_run), 즉시 실행, 예약 실행 완벽 지원
- 타래 중간 실패(Partial Failure) 시 성공/실패 항목 기록 및 이전 성공 항목 보존(처음부터 재발행 방지)
- 동일 승인 요청의 중복 발행 방지 (Idempotency & 상태 펜싱)
- 가짜 플랫폼 어댑터(Mock Platform Adapter) 주입 가능 구조로 테스트 완벽 분리
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Callable, Dict, List, Optional

import content_service
import social_store
import threads_client
import x_client


class PublishError(Exception):
    """발행 실행 중 오류"""

    def __init__(self, message: str, code: str = "PUBLISH_FAILED", partial_results: Optional[List[Dict[str, Any]]] = None):
        super().__init__(social_store.sanitize_sensitive_data(message))
        self.code = code
        self.partial_results = partial_results or []


class PublishService:
    """Threads / X 게시물 및 타래 발행 통합 오케스트레이터"""

    def __init__(
        self,
        store: Optional[social_store.SocialStore] = None,
        threads_adapter: Optional[Callable[..., Dict[str, Any]]] = None,
        x_adapter: Optional[Callable[..., Dict[str, Any]]] = None,
    ):
        self.store = store or social_store.SocialStore()
        # 어댑터가 주입되지 않은 경우 기본 라이브 클라이언트 사용
        self._threads_adapter = threads_adapter or threads_client.publish_single_post
        self._x_adapter = x_adapter or x_client.publish_tweet

    def execute_publish_job(
        self,
        job_id: str,
        worker_id: str,
        dry_run: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        승인된 작업을 발행 실행.
        - 중복 실행 차단 (approved, partial, scheduled 상태에서만 running 가능)
        - 타래 순차 발행 및 중간 실패 시 partial 처리
        - 재실행 시 이미 성공한 항목은 건너뛰고 이어서 발행 (Resume 지원)
        """
        job = self.store.get_job(job_id)
        if not job:
            raise ValueError(f"존재하지 않는 작업 ID: {job_id}")

        # 1. 사전 승인 및 상태 검증
        if job["approved_at"] <= 0:
            raise social_store.InvalidStateTransitionError(
                f"승인되지 않은 작업은 발행할 수 없습니다 (job_id: {job_id}, status: {job['status']})."
            )

        if job["status"] not in ("approved", "scheduled", "partial", "failed"):
            raise social_store.InvalidStateTransitionError(
                f"현재 상태({job['status']})에서는 작업을 실행할 수 없습니다 (중복 실행 방지)."
            )

        # 2. 실행 시작: running 상태로 원자적 전이 (워커 소유권 펜싱 및 시도 기록)
        self.store.transition_job_status(job_id, "running", worker_id=worker_id)

        items = self.store.get_job_items(job_id)
        if not items:
            self.store.transition_job_status(
                job_id, "failed", worker_id=worker_id, error_code="EMPTY_ITEMS", error_message="발행할 항목이 없습니다."
            )
            raise PublishError("발행할 항목이 없습니다.", code="EMPTY_ITEMS")

        platform = job["platform"]
        effective_dry_run = dry_run if dry_run is not None else bool(job["dry_run"])

        published_results: List[Dict[str, Any]] = []
        last_platform_post_id: Optional[str] = None
        has_failure = False
        failure_error_msg = ""

        # 이전에 이미 성공한 항목이 있는지 확인 (Resume 용)
        for item in items:
            if item["status"] == "published" and item.get("platform_post_id"):
                last_platform_post_id = item["platform_post_id"]

        now_ts = int(time.time())

        # 3. 항목별 순차 발행 루프
        for item in items:
            idx = item["item_index"]

            # 이미 이전 시도에서 성공한 항목은 건너뜀 (처음부터 재발행하지 않음!)
            if item["status"] == "published" and item.get("platform_post_id"):
                published_results.append({
                    "item_index": idx,
                    "status": "already_published",
                    "post_id": item["platform_post_id"],
                    "url": item.get("platform_post_url", ""),
                })
                continue

            content = item["content"]
            media_url = item.get("media_url") or None

            if effective_dry_run:
                # 드라이런 가상 발행
                mock_post_id = f"mock_{platform}_{job_id}_{idx}"
                mock_post_url = f"https://{platform}.com/post/{mock_post_id}"
                self.store.update_job_item(
                    job_id=job_id,
                    item_index=idx,
                    status="published",
                    platform_post_id=mock_post_id,
                    platform_post_url=mock_post_url,
                )
                last_platform_post_id = mock_post_id
                published_results.append({
                    "item_index": idx,
                    "status": "success",
                    "post_id": mock_post_id,
                    "url": mock_post_url,
                    "dry_run": True,
                })
            else:
                # 실제 또는 주입된 어댑터를 통한 라이브 발행
                try:
                    if platform == "threads":
                        adapter_res = self._threads_adapter(
                            text=content,
                            reply_to_id=last_platform_post_id,
                            image_url=media_url,
                        )
                        post_id = str(adapter_res.get("media_id") or adapter_res.get("id", ""))
                        post_url = adapter_res.get("url") or f"https://www.threads.net/t/{post_id}"
                    elif platform == "x":
                        adapter_res = self._x_adapter(
                            text=content,
                            reply_to_id=last_platform_post_id,
                            media_ids=[media_url] if media_url else None,
                        )
                        post_id = str(adapter_res.get("id", ""))
                        post_url = adapter_res.get("url") or f"https://x.com/i/web/status/{post_id}"
                    else:
                        raise ValueError(f"지원하지 않는 플랫폼: {platform}")

                    if not post_id:
                        raise RuntimeError(f"발행 응답에 post_id가 없습니다: {adapter_res}")

                    self.store.update_job_item(
                        job_id=job_id,
                        item_index=idx,
                        status="published",
                        platform_post_id=post_id,
                        platform_post_url=post_url,
                    )
                    last_platform_post_id = post_id
                    published_results.append({
                        "item_index": idx,
                        "status": "success",
                        "post_id": post_id,
                        "url": post_url,
                    })

                except Exception as e:
                    has_failure = True
                    failure_error_msg = social_store.sanitize_sensitive_data(str(e))
                    self.store.update_job_item(
                        job_id=job_id,
                        item_index=idx,
                        status="failed",
                        error_message=failure_error_msg,
                    )
                    published_results.append({
                        "item_index": idx,
                        "status": "failed",
                        "error": failure_error_msg,
                    })
                    # 중간 실패 시 즉시 중단 (타래 연속성 보장 위해 이후 포스트 발행 보류)
                    break

        # 4. 최종 작업 상태 전이
        success_count = sum(1 for r in published_results if r["status"] in ("success", "already_published"))
        total_count = len(items)

        result_payload = {
            "platform": platform,
            "dry_run": effective_dry_run,
            "total_items": total_count,
            "successful_items": success_count,
            "results": published_results,
        }

        if not has_failure and success_count == total_count:
            # 전체 성공
            finished_job = self.store.transition_job_status(
                job_id,
                "succeeded",
                worker_id=worker_id,
                result_payload=result_payload,
            )
            return {"status": "succeeded", "job": finished_job, "results": published_results}

        elif success_count > 0:
            # 부분 성공 (Partial Failure)
            finished_job = self.store.transition_job_status(
                job_id,
                "partial",
                worker_id=worker_id,
                error_code="PARTIAL_FAILURE",
                error_message=f"{total_count}개 중 {success_count}개 성공 후 실패: {failure_error_msg}",
                result_payload=result_payload,
            )
            return {"status": "partial", "job": finished_job, "results": published_results}

        else:
            # 전체 실패
            finished_job = self.store.transition_job_status(
                job_id,
                "failed",
                worker_id=worker_id,
                error_code="PUBLISH_FAILED",
                error_message=failure_error_msg or "모든 항목 발행 실패",
                result_payload=result_payload,
            )
            return {"status": "failed", "job": finished_job, "results": published_results}
