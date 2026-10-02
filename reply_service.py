"""Threads 및 X(Twitter) 댓글·답글 자동화 서비스 모듈.

작업지시서 Phase 5 요구사항 충족:
- Threads 및 X 대상 게시물 답글 발행 기능
- 최근 댓글·답글 읽기 및 권한 부족 시 unsupported/permission_required 반환
- 댓글 목록 기반 답글 초안 생성 및 사용자 수정/승인 모델
- 승인되지 않은 답글(unapproved) 실행 엄격 차단
- 배치 답글 실행: 승인된 항목만 대상, 실행 전 미리보기 제공
- 원댓글 ID 기반 중복 답글 방지 (Dedup & Idempotency)
- 부분 실패(Partial Failure) 집계 및 격리
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import content_service
import social_store
import threads_client
import x_client


class ReplyAutomationError(Exception):
    """답글 자동화 예외"""

    def __init__(self, message: str, code: str = "REPLY_ERROR"):
        super().__init__(social_store.sanitize_sensitive_data(message))
        self.code = code


class ReplyService:
    """댓글 조회 및 답글 자동화 오케스트레이터"""

    def __init__(
        self,
        store: Optional[social_store.SocialStore] = None,
        threads_fetcher: Optional[Callable[[str], Dict[str, Any]]] = None,
        x_fetcher: Optional[Callable[[str], Dict[str, Any]]] = None,
        threads_adapter: Optional[Callable[..., Dict[str, Any]]] = None,
        x_adapter: Optional[Callable[..., Dict[str, Any]]] = None,
    ):
        self.store = store or social_store.SocialStore()
        self._threads_fetcher = threads_fetcher
        self._x_fetcher = x_fetcher
        self._threads_adapter = threads_adapter or threads_client.publish_single_post
        self._x_adapter = x_adapter or x_client.publish_tweet

    # ==========================================
    # 1. 댓글 조회 (권한 검증 및 unsupported 보고)
    # ==========================================
    def fetch_post_replies(
        self,
        platform: str,
        post_id: str,
    ) -> Dict[str, Any]:
        """
        대상 게시물의 최근 댓글/답글 목록 조회.
        권한 부족 또는 미지원 시 웹 자동화로 임의 대체하지 않고
        'permission_required' 또는 'unsupported'로 안전하게 반환.
        """
        plat = content_service.normalize_platform(platform)
        clean_post_id = (post_id or "").strip()
        if not clean_post_id:
            raise ValueError("post_id가 비어 있습니다.")

        # 주입된 모의 페처가 있는 경우 우선 실행
        if plat == "threads" and self._threads_fetcher:
            return self._threads_fetcher(clean_post_id)
        elif plat == "x" and self._x_fetcher:
            return self._x_fetcher(clean_post_id)

        # 기본 라이브 조회 및 권한 확인
        if plat == "threads":
            conf = threads_client.load_config()
            token = conf.get("access_token")
            if not token:
                return {
                    "platform": "threads",
                    "status": "permission_required",
                    "code": "AUTH_REQUIRED",
                    "message": "Threads 액세스 토큰이 등록되지 않았습니다.",
                    "replies": [],
                }

            # Threads replies 엔드포인트 호출 시도
            url = f"{threads_client.THREADS_API_BASE}/{clean_post_id}/replies"
            try:
                res = threads_client._http_request(
                    url,
                    params={
                        "fields": "id,text,username,timestamp",
                        "access_token": token,
                    },
                )
                data = res.get("data", [])
                replies = [
                    {
                        "id": str(r.get("id", "")),
                        "text": r.get("text", ""),
                        "username": r.get("username", ""),
                        "created_at": r.get("timestamp", ""),
                    }
                    for r in data
                ]
                return {
                    "platform": "threads",
                    "status": "success",
                    "post_id": clean_post_id,
                    "replies": replies,
                }
            except Exception as e:
                err_msg = str(e).lower()
                if "scope" in err_msg or "permission" in err_msg or "403" in err_msg:
                    return {
                        "platform": "threads",
                        "status": "permission_required",
                        "code": "PERMISSION_REQUIRED",
                        "message": "댓글 조회를 위한 Threads 권한(threads_read_replies)이 필요합니다.",
                        "replies": [],
                    }
                return {
                    "platform": "threads",
                    "status": "unsupported",
                    "code": "UNSUPPORTED",
                    "message": f"댓글 조회 중 오류 발생: {social_store.sanitize_sensitive_data(str(e))}",
                    "replies": [],
                }

        elif plat == "x":
            # X API v2는 Search API 권한(Basic 이상) 필요
            x_status = x_client.get_status(store=self.store)
            if not x_status.get("connected"):
                return {
                    "platform": "x",
                    "status": "permission_required",
                    "code": "AUTH_REQUIRED",
                    "message": "X 계정이 연동되어 있지 않습니다.",
                    "replies": [],
                }

            # 무료 티어 또는 권한 부족 시 무단 웹스크래핑 대신 unsupported/permission_required 보고
            return {
                "platform": "x",
                "status": "unsupported",
                "code": "UNSUPPORTED",
                "message": "현재 X API 플랜에서 댓글 검색 API 조회가 지원되지 않습니다 (permission_required).",
                "replies": [],
            }

        return {"status": "unsupported", "replies": []}

    # ==========================================
    # 2. 댓글 목록 기반 답글 초안 생성
    # ==========================================
    def create_reply_drafts_from_comments(
        self,
        platform: str,
        comments: List[Dict[str, Any]],
        actor_account_id: str,
        tone: str = "friendly",
        post_context: Optional[str] = None,
        dry_run: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        수신된 댓글 목록을 바탕으로 AI 답글 초안을 생성하여 social_jobs(draft)로 저장.
        """
        plat = content_service.normalize_platform(platform)
        created_drafts: List[Dict[str, Any]] = []

        for c in comments:
            comment_id = str(c.get("id") or "").strip()
            comment_text = c.get("text", "").strip()
            if not comment_id or not comment_text:
                continue

            # 이미 해당 원댓글에 답글을 달았는지 확인
            if self.store.is_action_already_done(plat, actor_account_id, "reply", comment_id):
                continue

            # AI 답글 텍스트 생성
            reply_gen = content_service.generate_reply_draft(
                platform=plat,
                original_post=comment_text,
                post_context=post_context,
                tone=tone,
            )
            reply_text = reply_gen.get("reply", "")

            # 초안 작업 생성
            job = self.store.create_job(
                platform=plat,
                job_type="reply",
                actor_account_id=actor_account_id,
                target_id=comment_id,
                dry_run=dry_run,
                content_payload={
                    "original_comment_id": comment_id,
                    "original_comment_text": comment_text,
                    "reply_text": reply_text,
                    "tone": tone,
                    "author": c.get("username", ""),
                },
            )
            # 하위 아이템 1개 생성
            self.store.add_job_items(
                job["job_id"],
                [{"item_index": 0, "content": reply_text, "status": "pending"}],
            )
            created_drafts.append({
                "job_id": job["job_id"],
                "target_comment_id": comment_id,
                "original_text": comment_text,
                "suggested_reply": reply_text,
                "status": "draft",
            })

        return created_drafts

    # ==========================================
    # 3. 배치 실행 전 미리보기 (승인 여부 확인)
    # ==========================================
    def preview_batch_replies(self, job_ids: List[str]) -> Dict[str, Any]:
        """
        배치 실행 전 대상 목록, 승인 상태, 예상 동작 수를 반환.
        """
        targets = []
        approved_count = 0
        unapproved_count = 0

        for jid in job_ids:
            job = self.store.get_job(jid)
            if not job or job["job_type"] != "reply":
                continue

            items = self.store.get_job_items(jid)
            reply_text = items[0]["content"] if items else ""
            is_approved = (job["approved_at"] > 0 and job["status"] in ("approved", "scheduled"))

            if is_approved:
                approved_count += 1
            else:
                unapproved_count += 1

            targets.append({
                "job_id": jid,
                "platform": job["platform"],
                "target_comment_id": job["target_id"],
                "reply_text": reply_text,
                "status": job["status"],
                "is_approved": is_approved,
            })

        return {
            "total_requested": len(targets),
            "approved_count": approved_count,
            "unapproved_count": unapproved_count,
            "can_execute": approved_count > 0,
            "targets": targets,
        }

    # ==========================================
    # 4. 배치 답글 실행 (승인 필수, 중복 차단, 부분 실패 격리)
    # ==========================================
    def execute_batch_replies(
        self,
        job_ids: List[str],
        worker_id: str,
        dry_run: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        승인된 답글 작업을 배치 실행.
        - 승인 누락 차단: approved_at == 0 인 작업은 절대 실행하지 않음
        - 중복 방지: 동일 target_id에 대해 중복 답글 방지
        - 부분 실패 격리: 개별 답글 실패가 다른 답글 실행을 차단하지 않음
        """
        results: List[Dict[str, Any]] = []

        for jid in job_ids:
            job = self.store.get_job(jid)
            if not job:
                results.append({"job_id": jid, "status": "error", "error": "존재하지 않는 작업 ID"})
                continue

            if job["job_type"] != "reply":
                results.append({"job_id": jid, "status": "error", "error": "reply 작업이 아닙니다."})
                continue

            # 1. 승인 누락 차단 (Strict Approval Enforcement)
            if job["approved_at"] <= 0 or job["status"] not in ("approved", "scheduled", "partial"):
                results.append({
                    "job_id": jid,
                    "target_comment_id": job["target_id"],
                    "status": "unapproved_blocked",
                    "error": f"승인되지 않은 작업은 실행할 수 없습니다 (status: {job['status']}, approved_at: {job['approved_at']}).",
                })
                continue

            platform = job["platform"]
            target_id = job["target_id"]
            actor_account_id = job["actor_account_id"]
            effective_dry_run = dry_run if dry_run is not None else bool(job["dry_run"])

            # 2. 중복 방지 검사 (Dedup check)
            if self.store.is_action_already_done(platform, actor_account_id, "reply", target_id, dry_run=effective_dry_run):
                results.append({
                    "job_id": jid,
                    "target_comment_id": target_id,
                    "status": "skipped_duplicate",
                    "message": "이미 답글이 작성된 댓글 대상입니다.",
                })
                continue

            items = self.store.get_job_items(jid)
            if not items:
                results.append({"job_id": jid, "status": "error", "error": "답글 본문이 없습니다."})
                continue

            reply_text = items[0]["content"]

            # 3. running 상태 전이 (워커 소유권 펜싱)
            try:
                self.store.transition_job_status(jid, "running", worker_id=worker_id)
            except Exception as e:
                results.append({"job_id": jid, "status": "error", "error": str(e)})
                continue

            # 4. 실행 (드라이런 또는 라이브 어댑터)
            try:
                if effective_dry_run:
                    post_id = f"mock_reply_{platform}_{jid}"
                    post_url = f"https://{platform}.com/reply/{post_id}"
                else:
                    if platform == "threads":
                        adapter_res = self._threads_adapter(text=reply_text, reply_to_id=target_id)
                        post_id = str(adapter_res.get("media_id") or adapter_res.get("id", ""))
                        post_url = adapter_res.get("url") or f"https://www.threads.net/t/{post_id}"
                    elif platform == "x":
                        adapter_res = self._x_adapter(text=reply_text, reply_to_id=target_id)
                        post_id = str(adapter_res.get("id", ""))
                        post_url = adapter_res.get("url") or f"https://x.com/i/web/status/{post_id}"
                    else:
                        raise ValueError(f"지원하지 않는 플랫폼: {platform}")

                # 5. DB 및 중복 방지 키 기록
                self.store.record_dedup_action(
                    platform=platform,
                    actor_account_id=actor_account_id,
                    action="reply",
                    target_id=target_id,
                    dry_run=effective_dry_run,
                    job_id=jid,
                )
                self.store.update_job_item(
                    job_id=jid,
                    item_index=0,
                    status="published",
                    platform_post_id=post_id,
                    platform_post_url=post_url,
                )
                self.store.transition_job_status(
                    jid,
                    "succeeded",
                    worker_id=worker_id,
                    result_payload={"platform_post_id": post_id, "url": post_url},
                )
                results.append({
                    "job_id": jid,
                    "target_comment_id": target_id,
                    "status": "success",
                    "reply_post_id": post_id,
                    "url": post_url,
                    "dry_run": effective_dry_run,
                })

            except Exception as e:
                clean_err = social_store.sanitize_sensitive_data(str(e))
                self.store.update_job_item(job_id=jid, item_index=0, status="failed", error_message=clean_err)
                self.store.transition_job_status(
                    jid, "failed", worker_id=worker_id, error_code="REPLY_FAILED", error_message=clean_err
                )
                results.append({
                    "job_id": jid,
                    "target_comment_id": target_id,
                    "status": "failed",
                    "error": clean_err,
                })

        success_count = sum(1 for r in results if r["status"] == "success")
        failure_count = sum(1 for r in results if r["status"] == "failed")
        blocked_count = sum(1 for r in results if r["status"] in ("unapproved_blocked", "skipped_duplicate"))

        return {
            "total_processed": len(results),
            "success_count": success_count,
            "failure_count": failure_count,
            "blocked_count": blocked_count,
            "results": results,
        }
